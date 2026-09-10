"""Start and resume independent attempts from immutable run manifests."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.utils import timezone

from liveclassroom.models import (
    AnswerRevision,
    AssessmentAttempt,
    AssessmentAttemptItem,
    AssessmentRun,
    AttemptAnswerReceipt,
    AttemptStartReceipt,
    CourseMembership,
)

from .assessment_timing import assessment_deadline, ensure_assessment_can_start, server_now
from .classroom import ClassroomError


class AttemptAnswerConflict(ClassroomError):
    """A retry or optimistic version check cannot write a new answer."""

    status_code = 409

    def __init__(self, message: str, *, code: str = "stale_revision", current=None):
        super().__init__(message)
        self.code = code
        self.current = current


def _request_uuid(value) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ClassroomError("request_id must be a UUID.") from exc


def _item_uuid(value) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ClassroomError("item_key must be a UUID.") from exc


def _expected_version(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ClassroomError("expected_version must be a nonnegative integer.")
    return value


def _answer_request_hash(*, item_key: UUID, expected_version: int, answer) -> str:
    try:
        encoded = json.dumps(
            {"item_key": str(item_key), "expected_version": expected_version, "answer": answer},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ClassroomError("answer must contain only JSON values.") from exc
    return hashlib.sha256(encoded).hexdigest()


def _latest_answer(item: AssessmentAttemptItem) -> AnswerRevision | None:
    """Return the current answer, using the prefetch cache when available."""
    cached = getattr(item, "_prefetched_objects_cache", {}).get("answer_revisions")
    if cached is not None:
        return cached[0] if cached else None
    return item.answer_revisions.order_by("-version").first()


def _current_answer_payload(item: AssessmentAttemptItem) -> dict:
    revision = _latest_answer(item)
    return {
        "item_key": str(item.key),
        "version": revision.version if revision is not None else 0,
        "answer": deepcopy(revision.answer) if revision is not None else None,
    }


def _hash_request(*, new_attempt: bool) -> str:
    return hashlib.sha256(json.dumps({"new_attempt": new_attempt}, sort_keys=True).encode()).hexdigest()


def _can_access(actor, run: AssessmentRun) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    if run.audience == AssessmentRun.Audience.AUTHENTICATED_LINK:
        return True
    return bool(
        run.course_id
        and CourseMembership.objects.filter(
            course_id=run.course_id, user=actor, role=CourseMembership.Role.STUDENT
        ).exists()
    )


def _limit(run: AssessmentRun) -> int | None:
    settings = run.manifest.get("settings", {}) if isinstance(run.manifest, dict) else {}
    value = settings.get("max_attempts", 1) if isinstance(settings, dict) else 1
    if value is None:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else 1


@transaction.atomic
def save_attempt_answer(
    *, actor, attempt: AssessmentAttempt, item_key, answer, expected_version, request_id, now=None
) -> AnswerRevision:
    """Append one validated answer revision and make the command replayable.

    The attempt is locked before its item, matching finalization's lock order.
    That makes two tabs serialize their version checks and prevents a slower
    request from replacing a newer answer.  A receipt is checked before the
    optimistic version so a lost response can always replay its original row.
    """
    if not getattr(actor, "is_authenticated", False):
        raise ClassroomError("Authentication required.")
    item_uuid = _item_uuid(item_key)
    expected = _expected_version(expected_version)
    request_uuid = _request_uuid(request_id)
    if not isinstance(answer, dict):
        raise ClassroomError("answer must be an object.")
    request_hash = _answer_request_hash(item_key=item_uuid, expected_version=expected, answer=answer)
    current_now = timezone.now() if now is None else now
    if timezone.is_naive(current_now):
        current_now = timezone.make_aware(current_now, timezone.get_current_timezone())

    locked_attempt = (
        AssessmentAttempt.objects.select_for_update().select_related("run").get(pk=attempt.pk)
    )
    if locked_attempt.user_id != actor.pk:
        raise ClassroomError("You do not have permission to save this answer.")
    receipt = (
        AttemptAnswerReceipt.objects.select_related("revision__item")
        .filter(attempt=locked_attempt, request_id=request_uuid)
        .first()
    )
    if receipt is not None:
        if receipt.request_hash != request_hash:
            raise AttemptAnswerConflict(
                "This request_id was already used with different input.", code="idempotency_conflict"
            )
        # A valid receipt always points at this attempt, but retain this check
        # as a defense against manually corrupted database rows.
        if receipt.revision.item.attempt_id != locked_attempt.pk:
            raise ClassroomError("The saved answer receipt is invalid.")
        return receipt.revision

    try:
        item = AssessmentAttemptItem.objects.select_for_update().get(
            attempt=locked_attempt, key=item_uuid
        )
    except AssessmentAttemptItem.DoesNotExist as exc:
        raise ClassroomError("The assessment item was not found.") from exc

    if locked_attempt.status != AssessmentAttempt.Status.IN_PROGRESS:
        raise AttemptAnswerConflict("This attempt is already finalized.", code="attempt_closed")
    if locked_attempt.deadline_at is not None and current_now >= locked_attempt.deadline_at:
        raise AttemptAnswerConflict("The answer deadline has passed.", code="attempt_closed")
    from .assessment_navigation import assert_item_writable

    assert_item_writable(attempt=locked_attempt, item=item)

    latest = _latest_answer(item)
    current_version = latest.version if latest is not None else 0
    if expected != current_version:
        raise AttemptAnswerConflict(
            "The answer changed; refresh before saving.",
            current=_current_answer_payload(item),
        )

    source = item.manifest if isinstance(item.manifest, dict) else {}
    type_key = source.get("type_key")
    if isinstance(type_key, str) and "." not in type_key:
        type_key = f"liveclassroom.{type_key}"
    if not isinstance(type_key, str) or not type_key:
        raise ClassroomError("The assessment item has no answer type.")
    try:
        from liveclassroom.registry import activity_registry

        activity_type = activity_registry.get(type_key)
        normalized = activity_type.normalize(deepcopy(answer))
        definition = source.get("payload", {})
        normalized = activity_type.validate_answer(normalized, definition)
    except (KeyError, TypeError, ValueError) as exc:
        raise ClassroomError(str(exc)) from exc

    revision = AnswerRevision.objects.create(
        item=item,
        version=current_version + 1,
        answer=deepcopy(normalized),
        request_id=request_uuid,
        request_hash=request_hash,
        actor=actor,
        saved_at=current_now,
    )
    AttemptAnswerReceipt.objects.create(
        attempt=locked_attempt,
        request_id=request_uuid,
        request_hash=request_hash,
        revision=revision,
    )
    return revision


@transaction.atomic
def start_or_resume_attempt(
    *, actor, run: AssessmentRun, request_id, new_attempt: bool = False, now=None
) -> tuple[AssessmentAttempt, bool]:
    """Return an active attempt, or create a deliberately requested next one."""
    if not isinstance(new_attempt, bool):
        raise ClassroomError("new_attempt must be a boolean.")
    request_id = _request_uuid(request_id)
    locked_run = AssessmentRun.objects.select_for_update().get(pk=run.pk)
    if not _can_access(actor, locked_run):
        raise ClassroomError("You do not have access to this assessment.")
    current_now = server_now(now)
    run_settings = locked_run.manifest.get("settings", {}) if isinstance(locked_run.manifest, dict) else {}
    request_hash = _hash_request(new_attempt=new_attempt)
    receipt = (
        AttemptStartReceipt.objects.filter(run=locked_run, user=actor, request_id=request_id)
        .select_related("attempt")
        .first()
    )
    if receipt is not None:
        if receipt.request_hash != request_hash:
            raise ClassroomError("This request_id was already used with different input.")
        if receipt.attempt is None:
            raise ClassroomError("The start request did not complete; retry with a new request_id.")
        return receipt.attempt, False
    ensure_assessment_can_start(now=current_now, settings=run_settings)
    active = (
        AssessmentAttempt.objects.select_for_update()
        .filter(run=locked_run, user=actor, status=AssessmentAttempt.Status.IN_PROGRESS)
        .first()
    )
    if active is not None:
        if active.deadline_at is not None and current_now >= active.deadline_at:
            # A delayed worker must not leave a resumed attempt writable.  Use
            # the same idempotent finalizer as the scheduled expiry command.
            from .assessment_timing import finalize_due_attempt

            if finalize_due_attempt(attempt=active, now=current_now) is not None:
                active.refresh_from_db()
        AttemptStartReceipt.objects.create(
            run=locked_run, user=actor, request_id=request_id, request_hash=request_hash, attempt=active
        )
        return active, False
    latest = (
        AssessmentAttempt.objects.select_for_update()
        .filter(run=locked_run, user=actor)
        .order_by("-attempt_number")
        .first()
    )
    if latest is not None and not new_attempt:
        AttemptStartReceipt.objects.create(
            run=locked_run, user=actor, request_id=request_id, request_hash=request_hash, attempt=latest
        )
        return latest, False
    number = (latest.attempt_number if latest is not None else 0) + 1
    maximum = _limit(locked_run)
    if maximum is not None and number > maximum:
        raise ClassroomError("No attempts remain for this assessment.")
    try:
        navigation_mode = run_settings.get("navigation", "free")
        if navigation_mode not in {"free", "forward_only"}:
            raise ClassroomError("The assessment navigation mode is invalid.")
        attempt = AssessmentAttempt.objects.create(
            run=locked_run,
            user=actor,
            attempt_number=number,
            navigation_mode=navigation_mode,
        )
    except IntegrityError as exc:
        # The database constraints are the concurrency backstop on SQLite and PostgreSQL.
        active = AssessmentAttempt.objects.filter(
            run=locked_run, user=actor, status=AssessmentAttempt.Status.IN_PROGRESS
        ).first()
        if active is not None:
            return active, False
        raise ClassroomError("The attempt changed concurrently; retry.") from exc
    attempt.deadline_at = assessment_deadline(started_at=attempt.started_at, settings=run_settings)
    if attempt.deadline_at is not None:
        attempt.save(update_fields=["deadline_at"])
    from .attempt_assignment import assign_attempt_items

    assign_attempt_items(run=locked_run, attempt=attempt)
    AttemptStartReceipt.objects.create(
        run=locked_run, user=actor, request_id=request_id, request_hash=request_hash, attempt=attempt
    )
    return attempt, True


def _public_manifest(item: AssessmentAttemptItem) -> dict:
    source = item.manifest if isinstance(item.manifest, dict) else {}
    payload = deepcopy(source.get("payload", {}))

    def redact(value):
        if isinstance(value, dict):
            return {
                key: redact(child)
                for key, child in value.items()
                if key not in {"answer", "correct_answer", "explanation", "explanation_markdown", "feedback"}
            }
        if isinstance(value, list):
            return [redact(child) for child in value]
        return value

    answer_revision = _latest_answer(item)
    return {
        "key": str(item.key),
        "position": item.position,
        "points": format(item.points.normalize(), "f"),
        "type_key": source.get("type_key"),
        "schema_version": source.get("schema_version"),
        "payload": redact(payload),
        "metadata": redact(deepcopy(source.get("metadata", {}))),
        "asset_id": source.get("asset_id"),
        "answer_version": answer_revision.version if answer_revision is not None else 0,
        "answer": deepcopy(answer_revision.answer) if answer_revision is not None else None,
    }


def attempt_payload(attempt: AssessmentAttempt) -> dict:
    current = timezone.now()
    remaining_seconds = None
    if attempt.deadline_at is not None:
        remaining_seconds = max(0, int((attempt.deadline_at - current).total_seconds()))
    from .assessment_navigation import navigation_payload

    return {
        "id": str(attempt.public_id),
        "run_id": str(attempt.run.public_id),
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "started_at": attempt.started_at.isoformat(),
        "deadline_at": attempt.deadline_at.isoformat() if attempt.deadline_at else None,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "finalization_reason": attempt.finalization_reason or None,
        "server_now": current.isoformat(),
        "remaining_seconds": remaining_seconds,
        "navigation": navigation_payload(attempt),
        "items": [_public_manifest(item) for item in attempt.items.all()],
    }


def own_attempt(actor, public_id) -> AssessmentAttempt:
    try:
        attempt = (
            AssessmentAttempt.objects.prefetch_related(
                "items",
                Prefetch("items__answer_revisions", queryset=AnswerRevision.objects.order_by("-version")),
            )
            .select_related("run")
            .get(public_id=public_id, user=actor)
        )
    except AssessmentAttempt.DoesNotExist as exc:
        raise ClassroomError("Attempt not found.") from exc
    if not _can_access(actor, attempt.run):
        raise ClassroomError("You do not have access to this assessment.")
    return attempt
