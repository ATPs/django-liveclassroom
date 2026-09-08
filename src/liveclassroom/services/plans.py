"""Lesson snapshots and independent session plans; no student data is copied."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from django.db import transaction

from liveclassroom.models import (
    ActivityDefinition,
    ClassroomAsset,
    Flow,
    FlowSnapshot,
    FlowStep,
    LiveActivity,
    LiveSession,
    SessionChannelState,
    SessionPlanStep,
)
from liveclassroom.services.classroom import (
    ClassroomError,
    _advance_version,
    _append_event,
    _ensure_run_revision,
    activity_snapshot,
    can_manage_session,
    validate_activity_snapshot,
)
from liveclassroom.services.events import notify_session_after_commit
from liveclassroom.services.permissions import can_author_course, can_teach, can_use_activity_definition, can_use_flow


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def flow_manifest(flow: Flow) -> list[dict]:
    return [
        {
            "key": str(step.key),
            "snapshot": deepcopy(activity_snapshot(step)),
            "asset_id": step.activity_definition.asset_id,
        }
        for step in flow.steps.select_related("activity_definition", "activity_definition__current_revision").order_by(
            "position"
        )
    ]


def session_manifest(session: LiveSession) -> list[dict]:
    return [
        {"key": str(step.key), "snapshot": deepcopy(step.snapshot), "asset_id": step.asset_id}
        for step in session.plan_steps.filter(removed=False)
    ]


def content_signature(row: dict | None):
    if row is None:
        return None
    snapshot = row["snapshot"]
    return {
        "snapshot": {
            k: v
            for k, v in snapshot.items()
            if k
            not in {
                "activity_definition_id",
                "activity_definition_revision_id",
            }
        },
        "asset_id": row.get("asset_id"),
    }


def lesson_token(flow: Flow) -> str:
    return fingerprint({"title": flow.title, "description": flow.description, "steps": flow_manifest(flow)})


def make_snapshot(*, title: str, manifest: list[dict], flow=None) -> FlowSnapshot:
    snapshot = FlowSnapshot.objects.create(
        flow=flow,
        title=title,
        manifest=deepcopy(manifest),
        fingerprint=fingerprint(manifest),
    )
    snapshot.assets.set({row["asset_id"] for row in manifest if row.get("asset_id")})
    return snapshot


@transaction.atomic
def initialize_session_plan(session: LiveSession) -> None:
    """Also keep trusted direct ORM creation consistent with the public service."""
    if session.source_snapshot_id or not session.flow_id:
        return
    flow = Flow.objects.select_for_update().get(pk=session.flow_id)
    manifest = flow_manifest(flow)
    snapshot = make_snapshot(title=flow.title, manifest=manifest, flow=flow)
    LiveSession.objects.filter(pk=session.pk).update(source_snapshot=snapshot)
    session.source_snapshot = snapshot
    for position, row in enumerate(manifest, 1):
        SessionPlanStep.objects.create(session=session, position=position, **row)


def _settings(owner, course, options):
    from liveclassroom.conf import guests_allowed

    if not can_teach(owner):
        raise ClassroomError("An authorized teacher is required.")
    if course is not None and not can_author_course(owner, course):
        raise ClassroomError("You do not have permission to use this class.")
    values = {
        "access_mode": "guest" if guests_allowed() else "authenticated",
        "admission_mode": "open",
        "chat_enabled": False,
    }
    values.update((course.session_defaults or {}) if course else {})
    values.update({k: v for k, v in options.items() if v is not None})
    if values["access_mode"] not in LiveSession.AccessMode.values:
        raise ClassroomError("Unsupported student access mode.")
    if not guests_allowed() and values["access_mode"] != "authenticated":
        raise ClassroomError("Guest classroom entry is disabled by this host.")
    if values["admission_mode"] not in LiveSession.AdmissionMode.values:
        raise ClassroomError("Unsupported admission mode.")
    if values["admission_mode"] == "roster" and (course is None or values["access_mode"] == "guest"):
        raise ClassroomError("Roster entry requires a class and authenticated access.")
    if not isinstance(values["chat_enabled"], bool):
        raise ClassroomError("chat_enabled must be a boolean.")
    return {k: values[k] for k in ("access_mode", "admission_mode", "chat_enabled")}


@transaction.atomic
def create_session(*, owner, title, course=None, flow=None, source=None, **options) -> LiveSession:
    if not can_teach(owner):
        raise ClassroomError("An authorized teacher is required to create a classroom.")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        raise ClassroomError("A session title of at most 200 characters is required.")
    if source is not None:
        previous = source.creation_settings or {
            "access_mode": source.access_mode,
            "admission_mode": source.admission_mode,
            "chat_enabled": False,
        }
        inherited = previous if course is None else {}
        options = {**inherited, **options}
    values = _settings(owner, course, options)
    if source is not None:
        source = LiveSession.objects.select_for_update().get(pk=source.pk)
        if not can_manage_session(owner, source):
            raise ClassroomError("You do not have permission to reuse this classroom.")
        snapshot = make_snapshot(title=source.title, manifest=session_manifest(source), flow=source.flow)
        session = LiveSession.objects.create(
            teacher=owner,
            title=title.strip(),
            course=course,
            source_session=source,
            source_snapshot=snapshot,
            flow=source.flow,
            **values,
        )
        for position, row in enumerate(snapshot.manifest, 1):
            SessionPlanStep.objects.create(session=session, position=position, **row)
    else:
        if flow is not None and not can_use_flow(owner, flow):
            raise ClassroomError("You do not have permission to use this lesson.")
        session = LiveSession.objects.create(teacher=owner, title=title.strip(), course=course, flow=flow, **values)
    from .classroom import ensure_channel_states

    ensure_channel_states(session)
    session.creation_settings = values
    session.save(update_fields=["creation_settings"])
    _advance_version(session)
    _append_event(session, "session.created", owner, {"source_session_id": getattr(source, "pk", None)})
    return session


def plan_changed(session, actor, kind="plan.updated"):
    session.plan_version += 1
    session.save(update_fields=["plan_version", "updated_at"])
    version = _advance_version(session)
    event = _append_event(session, kind, actor, {"plan_version": session.plan_version})
    notify_session_after_commit(session.pk, {"version": version, "event_id": event, "type": kind})


def lock_plan(session, actor, expected_version=None):
    session = LiveSession.objects.select_for_update().get(pk=session.pk)
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to edit this classroom.")
    if session.status == LiveSession.Status.ENDED:
        raise ClassroomError("An ended classroom's teaching content cannot be changed.")
    if expected_version is not None and (
        isinstance(expected_version, bool) or expected_version != session.plan_version
    ):
        raise ClassroomError("The classroom plan changed; refresh and compare again.")
    return session


def copy_definition(*, actor, snapshot, asset=None, course=None):
    """Internal only: caller has authorized the source lesson or session."""
    snapshot = validate_activity_snapshot(deepcopy(snapshot))
    if snapshot.get("type_key") == "liveclassroom.file":
        if asset is None or snapshot.get("content", {}).get("asset_id") != str(asset.public_id):
            raise ClassroomError("The file reference is unavailable.")
    elif asset is not None:
        raise ClassroomError("Only file content can reference a classroom asset.")
    return ActivityDefinition.objects.create(
        owner=actor,
        course=course,
        title=snapshot.get("title") or "Activity",
        type_key=snapshot["type_key"],
        schema_version=snapshot.get("schema_version", 1),
        definition=snapshot["content"],
        asset=asset,
        status=ActivityDefinition.Status.READY,
    )


@transaction.atomic
def copy_lesson(*, flow, actor, title=None, slug=None):
    from .flows import create_flow

    flow = Flow.objects.select_for_update().get(pk=flow.pk)
    if not can_use_flow(actor, flow):
        raise ClassroomError("You do not have permission to use this lesson.")
    new = create_flow(creator=actor, title=title or f"{flow.title} (Copy)", slug=slug)
    for position, row in enumerate(flow_manifest(flow), 1):
        asset = ClassroomAsset.objects.filter(pk=row["asset_id"]).first() if row["asset_id"] else None
        definition = copy_definition(actor=actor, snapshot=row["snapshot"], asset=asset)
        FlowStep.objects.create(flow=new, position=position, key=row["key"], activity_definition=definition)
    return new


@transaction.atomic
def save_lesson(*, session, actor, title, slug=None):
    from .flows import create_flow

    session = LiveSession.objects.select_for_update().get(pk=session.pk)
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to save this classroom.")
    flow = create_flow(creator=actor, title=title, slug=slug)
    for position, step in enumerate(session.plan_steps.filter(removed=False).select_related("asset"), 1):
        definition = copy_definition(actor=actor, snapshot=step.snapshot, asset=step.asset)
        FlowStep.objects.create(flow=flow, key=step.key, position=position, activity_definition=definition)
    return flow


@transaction.atomic
def add_plan_step(*, session, actor, definition=None, snapshot=None, expected_version=None):
    session = lock_plan(session, actor, expected_version)
    asset = None
    if definition is not None:
        if not can_use_activity_definition(actor, definition):
            raise ClassroomError("You do not have permission to use this activity.")
        if definition.status == ActivityDefinition.Status.ARCHIVED:
            raise ClassroomError("Archived activities cannot be added to a classroom.")
        snapshot = activity_snapshot(definition)
        asset = definition.asset
    else:
        snapshot = validate_activity_snapshot(snapshot)
        if not snapshot.get("type_key"):
            raise ClassroomError("A registered activity type is required.")
        if snapshot.get("type_key") == "liveclassroom.file":
            raise ClassroomError("Select an authorized material instead of entering a file reference.")
    step = SessionPlanStep.objects.create(
        session=session,
        snapshot=deepcopy(snapshot),
        asset=asset,
        position=(session.plan_steps.order_by("-position").values_list("position", flat=True).first() or 0) + 1,
    )
    plan_changed(session, actor)
    return step


@transaction.atomic
def edit_plan_step(*, session, step, actor, snapshot=None, remove=False, expected_version=None):
    session = lock_plan(session, actor, expected_version)
    step = SessionPlanStep.objects.select_for_update().get(pk=step.pk, session=session, removed=False)
    if step.runs.exists():
        raise ClassroomError("Edit the launched activity separately; its history must be preserved.")
    if remove:
        step.removed = True
    else:
        snapshot = validate_activity_snapshot(snapshot)
        if not snapshot.get("type_key"):
            raise ClassroomError("A registered activity type is required.")
        if snapshot.get("type_key") == "liveclassroom.file":
            if not step.asset or snapshot.get("content", {}).get("asset_id") != str(step.asset.public_id):
                raise ClassroomError("The file reference cannot be changed here.")
        elif step.asset_id:
            step.asset = None
        step.snapshot = deepcopy(snapshot)
    step.save(update_fields=["snapshot", "asset", "removed"])
    plan_changed(session, actor)
    return step


@transaction.atomic
def reorder_plan(*, session, actor, keys, expected_version):
    session = lock_plan(session, actor, expected_version)
    steps = {str(s.key): s for s in session.plan_steps.filter(removed=False)}
    if not isinstance(keys, list) or len(keys) != len(steps) or set(keys) != set(steps):
        raise ClassroomError("Supply every classroom step exactly once.")
    for position, key in enumerate(keys, 1):
        SessionPlanStep.objects.filter(pk=steps[key].pk).update(position=position)
    plan_changed(session, actor)


@transaction.atomic
def launch_plan_step(*, session, step, actor, channel="display", restart=False):
    from .classroom import initialize_timer_runtime, publish_activity_to_audiences, publish_activity_to_channel

    session = lock_plan(session, actor)
    if session.status != LiveSession.Status.LIVE:
        raise ClassroomError("Start the session before publishing an item.")
    if channel not in {*SessionChannelState.Channel.values, "both"}:
        raise ClassroomError("Unsupported session channel.")
    step = SessionPlanStep.objects.select_for_update().get(pk=step.pk, session=session, removed=False)
    existing = step.runs.order_by("-sequence").first()
    if existing and not restart:
        if channel == "both":
            publish_activity_to_audiences(
                session=session, activity=existing, channels=["display", "participants"], actor=actor,
            )
        else:
            publish_activity_to_channel(session=session, activity=existing, channel=channel, actor=actor)
        return existing
    snapshot = validate_activity_snapshot(deepcopy(step.snapshot))
    activity = LiveActivity.objects.create(
        session=session,
        plan_step=step,
        sequence=(session.activities.order_by("-sequence").values_list("sequence", flat=True).first() or 0) + 1,
        kind=snapshot["type_key"].rsplit(".", 1)[-1],
        definition_snapshot=snapshot,
    )
    from liveclassroom.models import ActivityDefinitionRevision

    source_revision = ActivityDefinitionRevision.objects.filter(
        pk=snapshot.get("activity_definition_revision_id")
    ).first()
    revision = _ensure_run_revision(activity, actor, source_revision=source_revision)
    revision.asset = step.asset
    revision.save(update_fields=["asset"])
    initialize_timer_runtime(activity)
    if channel == "both":
        publish_activity_to_audiences(
            session=session, activity=activity, channels=["display", "participants"], actor=actor,
        )
    else:
        publish_activity_to_channel(session=session, activity=activity, channel=channel, actor=actor)
    _append_event(session, "activity.opened", actor, {"activity_id": activity.id, "plan_step_id": step.id})
    return activity


@transaction.atomic
def launch_source(*, session, item, actor, channel="display"):
    session = lock_plan(session, actor)
    if isinstance(item, FlowStep) and session.flow_id == item.flow_id:
        step = session.plan_steps.filter(key=item.key, removed=False).first()
        if step is None:
            raise ClassroomError("This step is not in the classroom plan; update the plan explicitly.")
    else:
        definition = item if isinstance(item, ActivityDefinition) else item.activity_definition
        if isinstance(item, FlowStep) and not can_use_flow(actor, item.flow):
            raise ClassroomError("You do not have permission to use this lesson.")
        step = add_plan_step(session=session, actor=actor, definition=definition)
    return launch_plan_step(session=session, step=step, actor=actor, channel=channel)
