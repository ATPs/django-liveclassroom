"""Streaming, versioned classroom exports."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Iterator
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q

from liveclassroom.models import LiveActivity, LiveSession, Submission
from liveclassroom.registry import activity_registry

from .classroom import result_summary
from .presentation import presentation_title


class _Echo:
    def write(self, value: str) -> str:
        return value


def _encode(value: Any) -> str:
    return json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _type_key(activity: LiveActivity, snapshot: dict | None = None) -> str:
    if snapshot is None:
        snapshot = (
            activity.current_revision.definition_snapshot
            if activity.current_revision_id
            else activity.definition_snapshot
        )
    key = snapshot.get("type_key") if isinstance(snapshot, dict) else None
    return key if isinstance(key, str) and key else f"liveclassroom.{activity.kind}"


def _answer(activity: LiveActivity, answer: dict, *, activity_revision=None) -> dict:
    snapshot = getattr(activity_revision, "definition_snapshot", None)
    try:
        return activity_registry.get(_type_key(activity, snapshot)).export(answer)
    except (KeyError, TypeError, ValueError):
        # A removed historical plugin must not prevent retained data export.
        return answer


def _participants(session: LiveSession):
    return session.participants.filter(is_test=False).order_by("joined_at", "id").values(
        "id", "display_name", "user_id", "admission_state", "joined_at", "last_seen_at", "connected_at",
        "disconnected_at", "removed_at",
    ).iterator(chunk_size=200)


def _activities(session: LiveSession):
    return session.activities.order_by("sequence", "id").select_related("current_revision").iterator(chunk_size=100)


def _activity_title(activity: LiveActivity) -> str:
    return presentation_title(activity.definition_snapshot.get("title", ""), "")


def _submissions(session: LiveSession):
    return Submission.objects.filter(activity__session=session, participant__is_test=False).select_related(
        "activity", "participant", "current_revision", "current_revision__activity_revision"
    ).order_by("activity__sequence", "participant_id", "id").iterator(chunk_size=200)


def _submission_row(submission: Submission) -> dict:
    return {
        "activity_id": submission.activity_id,
        "activity_sequence": submission.activity.sequence,
        "activity_revision": (
            submission.current_revision.activity_revision_id if submission.current_revision_id else None
        ),
        "submission_id": submission.id,
        "participant_id": submission.participant_id,
        "display_name": submission.participant.display_name,
        "performed_by_id": submission.performed_by_id,
        "answer": _answer(
            submission.activity,
            submission.answer,
            activity_revision=(
                submission.current_revision.activity_revision if submission.current_revision_id else None
            ),
        ),
        "is_stale": submission.is_stale,
        "is_correct": submission.is_correct,
        "score": submission.score,
        "submitted_at": submission.submitted_at,
        "revisions": [
            {
                "id": revision.id,
                "revision": revision.revision,
                "activity_revision_id": revision.activity_revision_id,
                "performed_by_id": revision.performed_by_id,
                "answer": _answer(submission.activity, revision.answer, activity_revision=revision.activity_revision),
                "is_correct": revision.is_correct,
                "score": revision.score,
                "created_at": revision.created_at,
            }
            for revision in submission.revisions.order_by("revision", "id").iterator(chunk_size=100)
        ],
    }


def _array(rows: Iterable[Any]) -> Iterator[str]:
    yield "["
    first = True
    for row in rows:
        if not first:
            yield ","
        yield _encode(row)
        first = False
    yield "]"


def json_archive(session: LiveSession) -> Iterator[str]:
    """Yield the complete archive without accumulating session-size lists."""
    yield '{"protocol_version":1,"session":'
    yield _encode({
        "id": session.id, "title": session.title, "join_code": session.join_code, "status": session.status,
        "access_mode": session.access_mode, "admission_mode": session.admission_mode,
        "created_at": session.created_at, "started_at": session.started_at, "ended_at": session.ended_at,
    })
    yield ',"participants":'
    yield from _array(_participants(session))
    yield ',"activities":['
    first = True
    for activity in _activities(session):
        if not first:
            yield ","
        yield _encode({
            "id": activity.id,
            "sequence": activity.sequence,
            "title": _activity_title(activity),
            "kind": activity.kind,
            "state": activity.state,
            "reviewable": activity.reviewable, "definition_snapshot": activity.definition_snapshot,
            "revisions": [
                {"id": revision.id, "revision": revision.revision, "definition_snapshot": revision.definition_snapshot,
                 "created_at": revision.created_at}
                for revision in activity.revisions.order_by("revision", "id").iterator(chunk_size=100)
            ],
        })
        first = False
    yield "]"
    yield ',"responses":'
    yield from _array(_submission_row(submission) for submission in _submissions(session))
    yield ',"chat":'
    yield from _array(session.messages.filter(deleted_at__isnull=True).filter(
        Q(participant__isnull=True) | Q(participant__is_test=False)
    ).order_by("created_at", "id").values(
        "id", "author_id", "participant_id", "display_name", "body", "created_at"
    ).iterator(chunk_size=200))
    yield ',"events":'
    yield from _array(session.events.filter(
        Q(participant__isnull=True) | Q(participant__is_test=False)
    ).order_by("sequence", "id").values(
        "sequence", "event_type", "actor_id", "participant_id", "payload", "created_at"
    ).iterator(chunk_size=200))
    yield "}"


_FIELDS = {
    "summary": [
        "activity_id", "sequence", "title", "kind", "state", "submission_count", "stale_submission_count", "choices",
    ],
    "responses": ["activity_id", "activity_sequence", "activity_revision", "submission_id", "participant_id",
                  "display_name", "performed_by_id", "answer", "is_stale", "is_correct", "score", "submitted_at",
                  "revisions"],
    "participants": ["id", "display_name", "user_id", "admission_state", "joined_at", "last_seen_at",
                     "connected_at", "disconnected_at", "removed_at"],
    "chat": ["id", "author_id", "participant_id", "display_name", "body", "created_at"],
}


def _csv_rows(session: LiveSession, dataset: str) -> Iterable[dict]:
    if dataset == "summary":
        for activity in _activities(session):
            summary = result_summary(activity)
            yield {"activity_id": activity.id, "sequence": activity.sequence, "title": _activity_title(activity),
                   "kind": activity.kind,
                   "state": activity.state, "submission_count": summary.get("submission_count", 0),
                   "stale_submission_count": summary.get("stale_submission_count", 0),
                   "choices": _encode(summary.get("choices", {}))}
    elif dataset == "responses":
        for submission in _submissions(session):
            row = _submission_row(submission)
            yield {**row, "answer": _encode(row["answer"]), "revisions": _encode(row["revisions"])}
    elif dataset == "participants":
        yield from _participants(session)
    elif dataset == "chat":
        yield from session.messages.filter(deleted_at__isnull=True).filter(
            Q(participant__isnull=True) | Q(participant__is_test=False)
        ).order_by("created_at", "id").values(
            "id", "author_id", "participant_id", "display_name", "body", "created_at"
        ).iterator(chunk_size=200)
    else:
        raise ValueError("Unsupported CSV dataset.")


def csv_export(session: LiveSession, dataset: str) -> Iterator[str]:
    """Yield a fixed-schema CSV, including an empty dataset header."""
    if dataset not in _FIELDS:
        raise ValueError("Unsupported CSV dataset.")
    writer = csv.DictWriter(_Echo(), fieldnames=_FIELDS[dataset], extrasaction="ignore")
    yield writer.writeheader()
    yield from (writer.writerow(row) for row in _csv_rows(session, dataset))
