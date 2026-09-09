"""Shared session versioning and timer runtime primitives."""

from __future__ import annotations

import math
from typing import Any

from django.db import transaction
from django.utils import timezone

from liveclassroom.models import (
    ActivityDefinition,
    ActivityRunRevision,
    CourseMembership,
    FlowStep,
    LiveActivity,
    LiveSession,
    Participant,
    SessionEvent,
    SessionStaff,
)

from .events import notify_session_after_commit
from .permissions import can_teach


class ClassroomError(Exception):
    """A command error that is safe to return from the JSON API."""


def can_manage_session(user, session: LiveSession) -> bool:
    if not can_teach(user):
        return False
    if (user.pk == session.teacher_id or user.is_superuser
            or (session.course_id and session.course.created_by_id == user.pk)):
        return True
    if SessionStaff.objects.filter(
        session=session,
        user=user,
        role=SessionStaff.Role.COHOST,
    ).exists():
        return True
    return bool(
        session.course_id
        and CourseMembership.objects.filter(
            course_id=session.course_id,
            user=user,
            role=CourseMembership.Role.TEACHER,
        ).exists()
    )


def _append_event(
    session: LiveSession,
    event_type: str,
    actor=None,
    payload: dict | None = None,
    participant: Participant | None = None,
) -> int:
    locked_session = LiveSession.objects.select_for_update().get(pk=session.pk)
    sequence = (locked_session.events.order_by("-sequence").values_list("sequence", flat=True).first() or 0) + 1
    event = SessionEvent.objects.create(
        session=locked_session,
        sequence=sequence,
        event_type=event_type,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        participant=participant,
        payload=payload or {},
    )
    return event.id


def _advance_version(session: LiveSession) -> int:
    locked_session = LiveSession.objects.select_for_update().get(pk=session.pk)
    locked_session.state_version += 1
    locked_session.save(update_fields=["state_version", "updated_at"])
    session.state_version = locked_session.state_version
    return locked_session.state_version


def activity_snapshot(item: FlowStep | ActivityDefinition) -> dict[str, Any]:
    """Capture all display and grading details so source content may change later."""
    definition = getattr(item, "activity_definition", None)
    if isinstance(item, ActivityDefinition):
        definition = item
    if definition is None:
        raise ClassroomError("A flow step must reference an activity definition.")
    if definition.pk and not definition.current_revision_id:
        definition.refresh_from_db(fields=["definition", "current_revision"])
    return {
        "schema_version": definition.schema_version,
        "type_key": definition.type_key,
        "kind": definition.type_key.rsplit(".", 1)[-1],
        "title": definition.title,
        "content": definition.definition,
        "metadata": definition.metadata,
        "activity_definition_id": definition.id,
        "activity_definition_revision_id": definition.current_revision_id,
    }


def _ensure_run_revision(activity: LiveActivity, actor=None, source_revision=None) -> ActivityRunRevision:
    locked_activity = LiveActivity.objects.select_for_update().get(pk=activity.pk)
    revision = locked_activity.current_revision
    if revision is not None:
        activity.current_revision = revision
        activity.current_revision_id = revision.id
        return revision
    revision = ActivityRunRevision.objects.create(
        activity=locked_activity,
        revision=1,
        definition_snapshot=locked_activity.definition_snapshot,
        asset=getattr(source_revision, "asset", None),
        source_revision=source_revision,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    locked_activity.current_revision = revision
    locked_activity.save(update_fields=["current_revision"])
    activity.current_revision = revision
    activity.current_revision_id = revision.id
    return revision


def _activity_validation_definition(activity: LiveActivity) -> dict[str, Any]:
    """Return the definition payload used to validate and aggregate a run's answers."""
    definition = (
        activity.current_revision.definition_snapshot
        if activity.current_revision_id
        else activity.definition_snapshot
    )
    if not isinstance(definition, dict):
        return {}
    definition_content = definition.get("content", definition)
    if not isinstance(definition_content, dict):
        definition_content = definition
    validation_definition = definition_content
    if isinstance(definition.get("question"), dict):
        question = definition["question"]
        question_data = question.get("data") if isinstance(question.get("data"), dict) else {}
        validation_definition = {
            **definition_content,
            "options": question_data.get("options", question_data.get("choices", [])),
            "answer": question.get("answer"),
        }
    return validation_definition


def timer_runtime_state(activity: LiveActivity, *, now=None) -> dict[str, Any]:
    """Return the validated, server-authoritative runtime state for a timer."""
    definition = _activity_validation_definition(activity)
    duration = definition.get("duration_seconds", 60)
    try:
        duration = max(1.0, float(duration))
    except (TypeError, ValueError):
        duration = 60.0
    raw = activity.runtime_state if isinstance(activity.runtime_state, dict) else {}
    status = raw.get("status") if raw.get("status") in {"idle", "running", "paused", "expired"} else "idle"
    try:
        remaining = max(0.0, min(duration, float(raw.get("remaining_seconds", duration))))
    except (TypeError, ValueError):
        remaining = duration
    deadline = raw.get("deadline")
    if not isinstance(deadline, (int, float)) or isinstance(deadline, bool) or not math.isfinite(deadline):
        deadline = None
    now_timestamp = (now or timezone.now()).timestamp()
    if status == "running":
        if deadline is None:
            status = "paused"
        else:
            remaining = min(duration, max(0.0, deadline - now_timestamp))
            if remaining <= 0:
                status = "expired"
                deadline = None
    if status in {"idle", "paused", "expired"}:
        deadline = None
    return {
        "status": status,
        "deadline": deadline,
        "remaining_seconds": remaining,
        "paused_by_classroom": bool(raw.get("paused_by_classroom", False)),
    }


def initialize_timer_runtime(activity: LiveActivity, *, now=None) -> dict[str, Any]:
    """Create the immutable-definition-independent timer runtime once per run."""
    if activity.kind != "timer" or activity.runtime_state:
        return timer_runtime_state(activity, now=now)
    runtime = timer_runtime_state(activity, now=now)
    if _activity_validation_definition(activity).get("auto_start") is True:
        current_time = now or timezone.now()
        runtime.update(
            status="running",
            deadline=current_time.timestamp() + runtime["remaining_seconds"],
        )
    activity.runtime_state = runtime
    activity.save(update_fields=["runtime_state"])
    return runtime


@transaction.atomic
def command_timer(*, activity: LiveActivity, action: str, actor) -> dict[str, Any]:
    """Apply one teacher timer command without altering the activity definition."""
    if not can_manage_session(actor, activity.session):
        raise ClassroomError("You do not have permission to control this timer.")
    if action not in {"start", "pause", "resume", "reset"}:
        raise ClassroomError("Unsupported timer action.")
    session = LiveSession.objects.select_for_update().get(pk=activity.session_id)
    activity = LiveActivity.objects.select_for_update().get(pk=activity.pk)
    if activity.kind != "timer":
        raise ClassroomError("This activity is not a timer.")
    if session.status != LiveSession.Status.LIVE:
        raise ClassroomError("Start or resume the classroom before controlling its timer.")
    now = timezone.now()
    runtime = initialize_timer_runtime(activity, now=now)
    if action == "reset":
        duration = timer_runtime_state(activity, now=now)["remaining_seconds"]
        # Reset must use configured duration even after expiry/pausing.
        try:
            duration = float(_activity_validation_definition(activity)["duration_seconds"])
        except (KeyError, TypeError, ValueError):
            duration = 60.0
        runtime = {"status": "idle", "deadline": None, "remaining_seconds": duration, "paused_by_classroom": False}
    elif action == "start":
        if runtime["status"] in {"idle", "paused"}:
            runtime.update(
                status="running",
                deadline=now.timestamp() + runtime["remaining_seconds"],
                paused_by_classroom=False,
            )
    elif action == "pause" and runtime["status"] == "running":
        runtime = timer_runtime_state(activity, now=now)
        runtime.update(status="paused", deadline=None, paused_by_classroom=False)
    elif action == "resume" and runtime["status"] == "paused":
        runtime.update(
            status="running",
            deadline=now.timestamp() + runtime["remaining_seconds"],
            paused_by_classroom=False,
        )
    activity.runtime_state = runtime
    activity.save(update_fields=["runtime_state"])
    version = _advance_version(session)
    event_id = _append_event(session, "timer.updated", actor, {"activity_id": activity.id, "action": action})
    notify_session_after_commit(
        session.id,
        {"protocol": 1, "session_id": session.id, "version": version, "event_id": event_id,
         "type": "timer.updated", "payload": {"activity_id": activity.id}},
    )
    return timer_runtime_state(activity, now=now)
