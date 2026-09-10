"""Read-only authenticated assessment history and retained attempt review."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from django.db.models import Prefetch

from liveclassroom.models import AnswerRevision, AssessmentAttempt, AssessmentAttemptItem

from .attempts import _can_access
from .classroom import ClassroomError
from .result_release import student_result_payload

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class AssessmentReviewError(ClassroomError):
    """The requested history or retained attempt is unavailable."""


def _limit(value) -> int:
    if value in (None, ""):
        return DEFAULT_LIMIT
    if isinstance(value, bool):
        raise AssessmentReviewError("limit must be an integer between 1 and 100.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AssessmentReviewError("limit must be an integer between 1 and 100.") from exc
    if not 1 <= parsed <= MAX_LIMIT:
        raise AssessmentReviewError("limit must be an integer between 1 and 100.")
    return parsed


def _offset(value) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        raise AssessmentReviewError("offset must be a nonnegative integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AssessmentReviewError("offset must be a nonnegative integer.") from exc
    if parsed < 0:
        raise AssessmentReviewError("offset must be a nonnegative integer.")
    return parsed


def _iso(value):
    return value.isoformat() if value is not None else None


def _history_row(attempt: AssessmentAttempt) -> dict:
    return {
        "id": str(attempt.public_id),
        "run_id": str(attempt.run.public_id),
        "run_title": attempt.run.title,
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "started_at": _iso(attempt.started_at),
        "submitted_at": _iso(attempt.submitted_at),
        "deadline_at": _iso(attempt.deadline_at),
        "can_resume": attempt.status == AssessmentAttempt.Status.IN_PROGRESS,
    }


def list_own_attempt_history(*, actor, limit=None, offset=None) -> dict:
    """Return one account's stable newest-first attempt history without writes."""
    if not getattr(actor, "is_authenticated", False):
        raise AssessmentReviewError("Authentication required.")
    page_size = _limit(limit)
    page_offset = _offset(offset)
    queryset = (
        AssessmentAttempt.objects.filter(user=actor)
        .select_related("run")
        .order_by("-started_at", "-id")
    )
    visible = [attempt for attempt in queryset if _can_access(actor, attempt.run)]
    rows = visible[page_offset : page_offset + page_size]
    return {
        "items": [_history_row(attempt) for attempt in rows],
        "limit": page_size,
        "offset": page_offset,
        "total": len(visible),
        "next_offset": page_offset + page_size if page_offset + page_size < len(visible) else None,
    }


def _latest_answer(item: AssessmentAttemptItem):
    cached = getattr(item, "_prefetched_objects_cache", {}).get("answer_revisions")
    if cached is not None:
        return cached[0] if cached else None
    return item.answer_revisions.order_by("-version").first()


def _safe_retained_content(item: AssessmentAttemptItem) -> dict:
    manifest = item.manifest if isinstance(item.manifest, dict) else {}
    payload = manifest.get("payload", manifest.get("definition", {}))
    if not isinstance(payload, dict):
        payload = {}
    content: dict = {}
    for key in ("prompt", "stem", "stem_markdown", "question", "markdown", "options"):
        if key in payload:
            content[key] = deepcopy(payload[key])
    return content


def review_own_attempt(*, actor, public_id, now=None) -> dict:
    """Return immutable delivered content, own answer, and policy-filtered result."""
    if not getattr(actor, "is_authenticated", False):
        raise AssessmentReviewError("Authentication required.")
    try:
        attempt = (
            AssessmentAttempt.objects.select_related("run")
            .prefetch_related(
                "items",
                Prefetch("items__answer_revisions", queryset=AnswerRevision.objects.order_by("-version")),
                "items__grade",
                "grade",
            )
            .get(public_id=public_id, user=actor)
        )
    except AssessmentAttempt.DoesNotExist as exc:
        raise AssessmentReviewError("Attempt not found.") from exc
    if not _can_access(actor, attempt.run):
        raise AssessmentReviewError("Attempt not found.")
    result = student_result_payload(attempt=attempt, now=now)
    by_key = {row["key"]: row for row in result["items"]}
    items = []
    for item in attempt.items.all():
        answer = _latest_answer(item)
        row = by_key.get(str(item.key), {})
        items.append(
            {
                "key": str(item.key),
                "position": item.position,
                "points": format(Decimal(str(item.points)).normalize(), "f"),
                "type_key": (item.manifest or {}).get("type_key") if isinstance(item.manifest, dict) else None,
                "content": _safe_retained_content(item),
                "saved_answer": deepcopy(answer.answer) if answer is not None else None,
                "answer_version": answer.version if answer is not None else 0,
                "released": {
                    key: value
                    for key, value in result["released"].items()
                },
                "result": row,
            }
        )
    return {
        "id": str(attempt.public_id),
        "run_id": str(attempt.run.public_id),
        "run_title": attempt.run.title,
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "started_at": _iso(attempt.started_at),
        "submitted_at": _iso(attempt.submitted_at),
        "released": result["released"],
        "score": result.get("score"),
        "items": items,
    }


__all__ = [
    "AssessmentReviewError",
    "list_own_attempt_history",
    "review_own_attempt",
]
