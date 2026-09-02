"""Transactional commands for the teacher-paced classroom workflow."""

import secrets
from collections import Counter
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from liveclassroom.models import (
    CourseMembership,
    FlowItem,
    LiveActivity,
    LiveSession,
    Participant,
    SessionEvent,
    Submission,
)

from .events import notify_session_after_commit


class ClassroomError(Exception):
    """A command error that is safe to return from the JSON API."""


def can_manage_session(user, session: LiveSession) -> bool:
    if not user.is_authenticated:
        return False
    if user.pk == session.teacher_id or user.is_superuser:
        return True
    return CourseMembership.objects.filter(
        course=session.course,
        user=user,
        role__in=[CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT],
    ).exists()


def _append_event(session: LiveSession, event_type: str, actor=None, payload: dict | None = None) -> int:
    sequence = (session.events.order_by("-sequence").values_list("sequence", flat=True).first() or 0) + 1
    SessionEvent.objects.create(
        session=session,
        sequence=sequence,
        event_type=event_type,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        payload=payload or {},
    )
    return sequence


def _advance_version(session: LiveSession) -> int:
    session.state_version += 1
    session.save(update_fields=["state_version", "updated_at"])
    return session.state_version


def activity_snapshot(item: FlowItem) -> dict[str, Any]:
    """Capture all display and grading details so source content may change later."""
    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "kind": item.kind,
        "title": item.title,
        "content": item.content,
    }
    if item.question_id:
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


@transaction.atomic
def start_session(*, session: LiveSession, actor) -> LiveSession:
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to start this session.")
    if session.status == LiveSession.Status.ENDED:
        raise ClassroomError("An ended session cannot be restarted.")
    if session.status != LiveSession.Status.LIVE:
        session.status = LiveSession.Status.LIVE
        session.started_at = session.started_at or timezone.now()
        session.save(update_fields=["status", "started_at", "updated_at"])
        version = _advance_version(session)
        _append_event(session, "session.started", actor)
        notify_session_after_commit(
            session.id,
            {"protocol": 1, "session_id": session.id, "version": version, "type": "session.started", "payload": {}},
        )
    return session


@transaction.atomic
def launch_item(*, session: LiveSession, item: FlowItem, actor) -> LiveActivity:
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to control this session.")
    if session.status != LiveSession.Status.LIVE:
        raise ClassroomError("Start the session before publishing an item.")
    if item.flow_id != session.flow_id:
        raise ClassroomError("The selected item does not belong to this session's flow.")

    sequence = (session.activities.order_by("-sequence").values_list("sequence", flat=True).first() or 0) + 1
    activity = LiveActivity.objects.create(
        session=session,
        sequence=sequence,
        kind=item.kind,
        source_item=item,
        definition_snapshot=activity_snapshot(item),
    )
    session.current_item = item
    session.save(update_fields=["current_item", "updated_at"])
    version = _advance_version(session)
    _append_event(session, "activity.opened", actor, {"activity_id": activity.id})
    notify_session_after_commit(
        session.id,
        {
            "protocol": 1,
            "session_id": session.id,
            "version": version,
            "type": "activity.opened",
            "payload": {"activity_id": activity.id},
        },
    )
    return activity


@transaction.atomic
def set_activity_state(*, activity: LiveActivity, state: str, actor) -> LiveActivity:
    if not can_manage_session(actor, activity.session):
        raise ClassroomError("You do not have permission to control this session.")
    if state not in {LiveActivity.State.CLOSED, LiveActivity.State.REVEALED}:
        raise ClassroomError("Unsupported activity state.")
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
    _append_event(activity.session, event_type, actor, {"activity_id": activity.id})
    notify_session_after_commit(
        activity.session_id,
        {
            "protocol": 1,
            "session_id": activity.session_id,
            "version": version,
            "type": event_type,
            "payload": {"activity_id": activity.id},
        },
    )
    return activity


@transaction.atomic
def join_guest(*, session: LiveSession, display_name: str, guest_id: str | None = None) -> Participant:
    if session.status not in {LiveSession.Status.WAITING, LiveSession.Status.LIVE, LiveSession.Status.PAUSED}:
        raise ClassroomError("This classroom is not accepting participants yet.")
    guest_id = guest_id or secrets.token_urlsafe(24)
    participant, _ = Participant.objects.update_or_create(
        session=session,
        guest_id=guest_id,
        defaults={"display_name": display_name.strip(), "role": Participant.Role.STUDENT},
    )
    _append_event(session, "participant.joined", payload={"participant_id": participant.id})
    version = _advance_version(session)
    notify_session_after_commit(
        session.id,
        {
            "protocol": 1,
            "session_id": session.id,
            "version": version,
            "type": "participant.joined",
            "payload": {"participant_id": participant.id},
        },
    )
    return participant


@transaction.atomic
def submit_answer(*, activity: LiveActivity, participant: Participant, answer: dict) -> Submission:
    if participant.session_id != activity.session_id:
        raise ClassroomError("You are not a participant in this classroom.")
    if activity.state != LiveActivity.State.OPEN:
        raise ClassroomError("This activity is no longer accepting answers.")
    try:
        submission = Submission.objects.create(activity=activity, participant=participant, answer=answer)
    except IntegrityError as exc:
        raise ClassroomError("You have already submitted an answer.") from exc
    version = _advance_version(activity.session)
    _append_event(activity.session, "submission.received", payload={"activity_id": activity.id})
    notify_session_after_commit(
        activity.session_id,
        {
            "protocol": 1,
            "session_id": activity.session_id,
            "version": version,
            "type": "submission.progress",
            "payload": {"activity_id": activity.id},
        },
    )
    return submission


def result_summary(activity: LiveActivity) -> dict[str, Any]:
    answers = activity.submissions.values_list("answer", flat=True)
    counts = Counter(answer.get("choice") for answer in answers if answer.get("choice"))
    return {"activity_id": activity.id, "submission_count": activity.submissions.count(), "choices": dict(counts)}
