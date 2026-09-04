"""Transactional commands for the teacher-paced classroom workflow."""

import secrets
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from liveclassroom.models import (
    ActivityDefinition,
    ActivityDefinitionRevision,
    ActivityRunRevision,
    CourseMembership,
    FlowItem,
    FlowStep,
    LiveActivity,
    LiveSession,
    Participant,
    SessionChannelState,
    SessionEvent,
    SessionMessage,
    SessionStaff,
    Submission,
    SubmissionRevision,
)
from liveclassroom.registry import activity_registry

from .events import notify_session_after_commit
from .permissions import can_author_course, can_edit_flow, can_use_activity_definition


class ClassroomError(Exception):
    """A command error that is safe to return from the JSON API."""


_LEGACY_MEDIA_KINDS = frozenset({"image", "video", "url", "iframe"})


def _snapshot_type_key(snapshot: dict[str, Any]) -> str | None:
    type_key = snapshot.get("type_key")
    if isinstance(type_key, str) and type_key.strip():
        return type_key if "." in type_key else f"liveclassroom.{type_key}"
    kind = snapshot.get("kind")
    if isinstance(kind, str) and kind in _LEGACY_MEDIA_KINDS:
        return "liveclassroom.media"
    return None


def validate_activity_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Revalidate a run snapshot, including compatibility media content."""
    if not isinstance(snapshot, dict):
        raise ValueError("An activity snapshot must be an object.")
    type_key = _snapshot_type_key(snapshot)
    if type_key is None:
        return snapshot
    content = snapshot.get("content", {})
    if not isinstance(content, dict):
        raise ValueError("An activity snapshot content value must be an object.")
    if type_key == "liveclassroom.media" and snapshot.get("kind") in _LEGACY_MEDIA_KINDS:
        legacy_type = "iframe" if snapshot["kind"] in {"url", "iframe"} else snapshot["kind"]
        content = {**content, "media_type": content.get("media_type", legacy_type)}
    validated = activity_registry.get(type_key).validate(content)
    result = dict(snapshot)
    result["type_key"] = type_key
    result["content"] = validated
    return result


def safe_activity_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a renderable snapshot, disabling unsafe stored media in place."""
    try:
        return validate_activity_snapshot(snapshot)
    except (KeyError, TypeError, ValueError):
        type_key = _snapshot_type_key(snapshot) if isinstance(snapshot, dict) else None
        if type_key != "liveclassroom.media":
            return {
                key: snapshot[key]
                for key in ("schema_version", "type_key", "kind", "title")
                if isinstance(snapshot, dict) and key in snapshot
            }
        return {
            key: snapshot[key]
            for key in ("schema_version", "type_key", "kind", "title")
            if key in snapshot
        } | {
            "type_key": "liveclassroom.media",
            "content": {"media_disabled": True},
            "media_disabled": True,
        }


def can_manage_session(user, session: LiveSession) -> bool:
    if not user.is_authenticated:
        return False
    if user.pk == session.teacher_id or user.is_superuser:
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


def can_manage_admission(user, session: LiveSession) -> bool:
    if not user.is_authenticated:
        return False
    if user.pk == session.teacher_id or user.is_superuser:
        return True
    if SessionStaff.objects.filter(
        session=session,
        user=user,
        role__in=[SessionStaff.Role.COHOST, SessionStaff.Role.ASSISTANT],
    ).exists():
        return True
    return bool(
        session.course_id
        and CourseMembership.objects.filter(
            course_id=session.course_id,
            user=user,
            role__in=[CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT],
        ).exists()
    )


def can_view_session(user, session: LiveSession) -> bool:
    if not user.is_authenticated:
        return False
    if user.pk == session.teacher_id or user.is_superuser:
        return True
    if can_manage_session(user, session):
        return True
    return SessionStaff.objects.filter(session=session, user=user).exists()


def can_view_display(user, session: LiveSession) -> bool:
    """Return whether a user may open the restricted classroom display."""
    return can_manage_session(user, session)


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


def activity_snapshot(item: FlowItem | FlowStep | ActivityDefinition) -> dict[str, Any]:
    """Capture all display and grading details so source content may change later."""
    definition = getattr(item, "activity_definition", None)
    if isinstance(item, ActivityDefinition):
        definition = item
    if definition is not None:
        if definition.pk and not definition.current_revision_id:
            definition.refresh_from_db(fields=["definition", "current_revision"])
        return {
            "schema_version": definition.schema_version,
            "type_key": definition.type_key,
            "kind": definition.type_key.rsplit(".", 1)[-1],
            "title": definition.title,
            "content": definition.definition,
            "activity_definition_id": definition.id,
            "activity_definition_revision_id": definition.current_revision_id,
        }

    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "kind": item.kind,
        "title": item.title,
        "content": item.content,
    }
    if getattr(item, "question_id", None):
        question = item.question
        snapshot["question"] = {
            "id": question.id,
            "type": question.question_type,
            "stem_markdown": question.stem_markdown,
            "data": question.data,
            "answer": question.answer,
            "explanation_markdown": question.explanation_markdown,
        }
    return snapshot


def _validate_launch_source(*, session: LiveSession, item, actor) -> None:
    """Prevent a session controller from launching unrelated private content."""
    flow = getattr(item, "flow", None)
    if flow is not None:
        if session.flow_id and flow.pk != session.flow_id:
            raise ClassroomError("The selected item does not belong to this session's flow.")
        if session.course_id and flow.course_id not in {None, session.course_id}:
            raise ClassroomError("The selected item does not belong to this session's course.")
        # The session's own flow is always launchable by a session manager;
        # otherwise require the same edit rights as flow authoring.
        if session.flow_id != flow.pk and not can_edit_flow(actor, flow):
            raise ClassroomError("You do not have permission to use this flow.")

    definition = item if isinstance(item, ActivityDefinition) else getattr(item, "activity_definition", None)
    if definition is None:
        return
    if definition.course_id and session.course_id != definition.course_id:
        raise ClassroomError("The selected activity does not belong to this session's course.")
    if not can_use_activity_definition(actor, definition):
        raise ClassroomError("You do not have permission to use this activity.")


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


def ensure_channel_states(session: LiveSession) -> list[SessionChannelState]:
    """Return both independent audience channels, creating them for old sessions."""
    states = []
    for channel in SessionChannelState.Channel:
        state, _ = SessionChannelState.objects.get_or_create(session=session, channel=channel)
        states.append(state)
    return states


@transaction.atomic
def create_instant_session(
    *,
    owner,
    title: str,
    access_mode: str = LiveSession.AccessMode.GUEST,
    admission_mode: str = LiveSession.AdmissionMode.OPEN,
    mode: str = LiveSession.Mode.TEACHER_PACED,
) -> LiveSession:
    """Create a session without requiring a course or prepared flow."""
    if not getattr(owner, "is_authenticated", False):
        raise ClassroomError("An authenticated teacher is required to create a session.")
    if not isinstance(title, str):
        raise ClassroomError("A session title is required.")
    title = title.strip()
    if not title:
        raise ClassroomError("A session title is required.")
    if access_mode not in LiveSession.AccessMode.values:
        raise ClassroomError("Unsupported student access mode.")
    if admission_mode not in LiveSession.AdmissionMode.values:
        raise ClassroomError("Unsupported admission mode.")
    if mode not in LiveSession.Mode.values:
        raise ClassroomError("Unsupported session mode.")
    session = LiveSession.objects.create(
        title=title,
        teacher=owner,
        access_mode=access_mode,
        admission_mode=admission_mode,
        mode=mode,
    )
    ensure_channel_states(session)
    _advance_version(session)
    _append_event(session, "session.created", owner)
    return session


@transaction.atomic
def create_activity_definition(
    *, owner, title: str, type_key: str, definition: dict[str, Any], course=None, change_note: str = ""
) -> ActivityDefinition:
    """Create a validated reusable activity and its first immutable revision."""
    if not getattr(owner, "is_authenticated", False):
        raise ClassroomError("An authenticated teacher is required to create an activity.")
    if not isinstance(type_key, str) or not type_key.strip():
        raise ClassroomError("An activity type is required.")
    type_key = type_key.strip()
    if (
        course is not None
        and not getattr(owner, "is_superuser", False)
        and not can_author_course(owner, course)
    ):
        raise ClassroomError("You do not have permission to author content for this course.")
    if "." not in type_key:
        type_key = f"liveclassroom.{type_key}"
    try:
        activity_type = activity_registry.get(type_key)
        definition = activity_type.validate(definition)
    except (KeyError, ValueError) as exc:
        raise ClassroomError(str(exc)) from exc
    if not isinstance(title, str) or not title.strip():
        raise ClassroomError("An activity title is required.")
    activity = ActivityDefinition.objects.create(
        owner=owner,
        course=course,
        type_key=type_key,
        title=title.strip(),
        definition=definition,
        status=ActivityDefinition.Status.READY,
    )
    activity.refresh_from_db(fields=["current_revision"])
    revision = activity.current_revision
    if revision is None:
        revision = activity.revisions.create(
            revision=1,
            schema_version=activity.schema_version,
            payload=definition,
            changed_by=owner,
            change_note=change_note,
        )
    elif change_note and revision.change_note != change_note:
        revision.change_note = change_note
        revision.save(update_fields=["change_note"])
    activity.current_revision = revision
    activity.save(update_fields=["current_revision", "updated_at"])
    return activity


@transaction.atomic
def revise_activity_definition(
    *, activity: ActivityDefinition, definition: dict[str, Any], actor, change_note: str = ""
) -> ActivityDefinitionRevision:
    """Update a reusable definition without rewriting its prior payload."""
    if not getattr(actor, "is_authenticated", False) or (
        activity.owner_id != actor.pk
        and not (activity.course_id and can_author_course(actor, activity.course))
    ):
        raise ClassroomError("You do not have permission to edit this activity.")
    try:
        definition = activity_registry.get(activity.type_key).validate(definition)
    except (KeyError, ValueError) as exc:
        raise ClassroomError(str(exc)) from exc
    latest = activity.revisions.order_by("-revision").first()
    revision = activity.revisions.create(
        revision=(latest.revision if latest else 0) + 1,
        schema_version=activity.schema_version,
        payload=definition,
        changed_by=actor,
        change_note=change_note,
    )
    activity.definition = definition
    activity.current_revision = revision
    activity.save(update_fields=["definition", "current_revision", "updated_at"])
    return revision


@transaction.atomic
def start_session(*, session: LiveSession, actor) -> LiveSession:
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to start this session.")
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    session.state_version = locked.state_version
    if locked.status == LiveSession.Status.ENDED:
        raise ClassroomError("An ended session cannot be restarted.")
    if locked.status != LiveSession.Status.LIVE:
        locked.status = LiveSession.Status.LIVE
        locked.started_at = locked.started_at or timezone.now()
        locked.save(update_fields=["status", "started_at", "updated_at"])
        session.status = locked.status
        session.started_at = locked.started_at
        version = _advance_version(locked)
        event_id = _append_event(locked, "session.started", actor)
        notify_session_after_commit(
            locked.id,
            {
                "protocol": 1,
                "session_id": locked.id,
                "version": version,
                "event_id": event_id,
                "type": "session.started",
                "payload": {},
            },
        )
    else:
        session.status = locked.status
        session.started_at = locked.started_at
    return session


@transaction.atomic
def pause_session(*, session: LiveSession, actor) -> LiveSession:
    """Pause a live classroom while retaining its current activities and answers."""
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to pause this session.")
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    session.state_version = locked.state_version
    if locked.status == LiveSession.Status.PAUSED:
        session.status = locked.status
        session.state_version = locked.state_version
        return session
    if locked.status != LiveSession.Status.LIVE:
        raise ClassroomError("Only a live session can be paused.")
    locked.status = LiveSession.Status.PAUSED
    locked.save(update_fields=["status", "updated_at"])
    session.status = locked.status
    version = _advance_version(locked)
    event_id = _append_event(locked, "session.paused", actor)
    notify_session_after_commit(
        locked.id,
        {
            "protocol": 1,
            "session_id": locked.id,
            "version": version,
            "event_id": event_id,
            "type": "session.paused",
            "payload": {},
        },
    )
    return session


@transaction.atomic
def end_session(*, session: LiveSession, actor) -> LiveSession:
    """End a classroom and close any still-open activity without deleting history."""
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to end this session.")
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    if locked.status == LiveSession.Status.ENDED:
        session.status = locked.status
        session.state_version = locked.state_version
        return session
    now = timezone.now()
    open_activity_ids = list(
        LiveActivity.objects.filter(session=locked, state=LiveActivity.State.OPEN).values_list("id", flat=True)
    )
    LiveActivity.objects.filter(session=locked, state=LiveActivity.State.OPEN).update(
        state=LiveActivity.State.CLOSED,
        closed_at=now,
    )
    locked.status = LiveSession.Status.ENDED
    locked.ended_at = locked.ended_at or now
    locked.chat_enabled = False
    locked.save(update_fields=["status", "ended_at", "chat_enabled", "updated_at"])
    session.status = locked.status
    session.ended_at = locked.ended_at
    version = _advance_version(locked)
    event_id = _append_event(locked, "session.ended", actor, {"closed_activity_ids": open_activity_ids})
    notify_session_after_commit(
        locked.id,
        {
            "protocol": 1,
            "session_id": locked.id,
            "version": version,
            "event_id": event_id,
            "type": "session.ended",
            "payload": {"closed_activity_ids": open_activity_ids},
        },
    )
    return session


@transaction.atomic
def archive_session(*, session: LiveSession, actor, archived: bool = True) -> LiveSession:
    """Archive or restore an ended session without removing its history."""
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to archive this session.")
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    if locked.status != LiveSession.Status.ENDED:
        raise ClassroomError("Only an ended session can be archived.")
    if not isinstance(archived, bool):
        raise ClassroomError("archived must be a boolean.")
    desired = timezone.now() if archived else None
    if (locked.archived_at is not None) == archived:
        session.archived_at = locked.archived_at
        return session
    locked.archived_at = desired
    locked.save(update_fields=["archived_at", "updated_at"])
    session.archived_at = desired
    version = _advance_version(locked)
    event_id = _append_event(
        locked,
        "session.archived" if archived else "session.unarchived",
        actor,
        {"archived": archived},
    )
    notify_session_after_commit(
        locked.id,
        {
            "protocol": 1,
            "session_id": locked.id,
            "version": version,
            "event_id": event_id,
            "type": "session.archived" if archived else "session.unarchived",
            "payload": {"archived": archived},
        },
    )
    return session


@transaction.atomic
def delete_session(*, session: LiveSession, actor) -> None:
    """Permanently delete an archived ended session after explicit confirmation."""
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to delete this session.")
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    if locked.status != LiveSession.Status.ENDED or locked.archived_at is None:
        raise ClassroomError("Archive the ended session before deleting it.")
    locked.delete()


def purge_expired_sessions(*, days: int | None = None) -> int:
    """Delete ended sessions older than the configured retention window."""
    if days is None:
        from liveclassroom.conf import setting

        days = setting("RETENTION_DAYS")
    if days is None:
        return 0
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ClassroomError("Retention days must be a positive integer.")
    cutoff = timezone.now() - timedelta(days=days)
    queryset = LiveSession.objects.filter(status=LiveSession.Status.ENDED, ended_at__isnull=False, ended_at__lt=cutoff)
    session_count = queryset.count()
    queryset.delete()
    return session_count


@transaction.atomic
def launch_item(
    *,
    session: LiveSession,
    item: FlowItem | FlowStep | ActivityDefinition,
    actor,
    channel: str = SessionChannelState.Channel.DISPLAY,
) -> LiveActivity:
    """Open an activity and publish it to one channel.

    Teacher-paced sessions default to the classroom display. Publishing to the
    participant channel is a separate command so opening new display content
    cannot replace what students are answering.
    """
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to control this session.")
    locked_session = LiveSession.objects.select_for_update().get(pk=session.pk)
    # Callers may hold a stale instance after another command advanced the version.
    session.state_version = locked_session.state_version
    session.status = locked_session.status
    if locked_session.status != LiveSession.Status.LIVE:
        raise ClassroomError("Start the session before publishing an item.")
    if channel not in SessionChannelState.Channel.values:
        raise ClassroomError("Unsupported session channel.")
    _validate_launch_source(session=session, item=item, actor=actor)
    try:
        snapshot = validate_activity_snapshot(activity_snapshot(item))
    except (KeyError, TypeError, ValueError) as exc:
        raise ClassroomError("The selected activity contains invalid or unsafe content.") from exc
    definition = item if isinstance(item, ActivityDefinition) else getattr(item, "activity_definition", None)

    sequence = (session.activities.order_by("-sequence").values_list("sequence", flat=True).first() or 0) + 1
    activity = LiveActivity.objects.create(
        session=session,
        sequence=sequence,
        kind=(definition.type_key.rsplit(".", 1)[-1] if definition is not None else item.kind),
        source_item=item if isinstance(item, FlowItem) else None,
        definition_snapshot=snapshot,
    )
    run_revision = _ensure_run_revision(
        activity,
        actor,
        source_revision=definition.current_revision if definition is not None else None,
    )
    update_fields = ["updated_at"]
    if isinstance(item, FlowItem):
        session.current_item = item
        update_fields.append("current_item")
    session.save(update_fields=update_fields)
    channel_state, _ = SessionChannelState.objects.get_or_create(session=session, channel=channel)
    channel_state.current_activity = activity
    channel_state.current_revision = run_revision
    if channel == SessionChannelState.Channel.PARTICIPANTS:
        channel_state.allow_review = activity.reviewable
    version = _advance_version(session)
    channel_state.version = version
    channel_state.save(
        update_fields=["current_activity", "current_revision", "allow_review", "version", "updated_at"]
    )
    event_id = _append_event(session, "activity.opened", actor, {"activity_id": activity.id})
    notify_session_after_commit(
        session.id,
        {
            "protocol": 1,
            "session_id": session.id,
            "version": version,
            "event_id": event_id,
            "type": "activity.opened",
            "payload": {"activity_id": activity.id},
        },
    )
    return activity


@transaction.atomic
def publish_activity_to_channel(
    *, session: LiveSession, activity: LiveActivity, channel: str, actor, allow_review: bool | None = None
) -> SessionChannelState:
    """Publish a run to one audience channel without changing the other channel."""
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to control this session.")
    if activity.session_id != session.id:
        raise ClassroomError("The activity does not belong to this session.")
    if not isinstance(channel, str) or channel not in SessionChannelState.Channel.values:
        raise ClassroomError("Unsupported session channel.")
    if allow_review is not None and not isinstance(allow_review, bool):
        raise ClassroomError("allow_review must be a boolean.")
    revision = _ensure_run_revision(activity, actor)
    state, _ = SessionChannelState.objects.get_or_create(session=session, channel=channel)
    state.current_activity = activity
    state.current_revision = revision
    if channel == SessionChannelState.Channel.PARTICIPANTS:
        if allow_review is not None:
            activity.reviewable = allow_review
            activity.save(update_fields=["reviewable"])
        # ``allow_review`` remains a compatibility mirror for old clients;
        # the activity flag is authoritative for history filtering.
        state.allow_review = activity.reviewable
    elif allow_review is not None:
        state.allow_review = allow_review
    version = _advance_version(session)
    state.version = version
    state.save(update_fields=["current_activity", "current_revision", "allow_review", "version", "updated_at"])
    event_id = _append_event(session, "channel.published", actor, {"channel": channel, "activity_id": activity.id})
    notify_session_after_commit(
        session.id,
        {
            "protocol": 1,
            "session_id": session.id,
            "version": version,
            "event_id": event_id,
            "type": "channel.published",
            "payload": {"channel": channel, "activity_id": activity.id},
        },
    )
    return state


@transaction.atomic
def update_channel_visibility(*, session: LiveSession, channel: str, actor, **changes: bool) -> SessionChannelState:
    """Update audience visibility flags without changing the published activity."""
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to control this session.")
    if not isinstance(channel, str) or channel not in SessionChannelState.Channel.values:
        raise ClassroomError("Unsupported session channel.")
    allowed = {
        "show_prompt",
        "show_aggregate",
        "show_answer",
        "show_explanation",
        "show_own_status",
        "allow_review",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise ClassroomError(f"Unsupported channel settings: {', '.join(sorted(unknown))}.")
    state, _ = SessionChannelState.objects.get_or_create(session=session, channel=channel)
    for key, value in changes.items():
        if not isinstance(value, bool):
            raise ClassroomError(f"{key} must be a boolean.")
        setattr(state, key, value)
    version = _advance_version(session)
    state.version = version
    state.save(update_fields=[*changes, "version", "updated_at"])
    # Keep the compatibility mirror and durable per-activity flag synchronized.
    if channel == SessionChannelState.Channel.PARTICIPANTS and "allow_review" in changes and state.current_activity_id:
        activity = LiveActivity.objects.select_for_update().get(pk=state.current_activity_id)
        activity.reviewable = changes["allow_review"]
        activity.save(update_fields=["reviewable"])
    event_id = _append_event(
        session,
        "channel.visibility.updated",
        actor,
        {"channel": channel, "changes": sorted(changes)},
    )
    notify_session_after_commit(
        session.id,
        {
            "protocol": 1,
            "session_id": session.id,
            "version": version,
            "event_id": event_id,
            "type": "channel.visibility.updated",
            "payload": {"channel": channel},
        },
    )
    return state


@transaction.atomic
def revise_activity(
    *, activity: LiveActivity, definition_snapshot: dict[str, Any], actor, source_revision=None
) -> ActivityRunRevision:
    """Create a new run revision while preserving every prior submission revision."""
    if not can_manage_session(actor, activity.session):
        raise ClassroomError("You do not have permission to edit this activity.")
    activity = LiveActivity.objects.select_for_update().get(pk=activity.pk)
    if activity.state != LiveActivity.State.OPEN:
        raise ClassroomError("Only an open activity can be edited.")
    if not isinstance(definition_snapshot, dict):
        raise ClassroomError("An activity definition must be an object.")
    type_key = definition_snapshot.get("type_key")
    if type_key:
        try:
            activity_registry.get(type_key).validate(definition_snapshot.get("content", definition_snapshot))
        except (KeyError, ValueError) as exc:
            raise ClassroomError(str(exc)) from exc
    latest = activity.revisions.order_by("-revision").first()
    next_revision = (latest.revision if latest else 0) + 1
    revision = ActivityRunRevision.objects.create(
        activity=activity,
        revision=next_revision,
        definition_snapshot=definition_snapshot,
        source_revision=source_revision,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    activity.definition_snapshot = definition_snapshot
    activity.current_revision = revision
    activity.save(update_fields=["definition_snapshot", "current_revision"])
    activity.submissions.filter(is_stale=False).update(is_stale=True)
    version = _advance_version(activity.session)
    activity.session.channel_states.filter(current_activity=activity).update(
        current_revision=revision, version=version
    )
    event_id = _append_event(
        activity.session,
        "activity.revised",
        actor,
        {"activity_id": activity.id, "revision": revision.revision},
    )
    notify_session_after_commit(
        activity.session_id,
        {
            "protocol": 1,
            "session_id": activity.session_id,
            "version": version,
            "event_id": event_id,
            "type": "activity.revised",
            "payload": {"activity_id": activity.id, "revision": revision.revision},
        },
    )
    return revision


@transaction.atomic
def set_activity_state(*, activity: LiveActivity, state: str, actor) -> LiveActivity:
    if not can_manage_session(actor, activity.session):
        raise ClassroomError("You do not have permission to control this session.")
    if state not in {LiveActivity.State.CLOSED, LiveActivity.State.REVEALED}:
        raise ClassroomError("Unsupported activity state.")
    if activity.state == state:
        return activity
    if activity.state == LiveActivity.State.REVEALED and state == LiveActivity.State.CLOSED:
        raise ClassroomError("A revealed activity cannot be closed again.")
    if state == LiveActivity.State.REVEALED and activity.state == LiveActivity.State.OPEN:
        raise ClassroomError("Close the activity before revealing the answer.")

    now = timezone.now()
    activity.state = state
    fields = ["state"]
    event_type = "activity.closed"
    if state == LiveActivity.State.CLOSED:
        activity.closed_at = activity.closed_at or now
        fields.append("closed_at")
    else:
        activity.revealed_at = activity.revealed_at or now
        fields.append("revealed_at")
        event_type = "activity.revealed"
    activity.save(update_fields=fields)
    version = _advance_version(activity.session)
    event_id = _append_event(activity.session, event_type, actor, {"activity_id": activity.id})
    notify_session_after_commit(
        activity.session_id,
        {
            "protocol": 1,
            "session_id": activity.session_id,
            "version": version,
            "event_id": event_id,
            "type": event_type,
            "payload": {"activity_id": activity.id},
        },
    )
    return activity


@transaction.atomic
def join_guest(*, session: LiveSession, display_name: str, guest_id: str | None = None) -> Participant:
    if session.status not in {LiveSession.Status.WAITING, LiveSession.Status.LIVE, LiveSession.Status.PAUSED}:
        raise ClassroomError("This classroom is not accepting participants yet.")
    if session.access_mode == LiveSession.AccessMode.AUTHENTICATED:
        raise ClassroomError("This classroom requires a Django account.")
    if session.admission_mode == LiveSession.AdmissionMode.ROSTER:
        raise ClassroomError("This classroom requires an approved roster participant.")
    if not isinstance(display_name, str):
        raise ClassroomError("A display name is required.")
    display_name = display_name.strip()
    if not display_name:
        raise ClassroomError("A display name is required.")
    if len(display_name) > 100:
        raise ClassroomError("A display name is too long.")
    guest_id = guest_id or secrets.token_urlsafe(24)
    existing = Participant.objects.filter(session=session, guest_id=guest_id).first()
    if existing and existing.admission_state == Participant.AdmissionState.REMOVED:
        raise ClassroomError("This participant was removed from the classroom.")
    if existing and existing.admission_state == Participant.AdmissionState.REJECTED:
        raise ClassroomError("This participant was not admitted to the classroom.")
    requested_admission_state = (
        Participant.AdmissionState.PENDING
        if session.admission_mode == LiveSession.AdmissionMode.WAITING_ROOM
        else Participant.AdmissionState.ADMITTED
    )
    admission_state = (
        existing.admission_state
        if existing and existing.admission_state == Participant.AdmissionState.ADMITTED
        else requested_admission_state
    )
    participant, created = Participant.objects.update_or_create(
        session=session,
        guest_id=guest_id,
        defaults={
            "display_name": display_name.strip(),
            "role": Participant.Role.STUDENT,
            "admission_state": admission_state,
        },
    )
    if not created and participant.display_name == display_name and participant.admission_state == admission_state:
        return participant
    event_type = (
        "participant.requested"
        if admission_state == Participant.AdmissionState.PENDING
        else "participant.joined"
    )
    event_id = _append_event(session, event_type, payload={"participant_id": participant.id}, participant=participant)
    version = _advance_version(session)
    notify_session_after_commit(
        session.id,
        {
            "protocol": 1,
            "session_id": session.id,
            "version": version,
            "event_id": event_id,
            "type": event_type,
            "payload": {"participant_id": participant.id},
        },
    )
    return participant


@transaction.atomic
def join_authenticated(*, session: LiveSession, user, display_name: str | None = None) -> Participant:
    if not getattr(user, "is_authenticated", False):
        raise ClassroomError("A Django account is required.")
    if session.access_mode == LiveSession.AccessMode.GUEST:
        raise ClassroomError("This classroom accepts guest participants only.")
    if session.status not in {LiveSession.Status.WAITING, LiveSession.Status.LIVE, LiveSession.Status.PAUSED}:
        raise ClassroomError("This classroom is not accepting participants yet.")
    if session.admission_mode == LiveSession.AdmissionMode.ROSTER:
        if not session.course_id:
            raise ClassroomError("This classroom has no authenticated roster.")
        if not CourseMembership.objects.filter(course_id=session.course_id, user=user).exists():
            raise ClassroomError("You are not on this classroom's roster.")
    admitted = session.admission_mode != LiveSession.AdmissionMode.WAITING_ROOM
    if display_name is not None and not isinstance(display_name, str):
        raise ClassroomError("A display name must be text.")
    resolved_name = (display_name or getattr(user, "get_full_name", lambda: "")() or user.get_username()).strip()
    if not resolved_name:
        raise ClassroomError("A display name is required.")
    if len(resolved_name) > 100:
        raise ClassroomError("A display name is too long.")
    existing = Participant.objects.filter(session=session, user=user).first()
    if existing and existing.admission_state == Participant.AdmissionState.REMOVED:
        raise ClassroomError("This participant was removed from the classroom.")
    if existing and existing.admission_state == Participant.AdmissionState.REJECTED:
        raise ClassroomError("This participant was not admitted to the classroom.")
    participant, created = Participant.objects.update_or_create(
        session=session,
        user=user,
        defaults={
            "display_name": resolved_name,
            "role": Participant.Role.STUDENT,
            "admission_state": Participant.AdmissionState.ADMITTED if admitted else Participant.AdmissionState.PENDING,
        },
    )
    expected_state = Participant.AdmissionState.ADMITTED if admitted else Participant.AdmissionState.PENDING
    if not created and participant.admission_state == expected_state:
        return participant
    event_type = "participant.joined" if admitted else "participant.requested"
    event_id = _append_event(session, event_type, participant=participant)
    version = _advance_version(session)
    notify_session_after_commit(
        session.id,
        {
            "protocol": 1,
            "session_id": session.id,
            "version": version,
            "event_id": event_id,
            "type": event_type,
            "payload": {"participant_id": participant.id},
        },
    )
    return participant


@transaction.atomic
def set_participant_admission(
    *, participant: Participant, admitted: bool | None = None, state: str | None = None, actor
) -> Participant:
    """Admit, reject, or remove a participant without deleting their audit record."""
    session = participant.session
    if not can_manage_admission(actor, session):
        raise ClassroomError("You do not have permission to manage admission.")
    if state is None:
        state = Participant.AdmissionState.ADMITTED if admitted else Participant.AdmissionState.REJECTED
    if not isinstance(state, str) or state not in {
        Participant.AdmissionState.ADMITTED,
        Participant.AdmissionState.REJECTED,
        Participant.AdmissionState.REMOVED,
    }:
        raise ClassroomError("Unsupported admission state.")
    if participant.admission_state == state:
        return participant
    participant.admission_state = state
    if state == Participant.AdmissionState.ADMITTED:
        participant.removed_at = None
    elif state == Participant.AdmissionState.REMOVED:
        participant.removed_at = participant.removed_at or timezone.now()
    participant.save(update_fields=["admission_state", "removed_at"])
    event_type = f"participant.{state}"
    event_id = _append_event(session, event_type, actor, {"participant_id": participant.id}, participant=participant)
    version = _advance_version(session)
    notify_session_after_commit(
        session.id,
        {
            "protocol": 1,
            "session_id": session.id,
            "version": version,
            "event_id": event_id,
            "type": event_type,
            "payload": {"participant_id": participant.id},
        },
    )
    return participant


@transaction.atomic
def submit_answer(*, activity: LiveActivity, participant: Participant, answer: dict) -> Submission:
    if participant.session_id != activity.session_id:
        raise ClassroomError("You are not a participant in this classroom.")
    if participant.admission_state != Participant.AdmissionState.ADMITTED:
        raise ClassroomError("You are not admitted to this classroom.")
    if activity.session.status != LiveSession.Status.LIVE:
        raise ClassroomError("This classroom is not accepting answers right now.")
    if activity.state != LiveActivity.State.OPEN:
        raise ClassroomError("This activity is no longer accepting answers.")
    if not isinstance(answer, dict):
        raise ClassroomError("A submission must be an object.")
    try:
        type_key = (
            activity.current_revision.definition_snapshot.get("type_key")
            if activity.current_revision_id
            else None
        ) or f"liveclassroom.{activity.kind}"
        activity_type = activity_registry.get(type_key)
        answer = activity_type.normalize(answer)
    except (KeyError, ValueError) as exc:
        raise ClassroomError(str(exc)) from exc
    run_revision = _ensure_run_revision(activity)
    validation_definition = _activity_validation_definition(activity)
    try:
        answer = activity_type.validate_answer(answer, validation_definition)
        score_data = activity_type.score(answer, validation_definition)
    except (KeyError, TypeError, ValueError) as exc:
        raise ClassroomError(str(exc)) from exc
    submission = (
        Submission.objects.select_for_update()
        .filter(activity=activity, participant=participant, attempt=1)
        .first()
    )
    if submission is not None and submission.answer == answer and not submission.is_stale:
        raise ClassroomError("You have already submitted this answer.")
    if submission is None:
        try:
            submission = Submission.objects.create(activity=activity, participant=participant, answer=answer)
        except IntegrityError as exc:
            raise ClassroomError("The submission was updated concurrently; retry the request.") from exc
    revision_number = (submission.revisions.order_by("-revision").values_list("revision", flat=True).first() or 0) + 1
    submission_revision = SubmissionRevision.objects.create(
        submission=submission,
        revision=revision_number,
        activity_revision=run_revision,
        answer=answer,
        score=score_data.get("score"),
        is_correct=score_data.get("is_correct"),
        response_ms=submission.response_ms,
    )
    submission.answer = answer
    submission.current_revision = submission_revision
    submission.is_stale = False
    submission.score = score_data.get("score")
    submission.is_correct = score_data.get("is_correct")
    submission.save(update_fields=["answer", "current_revision", "is_stale", "score", "is_correct", "updated_at"])
    version = _advance_version(activity.session)
    event_id = _append_event(
        activity.session,
        "submission.received",
        payload={"activity_id": activity.id},
        participant=participant,
    )
    notify_session_after_commit(
        activity.session_id,
        {
            "protocol": 1,
            "session_id": activity.session_id,
            "version": version,
            "event_id": event_id,
            "type": "submission.progress",
            "payload": {"activity_id": activity.id},
        },
    )
    return submission


def result_summary(activity: LiveActivity, *, public: bool = False) -> dict[str, Any]:
    current = activity.submissions.filter(is_stale=False)
    answers = list(current.values_list("answer", flat=True))
    try:
        type_key = (
            activity.current_revision.definition_snapshot.get("type_key")
            if activity.current_revision_id
            else None
        ) or f"liveclassroom.{activity.kind}"
        activity_type = activity_registry.get(type_key)
        aggregate = (
            activity_type.aggregate_public(answers, definition=_activity_validation_definition(activity))
            if public
            else activity_type.aggregate(answers, definition=_activity_validation_definition(activity))
        )
    except (KeyError, ValueError):
        aggregate = {"submission_count": len(answers), "choices": {}}
    return {
        "activity_id": activity.id,
        "submission_count": current.count(),
        "stale_submission_count": activity.submissions.filter(is_stale=True).count(),
        **aggregate,
    }


def public_result_summary(activity: LiveActivity) -> dict[str, Any]:
    """Return the explicit audience-safe aggregate for one activity."""
    return result_summary(activity, public=True)


def redact_aggregate(aggregate: dict[str, Any]) -> dict[str, Any]:
    """Keep compatibility callers on the explicitly supported public fields.

    New state serialization uses ``public_result_summary`` so plugin-defined
    fields cannot accidentally cross an audience boundary.
    """
    public_keys = frozenset({
        "submission_count",
        "choices",
        "word_frequencies",
        "words",
        "numeric_summary",
        "ranking_positions",
    })
    return {key: value for key, value in aggregate.items() if key in public_keys}


@transaction.atomic
def post_message(
    *, session: LiveSession, body: str, actor=None, participant: Participant | None = None
) -> SessionMessage:
    """Create a named public chat message after checking session participation."""
    session = LiveSession.objects.select_for_update().get(pk=session.pk)
    if session.status == LiveSession.Status.ENDED:
        raise ClassroomError("This classroom has ended.")
    if not session.chat_enabled:
        raise ClassroomError("Chat is disabled for this classroom.")
    if not isinstance(body, str):
        raise ClassroomError("A chat message cannot be empty.")
    body = body.strip()
    if not body:
        raise ClassroomError("A chat message cannot be empty.")
    if len(body) > 4000:
        raise ClassroomError("A chat message is too long.")
    if participant is not None:
        if participant.session_id != session.id or participant.admission_state != Participant.AdmissionState.ADMITTED:
            raise ClassroomError("You are not admitted to this classroom.")
        display_name = participant.display_name
    elif getattr(actor, "is_authenticated", False) and can_manage_admission(actor, session):
        display_name = actor.get_username()
    else:
        raise ClassroomError("A participant or classroom staff account is required.")
    message = SessionMessage.objects.create(
        session=session,
        participant=participant,
        author=actor if getattr(actor, "is_authenticated", False) else None,
        display_name=display_name,
        body=body,
    )
    event_id = _append_event(session, "message.created", actor, {"message_id": message.id}, participant)
    version = _advance_version(session)
    notify_session_after_commit(
        session.id,
        {
            "protocol": 1,
            "session_id": session.id,
            "version": version,
            "event_id": event_id,
            "type": "message.created",
            "payload": {"message_id": message.id},
        },
    )
    return message


@transaction.atomic
def set_chat_enabled(*, session: LiveSession, enabled: bool, actor) -> LiveSession:
    """Enable or disable the named public chat without deleting its history."""
    if not can_manage_admission(actor, session):
        raise ClassroomError("You do not have permission to manage chat.")
    if not isinstance(enabled, bool):
        raise ClassroomError("enabled must be a boolean.")
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    if locked.status == LiveSession.Status.ENDED and enabled:
        raise ClassroomError("Chat cannot be enabled after the session has ended.")
    if locked.chat_enabled == enabled:
        session.chat_enabled = enabled
        session.state_version = locked.state_version
        return session
    locked.chat_enabled = enabled
    locked.save(update_fields=["chat_enabled", "updated_at"])
    version = _advance_version(locked)
    event_type = "chat.enabled" if enabled else "chat.disabled"
    event_id = _append_event(locked, event_type, actor, {"enabled": enabled})
    notify_session_after_commit(
        locked.id,
        {
            "protocol": 1,
            "session_id": locked.id,
            "version": version,
            "event_id": event_id,
            "type": event_type,
            "payload": {"enabled": enabled},
        },
    )
    session.chat_enabled = enabled
    session.state_version = version
    return session


@transaction.atomic
def mark_participant_connected(*, participant: Participant) -> Participant:
    """Record a participant connection without creating a chat or classroom event."""
    now = timezone.now()
    participant.connected_at = now
    participant.last_seen_at = now
    participant.disconnected_at = None
    participant.save(update_fields=["connected_at", "last_seen_at", "disconnected_at"])
    return participant


@transaction.atomic
def mark_participant_disconnected(*, participant: Participant) -> Participant:
    """Record a participant disconnect while retaining their durable identity."""
    now = timezone.now()
    participant.disconnected_at = now
    participant.last_seen_at = now
    participant.save(update_fields=["disconnected_at", "last_seen_at"])
    return participant
