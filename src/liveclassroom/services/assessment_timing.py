"""Server-authoritative assessment timing and bounded expiry.

Assessment timing is stored in the immutable run manifest as normalized JSON
values.  This module owns parsing and comparison so authoring, attempt start,
answer saves and the recovery command use the same rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from django.utils import timezone

from liveclassroom.models import AssessmentAttempt

from .classroom import ClassroomError

TIMING_FIELDS = frozenset({"due_at", "opens_at", "closes_at", "duration_seconds"})
HARD_CUTOFF_FIELDS = frozenset({"opens_at", "closes_at", "duration_seconds"})


def _aware_datetime(value: Any, field: str, *, allow_none: bool = True) -> datetime | None:
    if value is None and allow_none:
        return None
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ClassroomError(f"{field} must be an ISO-8601 datetime with a timezone.") from exc
    else:
        raise ClassroomError(f"{field} must be an ISO-8601 datetime with a timezone.")
    if timezone.is_naive(result):
        raise ClassroomError(f"{field} must include a timezone.")
    return result.astimezone(UTC)


def _canonical_datetime(value: Any, field: str) -> str | None:
    result = _aware_datetime(value, field)
    return result.isoformat() if result is not None else None


def normalize_timing_settings(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with timing values validated and datetime values frozen.

    ``None`` means that an optional constraint is absent.  It is retained when
    explicitly supplied so an author can clear an existing setting.
    """
    if not isinstance(value, Mapping):
        raise ClassroomError("settings must be an object.")
    result = dict(value)
    for field in ("due_at", "opens_at", "closes_at"):
        if field in value:
            result[field] = _canonical_datetime(value[field], field)
    if "duration_seconds" in value:
        duration = value["duration_seconds"]
        if duration is not None and (
            isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0
        ):
            raise ClassroomError("duration_seconds must be a positive integer.")
        result["duration_seconds"] = duration

    opens_at = _aware_datetime(result.get("opens_at"), "opens_at")
    closes_at = _aware_datetime(result.get("closes_at"), "closes_at")
    if opens_at is not None and closes_at is not None and opens_at >= closes_at:
        raise ClassroomError("opens_at must be earlier than closes_at.")
    return result


def _settings(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return value


def assessment_deadline(*, started_at: datetime, settings: Mapping[str, Any] | None) -> datetime | None:
    """Derive an attempt's frozen hard deadline from its run settings."""
    if timezone.is_naive(started_at):
        started_at = timezone.make_aware(started_at, timezone.get_current_timezone())
    values = _settings(settings)
    candidates: list[datetime] = []
    duration = values.get("duration_seconds")
    if duration is not None:
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise ClassroomError("duration_seconds must be a positive integer.")
        candidates.append(started_at + timedelta(seconds=duration))
    closes_at = _aware_datetime(values.get("closes_at"), "closes_at")
    if closes_at is not None:
        candidates.append(closes_at)
    return min(candidates) if candidates else None


def server_now(value: datetime | None = None) -> datetime:
    """Normalize an internal/test clock; clients never supply this value."""
    current = timezone.now() if value is None else value
    if timezone.is_naive(current):
        return timezone.make_aware(current, timezone.get_current_timezone())
    return current


def ensure_assessment_can_start(*, now: datetime, settings: Mapping[str, Any] | None) -> None:
    """Enforce the inclusive opening and exclusive closing boundaries."""
    values = _settings(settings)
    current = server_now(now)
    opens_at = _aware_datetime(values.get("opens_at"), "opens_at")
    closes_at = _aware_datetime(values.get("closes_at"), "closes_at")
    if opens_at is not None and current < opens_at:
        raise ClassroomError("This assessment is not open yet.")
    if closes_at is not None and current >= closes_at:
        raise ClassroomError("This assessment is closed.")


def is_due(*, attempt: AssessmentAttempt, now: datetime | None = None) -> bool:
    current = server_now(now)
    return (
        attempt.status == AssessmentAttempt.Status.IN_PROGRESS
        and attempt.deadline_at is not None
        and current >= attempt.deadline_at
    )


def finalize_due_attempt(*, attempt: AssessmentAttempt, now: datetime | None = None):
    """Finalize one due attempt through the task-26 idempotent service.

    Returns the terminal result when due, or ``None`` when the attempt remains
    open.  The import is intentionally local because task 26 imports attempt
    access helpers from the sibling attempts module.
    """
    current = server_now(now)
    if not is_due(attempt=attempt, now=current):
        return None
    from .attempt_submission import AttemptSubmissionConflict, submit_attempt

    try:
        return submit_attempt(
            actor=None,
            attempt=attempt,
            request_id=uuid4(),
            now=current,
            reason="expired",
        )
    except AttemptSubmissionConflict as exc:
        if exc.code == "attempt_open":
            return None
        raise


def expire_due_attempts(*, now: datetime | None = None, limit: int = 500) -> dict[str, int]:
    """Finalize a bounded batch of due attempts and return operational counts."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ClassroomError("limit must be a positive integer.")
    current = server_now(now)
    ids = list(
        AssessmentAttempt.objects.filter(
            status=AssessmentAttempt.Status.IN_PROGRESS,
            deadline_at__isnull=False,
            deadline_at__lte=current,
        )
        .order_by("deadline_at", "id")
        .values_list("pk", flat=True)[:limit]
    )
    counts = {"scanned": len(ids), "expired": 0, "already_finalized": 0, "failed": 0}
    from .attempt_submission import AttemptSubmissionConflict, submit_attempt

    for attempt_id in ids:
        try:
            result = submit_attempt(
                actor=None,
                attempt=AssessmentAttempt(pk=attempt_id),
                request_id=uuid4(),
                now=current,
                reason="expired",
            )
        except AttemptSubmissionConflict as exc:
            # A concurrent writer can make a candidate non-due before this
            # worker acquires its lock.  It is a harmless skipped candidate;
            # other failures remain visible to the command/operator.
            if exc.code == "attempt_open":
                counts["already_finalized"] += 1
            else:
                counts["failed"] += 1
            continue
        except Exception:
            counts["failed"] += 1
            continue
        if getattr(result, "finalized_now", False):
            counts["expired"] += 1
        else:
            counts["already_finalized"] += 1
    return counts


__all__ = [
    "HARD_CUTOFF_FIELDS",
    "TIMING_FIELDS",
    "assessment_deadline",
    "ensure_assessment_can_start",
    "expire_due_attempts",
    "finalize_due_attempt",
    "is_due",
    "normalize_timing_settings",
    "server_now",
]
