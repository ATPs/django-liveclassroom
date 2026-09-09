"""Transactional finalization of authenticated assessment attempts.

Answer saves and final submission deliberately use the same lock order: the
attempt row is locked first and its item rows are locked second.  This makes
the last acknowledged save deterministic when a student submits from two
tabs.  ``AnswerRevision`` rows are already immutable; changing the attempt to
``submitted`` closes the only write path that can create another revision.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone

from liveclassroom.models import AnswerRevision, AssessmentAttempt, AssessmentAttemptItem

from .attempts import _can_access, _item_uuid, _request_uuid
from .classroom import ClassroomError


class AttemptSubmissionConflict(ClassroomError):
    """A submission cannot be accepted without changing the attempt."""

    status_code = 409

    def __init__(self, message: str, *, code: str = "stale_revision", current_versions=None):
        super().__init__(message)
        self.code = code
        self.current_versions = current_versions


# Public aliases keep the event easy to discover for host integrations and
# later grading code without requiring a job queue or a host-specific import.
attempt_submitted = Signal()
attempt_finalized = attempt_submitted


class AttemptSubmissionResult(dict):
    """Stable, JSON-compatible finalization result with the model attached.

    Services in this package commonly return model instances, while API
    boundaries return dictionaries.  The mapping supports both callers and
    keeps the durable response independent of the request ID used to retry.
    """

    def __init__(self, payload: dict[str, Any], attempt: AssessmentAttempt):
        super().__init__(payload)
        self.attempt = attempt
        self.finalized_now = False


def _aware_now(value: datetime | None) -> datetime:
    current = timezone.now() if value is None else value
    if timezone.is_naive(current):
        return timezone.make_aware(current, timezone.get_current_timezone())
    return current


def _expected_versions(value) -> dict[UUID, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ClassroomError("expected_versions must be an object.")
    result: dict[UUID, int] = {}
    for raw_key, raw_version in value.items():
        try:
            key = _item_uuid(raw_key)
        except ClassroomError as exc:
            raise ClassroomError("expected_versions contains an invalid item key.") from exc
        if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 0:
            raise ClassroomError("expected_versions values must be nonnegative integers.")
        result[key] = raw_version
    return result


def _latest(item: AssessmentAttemptItem) -> AnswerRevision | None:
    cached = getattr(item, "_prefetched_objects_cache", {}).get("answer_revisions")
    if cached is not None:
        return cached[0] if cached else None
    return item.answer_revisions.order_by("-version").first()


def _versions(items: list[AssessmentAttemptItem]) -> dict[str, int]:
    result = {}
    for item in items:
        revision = _latest(item)
        result[str(item.key)] = revision.version if revision is not None else 0
    return result


def _submission_payload(attempt: AssessmentAttempt, items: list[AssessmentAttemptItem]) -> dict[str, Any]:
    """Serialize only the student's own retained answers and final state."""
    item_payloads = []
    for item in items:
        revision = _latest(item)
        item_payloads.append(
            {
                "item_key": str(item.key),
                "version": revision.version if revision is not None else 0,
                "answer": deepcopy(revision.answer) if revision is not None else None,
            }
        )
    return {
        "id": str(attempt.public_id),
        "run_id": str(attempt.run.public_id),
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "started_at": attempt.started_at.isoformat(),
        "deadline_at": attempt.deadline_at.isoformat() if attempt.deadline_at else None,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "finalization_reason": attempt.finalization_reason or None,
        "items": item_payloads,
    }


def _send_submitted(attempt_id: int, actor_id: int | None, reason: str, payload: dict[str, Any]) -> None:
    """Send the extension event after commit; receivers cannot affect writes."""
    attempt_submitted.send(
        sender=AssessmentAttempt,
        attempt_id=attempt_id,
        actor_id=actor_id,
        reason=reason,
        result=payload,
    )


@transaction.atomic
def submit_attempt(
    *,
    actor,
    attempt: AssessmentAttempt,
    request_id,
    expected_versions=None,
    now: datetime | None = None,
    reason: str = "student",
) -> AttemptSubmissionResult:
    """Finalize one attempt exactly once and return its stable own-result.

    ``request_id`` is required for retry tracing and is intentionally not used
    as a second mutable state machine: once the status is submitted every
    request returns the durable final result.  This is safe across process
    restarts and avoids a separate receipt table for a transition that has one
    immutable terminal state.
    """
    request_uuid = _request_uuid(request_id)
    del request_uuid  # Validation is the contract; status is the idempotent receipt.
    expected = _expected_versions(expected_versions)
    if reason not in {"student", "expired"}:
        raise ClassroomError("reason must be student or expired.")
    current_now = _aware_now(now)

    locked = (
        AssessmentAttempt.objects.select_for_update()
        .select_related("run")
        .get(pk=attempt.pk)
    )
    is_expiry = reason == "expired"
    if not is_expiry:
        if not getattr(actor, "is_authenticated", False):
            raise ClassroomError("Authentication required.")
        if locked.user_id != actor.pk:
            raise ClassroomError("You do not have permission to submit this attempt.")
        if not _can_access(actor, locked.run):
            raise ClassroomError("You do not have access to this assessment.")
    elif actor is not None and getattr(actor, "is_authenticated", False) and locked.user_id != actor.pk:
        # A future delegated/system expiry caller may pass no actor.  A normal
        # authenticated actor still cannot impersonate this student's expiry.
        raise ClassroomError("You do not have permission to expire this attempt.")

    # Lock all items after the attempt, matching save_attempt_answer.  The
    # explicit order also keeps PostgreSQL lock acquisition deterministic.
    items = list(
        AssessmentAttemptItem.objects.select_for_update()
        .filter(attempt=locked)
        .order_by("position", "id")
    )

    if locked.status == AssessmentAttempt.Status.SUBMITTED:
        # A repeated submit is a read of the immutable terminal state.  Ignore
        # an old expected-version map because no answer can change now.
        return AttemptSubmissionResult(_submission_payload(locked, items), locked)

    if is_expiry:
        if locked.deadline_at is None or current_now < locked.deadline_at:
            raise AttemptSubmissionConflict("This attempt is not due for expiry.", code="attempt_open")
    elif locked.deadline_at is not None and current_now >= locked.deadline_at:
        raise AttemptSubmissionConflict("The answer deadline has passed.", code="attempt_closed")

    current = _versions(items)
    if expected is not None:
        normalized_expected = {str(key): value for key, value in expected.items()}
        if normalized_expected != current:
            raise AttemptSubmissionConflict(
                "Answers changed; save the current answers before submitting.",
                code="stale_revision",
                current_versions=current,
            )

    # Expiry uses the effective deadline as the student's recorded submission
    # time.  Manual submission records the authoritative server time.
    effective_now = locked.deadline_at if is_expiry and locked.deadline_at is not None else current_now
    locked.status = AssessmentAttempt.Status.SUBMITTED
    locked.submitted_at = effective_now
    locked.finalization_reason = reason
    locked.save(update_fields=["status", "submitted_at", "finalization_reason"])

    payload = _submission_payload(locked, items)
    transaction.on_commit(
        lambda: _send_submitted(locked.pk, getattr(actor, "pk", None), reason, payload),
        robust=True,
    )
    result = AttemptSubmissionResult(payload, locked)
    result.finalized_now = True
    return result


__all__ = [
    "AttemptSubmissionConflict",
    "AttemptSubmissionResult",
    "attempt_finalized",
    "attempt_submitted",
    "submit_attempt",
]
