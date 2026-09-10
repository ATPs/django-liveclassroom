"""Human grading of submitted subjective assessment answers.

The queue is deliberately small and account based.  It reads the immutable
attempt item manifest and the materialized task-31 item result, while writes
lock the attempt before its item and append a new grade decision.  Student
answers are never looked up by a display name and are never exposed through a
student-facing endpoint.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from liveclassroom.integrations.host import host_can_grade
from liveclassroom.models import (
    AssessmentAttempt,
    AssessmentAttemptItem,
    AssessmentGradeDecision,
    AssessmentItemGrade,
    AssessmentRun,
    CourseMembership,
)

from .assessment_grading import POINT_QUANTUM, grade_submitted_attempt, recompute_attempt_grade
from .classroom import ClassroomError
from .permissions import can_teach

MANUAL_SOURCE = "manual"
MANUAL_RULE_VERSION = "manual-v1"
COMMENT_MAX_LENGTH = 4000
REASON_MAX_LENGTH = 255
NORMALIZED_QUANTUM = Decimal("0.0000000001")
_STAFF_ROLES = (CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT)


class ManualGradingError(ClassroomError):
    """A manual-grade request is invalid or outside the actor's scope."""


def _now(value: datetime | None) -> datetime:
    current = timezone.now() if value is None else value
    return timezone.make_aware(current, timezone.get_current_timezone()) if timezone.is_naive(current) else current


def _score(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ManualGradingError("normalized_score must be a finite decimal between zero and one.")
    try:
        score = Decimal(str(value))
    except (DecimalException, TypeError, ValueError) as exc:
        raise ManualGradingError("normalized_score must be a finite decimal between zero and one.") from exc
    if not score.is_finite() or score < 0 or score > 1:
        raise ManualGradingError("normalized_score must be between zero and one.")
    # The model stores at most ten fractional digits.  Reject excess precision
    # rather than silently changing a teacher's awarded score.
    if score.as_tuple().exponent < -10:
        raise ManualGradingError("normalized_score has at most ten decimal places.")
    return score.quantize(NORMALIZED_QUANTUM, rounding=ROUND_HALF_UP)


def _text(value: Any, *, field: str, maximum: int, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ManualGradingError(f"{field} must be text.")
    if required and not value.strip():
        raise ManualGradingError(f"{field} is required.")
    if len(value) > maximum:
        raise ManualGradingError(f"{field} must be at most {maximum} characters.")
    return value.strip() if required else value


def _run_scope(actor) -> Q:
    """Return the runs whose submitted attempts this actor may grade."""
    if getattr(actor, "is_superuser", False):
        return Q()
    return (
        Q(run__owner_id=actor.pk)
        | Q(run__course__created_by_id=actor.pk)
        | Q(run__course__memberships__user_id=actor.pk, run__course__memberships__role__in=_STAFF_ROLES)
    )


def _has_grading_scope(actor) -> bool:
    """Keep an authenticated student from probing an empty queue."""
    if getattr(actor, "is_superuser", False):
        return True
    return AssessmentRun.objects.filter(
        Q(owner_id=actor.pk)
        | Q(course__created_by_id=actor.pk)
        | Q(course__memberships__user_id=actor.pk, course__memberships__role__in=_STAFF_ROLES)
    ).exists()


def can_grade_attempt(actor, attempt: AssessmentAttempt) -> bool:
    """Apply package teacher policy and the configured host grading capability."""
    if not getattr(actor, "is_authenticated", False) or not can_teach(actor):
        return False
    course = getattr(attempt.run, "course", None)
    package_allowed = bool(
        getattr(actor, "is_superuser", False)
        or attempt.run.owner_id == actor.pk
        or (
            course is not None
            and (
                course.created_by_id == actor.pk
                or CourseMembership.objects.filter(course=course, user=actor, role__in=_STAFF_ROLES).exists()
            )
        )
    )
    return bool(
        package_allowed
        and host_can_grade(actor=actor, attempt_id=getattr(attempt, "pk", None), package_allowed=True)
    )


def _resolve_run_filter(run_id: Any) -> Q:
    if run_id in (None, ""):
        return Q()
    if isinstance(run_id, AssessmentRun):
        return Q(run_id=run_id.pk)
    try:
        value = UUID(str(run_id))
    except (AttributeError, TypeError, ValueError):
        try:
            return Q(run_id=int(run_id))
        except (TypeError, ValueError) as exc:
            raise ManualGradingError("run_id must identify an assessment run.") from exc
    return Q(run__public_id=value)


def _resolve_item_type(item: AssessmentAttemptItem):
    manifest = item.manifest if isinstance(item.manifest, dict) else {}
    type_key = manifest.get("type_key")
    if isinstance(type_key, str) and "." not in type_key:
        type_key = f"liveclassroom.{type_key}"
    if not isinstance(type_key, str) or not type_key.strip():
        raise ManualGradingError("The assessment item has no answer type.")
    try:
        from liveclassroom.registry import activity_registry

        activity_type = activity_registry.get(type_key.strip())
    except KeyError as exc:
        raise ManualGradingError("This assessment item does not support manual grading.") from exc
    if "manual" not in activity_type.capabilities:
        raise ManualGradingError("Only subjective items can be manually graded.")
    return activity_type


def _prompt(item: AssessmentAttemptItem) -> str:
    manifest = item.manifest if isinstance(item.manifest, dict) else {}
    payload = manifest.get("payload", manifest.get("definition", {}))
    if not isinstance(payload, dict):
        return ""
    for key in ("prompt", "stem_markdown", "markdown"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _latest_decision(item: AssessmentAttemptItem) -> AssessmentGradeDecision | None:
    return item.grade_decisions.order_by("-created_at", "-id").first()


def _decision_payload(grade: AssessmentItemGrade, decision: AssessmentGradeDecision | None) -> dict[str, Any]:
    return {
        "status": grade.status,
        "normalized_score": grade.normalized_score,
        "awarded_points": grade.awarded_points,
        "possible_points": grade.possible_points,
        "source": grade.source,
        "rule_version": grade.rule_version,
        "comment": grade.comment,
        "reason": decision.reason if decision is not None else "",
        "actor_id": decision.actor_id if decision is not None else None,
        "created_at": decision.created_at.isoformat() if decision is not None else None,
    }


def _item_payload(item: AssessmentAttemptItem, grade: AssessmentItemGrade) -> dict[str, Any]:
    attempt = item.attempt
    user = attempt.user
    username = user.get_username() if hasattr(user, "get_username") else str(user)
    decision = _latest_decision(item)
    result = {
        "attempt_id": str(attempt.public_id),
        "attempt_pk": attempt.pk,
        "item_key": str(item.key),
        "run_id": str(attempt.run.public_id),
        "run_title": attempt.run.title,
        "student_id": attempt.user_id,
        "student_username": username,
        "prompt": _prompt(item),
        "retained_prompt": _prompt(item),
        "answer": deepcopy(grade.retained_answer),
        "retained_answer": deepcopy(grade.retained_answer),
        "possible_points": grade.possible_points,
        "status": grade.status,
        "decision": _decision_payload(grade, decision),
        "normalized_score": grade.normalized_score,
        "awarded_points": grade.awarded_points,
        "comment": grade.comment,
    }
    return result


def _materialize_grade(attempt: AssessmentAttempt, item: AssessmentAttemptItem) -> AssessmentItemGrade:
    """Ensure task-31's current result exists before reading the queue."""
    grade = AssessmentItemGrade.objects.filter(item=item).first()
    if grade is None:
        grade_submitted_attempt(attempt=attempt)
        grade = AssessmentItemGrade.objects.filter(item=item).first()
    if grade is None:
        raise ManualGradingError("The assessment item has no current grade result.")
    return grade


def list_manual_grading_items(actor, run_id=None, class_id=None) -> list[dict[str, Any]]:
    """List pending manual items visible to authorized teaching staff."""
    if not getattr(actor, "is_authenticated", False):
        raise ManualGradingError("Authentication required.")
    if not can_teach(actor):
        raise ManualGradingError("Teacher grading access is required.")
    if not _has_grading_scope(actor):
        raise ManualGradingError("Teacher grading access is required.")
    filters = _run_scope(actor) & _resolve_run_filter(run_id)
    if class_id not in (None, ""):
        try:
            filters &= Q(run__course_id=int(class_id))
        except (TypeError, ValueError) as exc:
            raise ManualGradingError("class_id must be an integer.") from exc
    attempts = list(
        AssessmentAttempt.objects.filter(
            filters,
            status=AssessmentAttempt.Status.SUBMITTED,
        )
        .select_related("run", "run__course", "user")
        .prefetch_related("items", "items__grade_decisions")
        .distinct()
        .order_by("submitted_at", "id")
    )
    rows: list[dict[str, Any]] = []
    for attempt in attempts:
        for item in attempt.items.all():
            try:
                _resolve_item_type(item)
            except ManualGradingError:
                continue
            grade = _materialize_grade(attempt, item)
            if grade.status != AssessmentItemGrade.Status.PENDING:
                continue
            # Materializing a missing grade invalidates prefetch caches.  The
            # fresh row is used so the retained answer and metadata are exact.
            item = AssessmentAttemptItem.objects.select_related("attempt__run", "attempt__user").get(pk=item.pk)
            grade = AssessmentItemGrade.objects.get(item=item)
            rows.append(_item_payload(item, grade))
    return rows


def _item_for_write(attempt_item: AssessmentAttemptItem) -> AssessmentAttemptItem:
    if not isinstance(attempt_item, AssessmentAttemptItem) or not attempt_item.pk:
        raise ManualGradingError("attempt_item must be a saved assessment item.")
    try:
        return (
            AssessmentAttemptItem.objects.select_for_update()
            .select_related("attempt__run", "attempt__run__course", "attempt__user")
            .get(pk=attempt_item.pk)
        )
    except AssessmentAttemptItem.DoesNotExist as exc:
        raise ManualGradingError("The assessment item was not found.") from exc


@transaction.atomic
def save_manual_grade(
    *,
    attempt_item: AssessmentAttemptItem,
    normalized_score,
    comment: str = "",
    actor,
    reason: str,
    now: datetime | None = None,
) -> AssessmentItemGrade:
    """Save one explicit human decision and recompute its attempt total."""
    current = _now(now)
    score = _score(normalized_score)
    comment = _text(comment, field="comment", maximum=COMMENT_MAX_LENGTH)
    reason = _text(reason, field="reason", maximum=REASON_MAX_LENGTH, required=True)
    if not getattr(actor, "is_authenticated", False) or not can_teach(actor):
        raise ManualGradingError("Teacher grading access is required.")

    # Lock the parent first, matching answer-save, submission and automatic
    # grading.  The caller's object is only an identifier; it cannot select a
    # different student's item by changing related fields.
    try:
        item_ref = AssessmentAttemptItem.objects.select_related("attempt").get(pk=attempt_item.pk)
        locked_attempt = (
            AssessmentAttempt.objects.select_for_update()
            .select_related("run", "run__course", "user")
            .get(pk=item_ref.attempt_id)
        )
    except (AssessmentAttemptItem.DoesNotExist, AssessmentAttempt.DoesNotExist) as exc:
        raise ManualGradingError("The assessment item was not found.") from exc
    if not can_grade_attempt(actor, locked_attempt):
        raise ManualGradingError("You do not have permission to grade this attempt.")
    if locked_attempt.status != AssessmentAttempt.Status.SUBMITTED:
        raise ManualGradingError("Only a submitted attempt can be manually graded.")
    locked_item = _item_for_write(attempt_item)
    if locked_item.attempt_id != locked_attempt.pk:
        raise ManualGradingError("The assessment item does not belong to this attempt.")
    _resolve_item_type(locked_item)
    grade = AssessmentItemGrade.objects.select_for_update().filter(item=locked_item).first()
    if grade is None:
        # This is normally done by the post-submit callback.  The explicit
        # call also makes queue/API recovery safe after a callback outage.
        grade_submitted_attempt(attempt=locked_attempt)
        grade = AssessmentItemGrade.objects.select_for_update().filter(item=locked_item).first()
    if grade is None:
        raise ManualGradingError("The assessment item has no current grade result.")
    if grade.status == AssessmentItemGrade.Status.GRADED:
        if grade.source != MANUAL_SOURCE:
            raise ManualGradingError("This item is already automatically graded.")
        # A retry of the same command is a stable read.  Do not append a
        # duplicate decision or silently turn task 33's correction into an
        # overwrite.
        return grade
    if grade.status != AssessmentItemGrade.Status.PENDING:
        raise ManualGradingError("This item is not pending manual grading.")

    awarded = (score * Decimal(str(locked_item.points))).quantize(POINT_QUANTUM, rounding=ROUND_HALF_UP)
    retained_answer = deepcopy(grade.retained_answer)
    grade.status = AssessmentItemGrade.Status.GRADED
    grade.normalized_score = score
    grade.possible_points = locked_item.points
    grade.awarded_points = awarded
    grade.retained_answer = retained_answer
    grade.source = MANUAL_SOURCE
    grade.rule_version = MANUAL_RULE_VERSION
    grade.diagnostic_code = ""
    grade.comment = comment
    grade.graded_at = current
    grade.save(
        update_fields=[
            "status",
            "normalized_score",
            "possible_points",
            "awarded_points",
            "retained_answer",
            "source",
            "rule_version",
            "diagnostic_code",
            "comment",
            "graded_at",
            "updated_at",
        ]
    )
    AssessmentGradeDecision.objects.create(
        attempt=locked_attempt,
        item=locked_item,
        status=grade.status,
        normalized_score=grade.normalized_score,
        possible_points=grade.possible_points,
        awarded_points=grade.awarded_points,
        retained_answer=retained_answer,
        source=MANUAL_SOURCE,
        rule_version=MANUAL_RULE_VERSION,
        diagnostic_code="",
        comment=comment,
        actor=actor,
        reason=reason,
        created_at=current,
    )
    # Use task-31's persisted-row aggregate path.  No release decision is
    # made here and no student-facing result is changed by this operation.
    recompute_attempt_grade(attempt=locked_attempt, now=current)
    return grade


__all__ = [
    "COMMENT_MAX_LENGTH",
    "MANUAL_RULE_VERSION",
    "MANUAL_SOURCE",
    "ManualGradingError",
    "can_grade_attempt",
    "list_manual_grading_items",
    "save_manual_grade",
]
