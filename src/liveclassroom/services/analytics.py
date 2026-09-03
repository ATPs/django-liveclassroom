"""Read-only staff analytics for a live classroom session."""

from collections import Counter
from typing import Any

from django.db.models import Prefetch

from liveclassroom.models import LiveSession, Participant, Submission

from .classroom import result_summary


def _revision_payload(revision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "revision": revision.revision,
        "activity_revision_id": revision.activity_revision_id,
        "answer": revision.answer,
        "is_correct": revision.is_correct,
        "score": revision.score,
        "created_at": revision.created_at,
    }


def _submission_payload(submission: Submission) -> dict[str, Any]:
    current_revision = submission.current_revision
    return {
        "id": submission.id,
        "participant_id": submission.participant_id,
        "display_name": submission.participant.display_name,
        "answer": submission.answer,
        "is_stale": submission.is_stale,
        "is_correct": submission.is_correct,
        "score": submission.score,
        "submitted_at": submission.submitted_at,
        "updated_at": submission.updated_at,
        "revision": current_revision.revision if current_revision else None,
        "activity_revision_id": current_revision.activity_revision_id if current_revision else None,
        "revisions": [_revision_payload(revision) for revision in submission.revisions.all()],
    }


def session_analytics(session: LiveSession) -> dict[str, Any]:
    """Build a bounded, named analytics snapshot for teaching staff.

    This intentionally includes answers because the caller is already guarded
    by the staff-only API endpoint. Student state remains served by ``state``
    and never calls this function.
    """
    participants = list(session.participants.order_by("joined_at", "id"))
    participant_by_id = {participant.id: participant for participant in participants}
    status_counts = Counter(participant.admission_state for participant in participants)
    eligible_count = status_counts[Participant.AdmissionState.ADMITTED]
    chat_messages = list(
        session.messages.filter(deleted_at__isnull=True)
        .order_by("created_at", "id")
        .values("id", "display_name", "body", "created_at")
    )

    submission_queryset = (
        Submission.objects.select_related(
            "participant",
            "current_revision",
            "current_revision__activity_revision",
        )
        .prefetch_related("revisions")
        .order_by("participant_id", "id")
    )
    activities = list(
        session.activities.order_by("sequence").select_related("current_revision").prefetch_related(
            Prefetch("submissions", queryset=submission_queryset)
        )
    )

    participant_timelines: dict[int, list[dict[str, Any]]] = {participant.id: [] for participant in participants}
    activity_rows = []
    for activity in activities:
        submissions = list(activity.submissions.all())
        current_submissions = [submission for submission in submissions if not submission.is_stale]
        summary = result_summary(activity)
        response_rows = []
        for submission in submissions:
            response = _submission_payload(submission)
            response_rows.append(response)
            if submission.participant_id in participant_by_id:
                participant_timelines[submission.participant_id].append(
                    {
                        "activity_id": activity.id,
                        "activity_sequence": activity.sequence,
                        "activity_title": activity.definition_snapshot.get("title", ""),
                        "submission_id": submission.id,
                        "is_stale": submission.is_stale,
                        "submitted_at": submission.submitted_at,
                        "updated_at": submission.updated_at,
                        "revision": response["revision"],
                        "activity_revision_id": response["activity_revision_id"],
                        "revision_count": len(response["revisions"]),
                    }
                )
        response_rate = round((len(current_submissions) / eligible_count) * 100, 2) if eligible_count else 0
        activity_rows.append(
            {
                "id": activity.id,
                "sequence": activity.sequence,
                "kind": activity.kind,
                "title": activity.definition_snapshot.get("title", ""),
                "state": activity.state,
                "revision": activity.current_revision.revision if activity.current_revision else 1,
                "eligible_participant_count": eligible_count,
                "submitted_count": len(current_submissions),
                "stale_submission_count": len(submissions) - len(current_submissions),
                "unanswered_count": max(eligible_count - len(current_submissions), 0),
                "response_rate": response_rate,
                "aggregate": summary,
                "responses": response_rows,
            }
        )

    participant_rows = []
    for participant in participants:
        timeline = participant_timelines[participant.id]
        participant_rows.append(
            {
                "id": participant.id,
                "display_name": participant.display_name,
                "user_id": participant.user_id,
                "admission_state": participant.admission_state,
                "joined_at": participant.joined_at,
                "connected_at": participant.connected_at,
                "disconnected_at": participant.disconnected_at,
                "last_seen_at": participant.last_seen_at,
                "current_response_count": sum(1 for item in timeline if not item["is_stale"]),
                "stale_response_count": sum(1 for item in timeline if item["is_stale"]),
                "timeline": timeline,
            }
        )

    return {
        "protocol_version": 1,
        "session_id": session.id,
        "state_version": session.state_version,
        "attendance": {
            "total": len(participants),
            "eligible": eligible_count,
            "admitted": status_counts[Participant.AdmissionState.ADMITTED],
            "pending": status_counts[Participant.AdmissionState.PENDING],
            "rejected": status_counts[Participant.AdmissionState.REJECTED],
            "removed": status_counts[Participant.AdmissionState.REMOVED],
            "ever_connected": sum(1 for participant in participants if participant.connected_at is not None),
            "currently_connected": sum(
                1
                for participant in participants
                if participant.connected_at is not None and participant.disconnected_at is None
            ),
        },
        "activities": activity_rows,
        "participants": participant_rows,
        "chat": {
            "enabled": session.chat_enabled,
            "message_count": len(chat_messages),
            "messages": chat_messages,
        },
    }
