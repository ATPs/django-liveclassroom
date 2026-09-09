"""Automatic grading for immutable, submitted assessment attempts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from typing import Any

from django.db import transaction
from django.utils import timezone

from liveclassroom.models import (
    AssessmentAttempt,
    AssessmentAttemptGrade,
    AssessmentAttemptItem,
    AssessmentGradeDecision,
    AssessmentItemGrade,
)

from .attempt_submission import attempt_submitted
from .classroom import ClassroomError

POINT_QUANTUM = Decimal("0.01")
RULE_VERSION = "activity-registry-v1"
RETRYABLE_ERROR_CODES = frozenset(
    {"missing_grader", "missing_score", "invalid_retained_item", "grader_unavailable"}
)
_MISSING = object()


class AssessmentGradingError(ClassroomError):
    """A submitted attempt cannot be graded by the current configuration."""


def _decimal(value: Any, *, field: str, nonnegative: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (DecimalException, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a finite decimal.") from exc
    if not result.is_finite() or (nonnegative and result < 0):
        raise ValueError(f"{field} must be a finite nonnegative decimal.")
    return result


def _key(definition: dict[str, Any]):
    if "answer" in definition:
        value = definition["answer"]
    elif "correct_answer" in definition:
        value = definition["correct_answer"]
    else:
        return _MISSING
    if value is None or value == [] or (isinstance(value, str) and not value.strip()):
        return _MISSING
    return value


def _item_fields(item_payload: dict[str, Any]) -> tuple[str, dict[str, Any], Decimal]:
    if not isinstance(item_payload, dict):
        raise ValueError("The retained item must be an object.")
    type_key = item_payload.get("type_key")
    if not isinstance(type_key, str) or not type_key.strip():
        raise ValueError("The retained item has no type.")
    type_key = type_key.strip()
    if "." not in type_key:
        type_key = f"liveclassroom.{type_key}"
    definition = item_payload.get("definition", item_payload.get("payload"))
    if not isinstance(definition, dict):
        raise ValueError("The retained item has no definition.")
    points_value = item_payload.get("possible_points", item_payload.get("points", 1))
    points = _decimal(points_value, field="possible_points", nonnegative=True)
    if points <= 0:
        raise ValueError("possible_points must be positive.")
    return type_key, deepcopy(definition), points


def _canonical_unanswered(type_key: str) -> dict[str, Any]:
    """Use an adapter shape for objective scorers without inventing numeric 0."""
    if type_key in {"liveclassroom.multiple_choice"}:
        return {"choices": []}
    if type_key in {"liveclassroom.single_choice", "liveclassroom.true_false", "liveclassroom.question"}:
        return {"choice": ""}
    if type_key == "liveclassroom.short_text":
        return {"text": ""}
    return {}


def _result(*, status: str, points: Decimal, answer, score=None, code: str = "") -> dict[str, Any]:
    normalized = None if score is None else score
    awarded = None if normalized is None else (normalized * points).quantize(POINT_QUANTUM, rounding=ROUND_HALF_UP)
    return {
        "status": status,
        "normalized_score": normalized,
        "score": normalized,
        "possible_points": points,
        "awarded_points": awarded,
        "retained_answer": deepcopy(answer),
        "answer": deepcopy(answer),
        "source": "automatic",
        "rule_version": RULE_VERSION,
        "diagnostic_code": code,
    }


def score_retained_item(item_payload: dict[str, Any], answer=None) -> dict[str, Any]:
    """Score one retained manifest item, returning a persistence-ready result.

    ``answer=None`` means no answer was saved.  Other malformed answer values
    are errors and are never silently converted to a zero.
    """
    try:
        type_key, definition, points = _item_fields(item_payload)
    except ValueError as exc:
        return _result(status="error", points=Decimal("0"), answer=answer, code="invalid_retained_item") | {
            "detail": str(exc)
        }
    try:
        from liveclassroom.registry import activity_registry

        activity_type = activity_registry.get(type_key)
    except KeyError:
        return _result(status="error", points=points, answer=answer, code="missing_grader")
    try:
        definition = activity_type.validate(definition)
    except (TypeError, ValueError) as exc:
        return _result(status="error", points=points, answer=answer, code="invalid_definition") | {
            "detail": str(exc)
        }
    if _key(definition) is _MISSING:
        if "manual" in activity_type.capabilities:
            return _result(status="pending", points=points, answer=answer, code="manual_grading_required")
        return _result(status="ungraded", points=points, answer=answer, code="missing_answer_key")

    if answer is None:
        # Validate the configuration above and pass a type-specific empty
        # adapter through the registry where that adapter is supported. The
        # built-in answer validators intentionally reject empty student
        # answers; that rejection is expected for this distinct, no-save
        # state, which receives an explicit zero. In particular, numeric
        # questions never synthesize value=0 (zero can be the answer key).
        canonical = _canonical_unanswered(type_key)
        try:
            normalized_empty = activity_type.normalize(deepcopy(canonical))
            normalized_empty = activity_type.validate_answer(normalized_empty, deepcopy(definition))
            scored_empty = activity_type.score(normalized_empty, definition)
            if not isinstance(scored_empty, dict) or "score" not in scored_empty:
                raise ValueError("The activity scorer returned no score.")
            score_empty = _decimal(scored_empty.get("score"), field="score")
            if 0 <= score_empty <= 1:
                return _result(status="graded", points=points, answer=None, score=score_empty)
        except (KeyError, TypeError, ValueError, DecimalException):
            pass
        if type_key in {
            "liveclassroom.single_choice",
            "liveclassroom.multiple_choice",
            "liveclassroom.true_false",
            "liveclassroom.question",
            "liveclassroom.short_text",
            "liveclassroom.numeric",
        }:
            return _result(status="graded", points=points, answer=None, score=Decimal("0"))
        answer = canonical
    if not isinstance(answer, dict):
        return _result(status="error", points=points, answer=answer, code="invalid_saved_answer")
    try:
        normalized_answer = activity_type.validate_answer(deepcopy(answer), deepcopy(definition))
        scored = activity_type.score(normalized_answer, definition)
        if not isinstance(scored, dict) or "score" not in scored:
            if "manual" in activity_type.capabilities:
                return _result(status="pending", points=points, answer=answer, code="manual_grading_required")
            return _result(status="error", points=points, answer=answer, code="missing_score")
        score = _decimal(scored["score"], field="score")
        if score < 0 or score > 1:
            raise ValueError("score must be between zero and one.")
    except (KeyError, TypeError, ValueError, DecimalException) as exc:
        return _result(status="error", points=points, answer=answer, code="invalid_saved_answer") | {
            "detail": str(exc)
        }
    return _result(
        status="graded",
        points=points,
        answer=normalized_answer,
        score=score,
    )


def _aware_now(value: datetime | None) -> datetime:
    current = timezone.now() if value is None else value
    return timezone.make_aware(current, timezone.get_current_timezone()) if timezone.is_naive(current) else current


def _latest_answer(item: AssessmentAttemptItem):
    return item.answer_revisions.order_by("-version").first()


def _grade_payload(item: AssessmentAttemptItem) -> dict[str, Any]:
    answer = _latest_answer(item)
    manifest = deepcopy(item.manifest) if isinstance(item.manifest, dict) else {}
    # The persisted AttemptItem points are authoritative even when a corrupt
    # manifest omits its duplicate display value.  This keeps totals intact
    # while recording an explicit invalid-retained-item result.
    manifest["possible_points"] = str(item.points)
    return score_retained_item(manifest, answer=answer.answer if answer else None)


def _aggregate(attempt: AssessmentAttempt, rows: list[AssessmentItemGrade], now: datetime) -> AssessmentAttemptGrade:
    possible = sum((row.possible_points for row in rows), Decimal("0"))
    awarded = sum((row.awarded_points or Decimal("0") for row in rows), Decimal("0"))
    pending = sum(row.status == AssessmentItemGrade.Status.PENDING for row in rows)
    ungraded = sum(row.status == AssessmentItemGrade.Status.UNGRADED for row in rows)
    errors = sum(row.status == AssessmentItemGrade.Status.ERROR for row in rows)
    graded = sum(row.status == AssessmentItemGrade.Status.GRADED for row in rows)
    aggregate, _ = AssessmentAttemptGrade.objects.update_or_create(
        attempt=attempt,
        defaults={
            "status": (
                AssessmentAttemptGrade.Status.GRADED
                if not pending and not ungraded and not errors
                else AssessmentAttemptGrade.Status.PENDING
            ),
            "possible_points": possible.quantize(POINT_QUANTUM, rounding=ROUND_HALF_UP),
            "awarded_points": awarded.quantize(POINT_QUANTUM, rounding=ROUND_HALF_UP),
            "graded_count": graded,
            "pending_count": pending,
            "ungraded_count": ungraded,
            "error_count": errors,
            "updated_at": now,
        },
    )
    return aggregate


@transaction.atomic
def _grade_submitted_attempt(
    *, attempt: AssessmentAttempt, now: datetime | None = None, retry_errors: bool = False
) -> AssessmentAttemptGrade:
    """Materialize one submitted attempt under the same durable row lock."""
    current = _aware_now(now)
    locked = AssessmentAttempt.objects.select_for_update().get(pk=attempt.pk)
    if locked.status != AssessmentAttempt.Status.SUBMITTED:
        raise AssessmentGradingError("Only a submitted attempt can be graded.")
    items = list(AssessmentAttemptItem.objects.select_for_update().filter(attempt=locked).order_by("position", "id"))
    existing = list(AssessmentItemGrade.objects.filter(item__in=items).order_by("item_id"))
    existing_by_item = {row.item_id: row for row in existing}
    for item in items:
        existing_row = existing_by_item.get(item.pk)
        if existing_row is not None and not (
            retry_errors
            and existing_row.status == AssessmentItemGrade.Status.ERROR
            and existing_row.diagnostic_code in RETRYABLE_ERROR_CODES
        ):
            continue
        payload = _grade_payload(item)
        if existing_row is None:
            row = AssessmentItemGrade.objects.create(
                item=item,
                status=payload["status"],
                normalized_score=payload["normalized_score"],
                possible_points=payload["possible_points"],
                awarded_points=payload["awarded_points"],
                retained_answer=payload["retained_answer"],
                source=payload["source"],
                rule_version=payload["rule_version"],
                diagnostic_code=payload["diagnostic_code"],
                graded_at=current,
            )
        else:
            row = existing_row
            for field in (
                "status",
                "normalized_score",
                "possible_points",
                "awarded_points",
                "retained_answer",
                "source",
                "rule_version",
                "diagnostic_code",
                "graded_at",
            ):
                setattr(row, field, payload[field] if field != "graded_at" else current)
            row.save(update_fields=[
                "status", "normalized_score", "possible_points", "awarded_points",
                "retained_answer", "source", "rule_version", "diagnostic_code", "graded_at", "updated_at",
            ])
        AssessmentGradeDecision.objects.create(
            attempt=locked,
            item=item,
            status=row.status,
            normalized_score=row.normalized_score,
            possible_points=row.possible_points,
            awarded_points=row.awarded_points,
            retained_answer=row.retained_answer,
            source=row.source,
            rule_version=row.rule_version,
            diagnostic_code=row.diagnostic_code,
            reason="automatic submission grading",
            created_at=current,
        )
        existing_by_item[item.pk] = row
    return _aggregate(locked, list(existing_by_item.values()), current)


def grade_submitted_attempt(*, attempt: AssessmentAttempt, now: datetime | None = None) -> AssessmentAttemptGrade:
    """Grade one submitted attempt exactly once, under an attempt lock."""
    return _grade_submitted_attempt(attempt=attempt, now=now, retry_errors=False)


def _needs_grading(attempt_id: int) -> bool:
    aggregate = AssessmentAttemptGrade.objects.filter(attempt_id=attempt_id).first()
    if aggregate is None:
        return True
    return AssessmentItemGrade.objects.filter(
        item__attempt_id=attempt_id,
        status=AssessmentItemGrade.Status.ERROR,
        diagnostic_code__in=RETRYABLE_ERROR_CODES,
    ).exists()


def grade_pending_attempts(limit: int = 500, now: datetime | None = None) -> dict[str, int]:
    """Grade a bounded set of submitted attempts lacking current results."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise AssessmentGradingError("limit must be a positive integer.")
    ids = list(
        AssessmentAttempt.objects.filter(status=AssessmentAttempt.Status.SUBMITTED)
        .order_by("submitted_at", "id")
        .values_list("pk", flat=True)[:limit]
    )
    counts = {"scanned": len(ids), "graded": 0, "already_graded": 0, "failed": 0}
    for attempt_id in ids:
        if not _needs_grading(attempt_id):
            counts["already_graded"] += 1
            continue
        try:
            _grade_submitted_attempt(attempt=AssessmentAttempt(pk=attempt_id), now=now, retry_errors=True)
        except Exception:
            counts["failed"] += 1
        else:
            counts["graded"] += 1
    return counts


def _grade_after_submission(sender, attempt_id: int, **kwargs) -> None:
    """Best-effort post-commit hook; durable submission must never roll back."""
    del sender, kwargs
    try:
        grade_submitted_attempt(attempt=AssessmentAttempt(pk=attempt_id))
    except Exception:
        # Recovery is deliberately explicit and bounded.  Do not turn a
        # transient scorer/database failure into a submission failure or log
        # retained answers and provider diagnostics from a callback.
        return


attempt_submitted.connect(
    _grade_after_submission,
    weak=False,
    dispatch_uid="liveclassroom.automatic_attempt_grading",
)


__all__ = [
    "AssessmentGradingError",
    "POINT_QUANTUM",
    "RETRYABLE_ERROR_CODES",
    "RULE_VERSION",
    "grade_pending_attempts",
    "grade_submitted_attempt",
    "score_retained_item",
]
