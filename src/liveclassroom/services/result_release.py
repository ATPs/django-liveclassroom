"""Server-side policies for releasing assessment results.

Release state is deliberately separate from the immutable assessment-run
manifest.  A run may have a run-wide release, or a teacher may release one
specific attempt.  Every student-facing result is assembled from an allowlist
here; callers must not serialize the retained manifest and hide fields in a
client.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from django.db import transaction

from liveclassroom.integrations.host import host_can_manage_assessment_results
from liveclassroom.models import (
    AnswerRevision,
    AssessmentAttempt,
    AssessmentAttemptGrade,
    AssessmentAttemptItem,
    AssessmentItemGrade,
    AssessmentResultRelease,
    AssessmentRun,
    CourseMembership,
)
from liveclassroom.release_policy import (
    DEFAULT_RELEASE_POLICY,
    RELEASE_DIMENSIONS,
    RELEASE_POLICIES,
    normalize_release_policy,
)

from .assessment_timing import _aware_datetime, server_now
from .classroom import ClassroomError
from .permissions import can_teach

STAFF_ROLES = (CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT)
_SENSITIVE_PAYLOAD_KEYS = frozenset(
    {
        "answer",
        "correct_answer",
        "explanation",
        "explanation_markdown",
        "feedback",
        "comment",
        "comments",
    }
)


class ResultReleaseError(ClassroomError):
    """A malformed policy or unauthorized release operation."""


def _dimension(dimension: Any) -> str:
    value = getattr(dimension, "value", dimension)
    if not isinstance(value, str) or value not in RELEASE_DIMENSIONS:
        raise ResultReleaseError(
            "dimension must be scores, answers, explanations or comments."
        )
    return value


def _settings(run: AssessmentRun) -> dict[str, Any]:
    manifest = run.manifest if isinstance(run.manifest, dict) else {}
    settings = manifest.get("settings", {})
    return settings if isinstance(settings, dict) else {}


def run_release_policy(run: AssessmentRun) -> dict[str, str]:
    """Return the complete policy frozen in a published run."""
    settings = _settings(run)
    # ``release_policy`` is the public contract.  Keep the fallback entirely
    # local so older runs remain hidden/manual after this feature is installed.
    return normalize_release_policy(
        settings.get("release_policy"), closes_at=settings.get("closes_at")
    )


def _current(value: datetime | None) -> datetime:
    return server_now(value)


def _staff_can_manage(actor, run: AssessmentRun) -> bool:
    if not getattr(actor, "is_authenticated", False) or not can_teach(actor):
        return False
    if getattr(actor, "is_superuser", False) or run.owner_id == actor.pk:
        return True
    course = getattr(run, "course", None)
    if course is not None and course.created_by_id == actor.pk:
        return True
    return bool(
        course
        and CourseMembership.objects.filter(
            course=course, user=actor, role__in=STAFF_ROLES
        ).exists()
    )


def can_manage_result_release(actor, run: AssessmentRun) -> bool:
    """Return whether an actor may manage release state for this run."""
    return host_can_manage_assessment_results(
        actor=actor, run_id=run.pk, package_allowed=_staff_can_manage(actor, run)
    )


def _release_row(*, run: AssessmentRun, attempt: AssessmentAttempt | None, dimension: str):
    """Prefer an explicit attempt release, then fall back to the run release."""
    if attempt is not None:
        row = (
            AssessmentResultRelease.objects.filter(
                run=run, attempt=attempt, dimension=dimension, released=True
            )
            .order_by("-released_at", "-id")
            .first()
        )
        if row is not None:
            return row
    return (
        AssessmentResultRelease.objects.filter(
            run=run, attempt__isnull=True, dimension=dimension, released=True
        )
        .order_by("-released_at", "-id")
        .first()
    )


def can_release_result(
    *,
    run: AssessmentRun,
    attempt: AssessmentAttempt,
    dimension: str,
    now: datetime | None = None,
    actor=None,
) -> bool:
    """Return whether ``actor`` may see one result dimension for an attempt.

    With no actor this evaluates the release policy itself.  If an actor is
    supplied, students are restricted to their own attempt and staff may use
    the same function for authorized teacher views.
    """
    try:
        value = _dimension(dimension)
        if attempt is None or attempt.run_id != run.pk:
            return False
        policy = run_release_policy(run)[value]
    except (ResultReleaseError, ClassroomError, AttributeError, TypeError, ValueError):
        return False

    if actor is not None:
        if not getattr(actor, "is_authenticated", False):
            return False
        if actor.pk != attempt.user_id and not _staff_can_manage(actor, run):
            return False
    if policy == "never":
        return False
    if policy == "after_submit":
        return attempt.status == AssessmentAttempt.Status.SUBMITTED
    if policy == "after_close":
        # Authoring rejects a missing close.  The defensive branch makes an
        # old/malformed run fail closed rather than releasing immediately.
        closes_at = _settings(run).get("closes_at")
        if closes_at is None:
            return False
        try:
            return _current(now) >= _aware_datetime(closes_at, "closes_at")
        except ClassroomError:
            return False
    # manual: only an explicit durable row can release it.
    return _release_row(run=run, attempt=attempt, dimension=value) is not None


def _latest_answer(item: AssessmentAttemptItem) -> AnswerRevision | None:
    cached = getattr(item, "_prefetched_objects_cache", {}).get("answer_revisions")
    if cached is not None:
        return cached[0] if cached else None
    return item.answer_revisions.order_by("-version").first()


def _safe_payload(item: AssessmentAttemptItem) -> dict[str, Any]:
    source = item.manifest if isinstance(item.manifest, dict) else {}
    payload = source.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    # Retain the prompt/options vocabulary while recursively removing fields
    # that could contain keys or teacher feedback.
    safe: dict[str, Any] = {}
    for key in ("prompt", "stem", "stem_markdown", "question", "markdown", "options"):
        if key not in payload:
            continue
        value = payload[key]
        if key == "options" and isinstance(value, list):
            options = []
            for option in value:
                if not isinstance(option, dict):
                    continue
                options.append(
                    {
                        option_key: deepcopy(option[option_key])
                        for option_key in ("id", "text", "label", "value")
                        if option_key in option
                    }
                )
            safe[key] = options
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = deepcopy(value)
    return safe


def _answer_key(item: AssessmentAttemptItem):
    source = item.manifest if isinstance(item.manifest, dict) else {}
    payload = source.get("payload", {})
    if not isinstance(payload, dict):
        return None
    for key in ("answer", "correct_answer"):
        if key in payload:
            return deepcopy(payload[key])
    return None


def _explanation(item: AssessmentAttemptItem):
    source = item.manifest if isinstance(item.manifest, dict) else {}
    payload = source.get("payload", {})
    if not isinstance(payload, dict):
        return None
    for key in ("explanation", "explanation_markdown", "feedback"):
        if key in payload:
            return deepcopy(payload[key])
    return None


def _grade_payload(item: AssessmentAttemptItem) -> dict[str, Any] | None:
    try:
        grade = item.grade
    except AssessmentItemGrade.DoesNotExist:
        grade = None
    if grade is None:
        grade = AssessmentItemGrade.objects.filter(item=item).first()
    if grade is None:
        return None
    return {
        "status": grade.status,
        "normalized_score": _decimal_text(grade.normalized_score),
        "awarded_points": _decimal_text(grade.awarded_points),
        "possible_points": _decimal_text(grade.possible_points),
    }


def _aggregate_payload(attempt: AssessmentAttempt) -> dict[str, Any] | None:
    try:
        grade = attempt.grade
    except AssessmentAttemptGrade.DoesNotExist:
        grade = None
    if grade is None:
        grade = AssessmentAttemptGrade.objects.filter(attempt=attempt).first()
    if grade is None:
        return None
    return {
        "status": grade.status,
        "awarded_points": _decimal_text(grade.awarded_points),
        "possible_points": _decimal_text(grade.possible_points),
        "graded_count": grade.graded_count,
        "pending_count": grade.pending_count,
        "ungraded_count": grade.ungraded_count,
        "error_count": grade.error_count,
    }


def _decimal_text(value):
    return format(value, "f") if value is not None else None


def student_result_payload(*, attempt: AssessmentAttempt, now: datetime | None = None) -> dict[str, Any]:
    """Serialize a student's own result with independent server-side gates."""
    run = attempt.run
    current = _current(now)
    allowed = {
        dimension: can_release_result(
            run=run, attempt=attempt, dimension=dimension, now=current, actor=attempt.user
        )
        for dimension in RELEASE_DIMENSIONS
    }
    items = []
    for item in attempt.items.all():
        row: dict[str, Any] = {
            "key": str(item.key),
            "position": item.position,
            "type_key": (item.manifest or {}).get("type_key") if isinstance(item.manifest, dict) else None,
        }
        row.update(_safe_payload(item))
        if allowed["scores"]:
            row["score"] = _grade_payload(item)
        if allowed["answers"]:
            answer = _latest_answer(item)
            row["answer"] = deepcopy(answer.answer) if answer is not None else None
            row["answer_key"] = _answer_key(item)
        if allowed["explanations"]:
            row["explanation"] = _explanation(item)
        if allowed["comments"]:
            try:
                grade = item.grade
            except AssessmentItemGrade.DoesNotExist:
                grade = None
            if grade is None:
                grade = AssessmentItemGrade.objects.filter(item=item).first()
            row["comment"] = grade.comment if grade is not None else ""
        items.append(row)

    result: dict[str, Any] = {
        "id": str(attempt.public_id),
        "run_id": str(run.public_id),
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "released": {dimension: allowed[dimension] for dimension in RELEASE_DIMENSIONS},
        "items": items,
    }
    if allowed["scores"]:
        result["score"] = _aggregate_payload(attempt)
    return result


def _validate_release_target(*, run: AssessmentRun, attempt: AssessmentAttempt | None) -> None:
    if attempt is not None and attempt.run_id != run.pk:
        raise ResultReleaseError("The attempt does not belong to this assessment run.")


@transaction.atomic
def release_result_dimension(
    *,
    run: AssessmentRun,
    dimension: str,
    actor,
    attempt: AssessmentAttempt | None = None,
    now: datetime | None = None,
) -> AssessmentResultRelease:
    """Release one dimension for a run or explicit attempt after authorization."""
    value = _dimension(dimension)
    if not can_manage_result_release(actor, run):
        raise ResultReleaseError("Teacher release access is required.")
    _validate_release_target(run=run, attempt=attempt)
    # Validate the frozen policy before writing state.  ``never`` is a valid
    # policy but still requires an explicit staff action to change metadata;
    # the visibility function will continue to deny it.
    run_release_policy(run)
    current = _current(now)
    filters = {"run": run, "dimension": value, "attempt": attempt}
    row, _created = AssessmentResultRelease.objects.select_for_update().get_or_create(**filters)
    row.released = True
    row.actor = actor
    row.released_at = current
    row.save(update_fields=["released", "actor", "released_at", "updated_at"])
    return row


__all__ = [
    "DEFAULT_RELEASE_POLICY",
    "RELEASE_DIMENSIONS",
    "RELEASE_POLICIES",
    "ResultReleaseError",
    "can_release_result",
    "can_manage_result_release",
    "normalize_release_policy",
    "release_result_dimension",
    "run_release_policy",
    "student_result_payload",
]
