"""Permission-scoped, derived grade summaries for classes and course groups.

Summaries intentionally have no materialized schema.  They are derived from
the explicit class roster, retained assessment attempts, and current grade
rows each time a teacher requests them.  Historical attempts and grade audit
decisions remain available through the existing review and grading services.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.contrib.auth import get_user_model

from liveclassroom.models import (
    AssessmentAttempt,
    AssessmentAttemptGrade,
    AssessmentRun,
    Course,
    CourseMembership,
    Participant,
    TeachingCourse,
)

from .classroom import ClassroomError
from .organization import list_teaching_courses
from .permissions import can_teach

STAFF_ROLES = (CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT)
SUMMARY_STATES = frozenset({"not_started", "in_progress", "submitted", "graded", "pending", "ungraded"})
POINT_QUANTUM = Decimal("0.01")


class GradeSummaryError(ClassroomError):
    """A summary request is invalid or outside the teacher's named scope."""


def _decimal(value: Any, *, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default
    return result if result.is_finite() else default


def _points_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(POINT_QUANTUM, rounding=ROUND_HALF_UP), "f")


def _percent(numerator: int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    value = (Decimal(numerator) * Decimal("100") / Decimal(denominator)).quantize(
        POINT_QUANTUM, rounding=ROUND_HALF_UP
    )
    return format(value, "f")


def _ratio(earned: Decimal, possible: Decimal) -> str | None:
    if possible <= 0:
        return None
    value = (earned * Decimal("100") / possible).quantize(POINT_QUANTUM, rounding=ROUND_HALF_UP)
    return format(value, "f")


def _authenticated_teacher(actor) -> None:
    if not getattr(actor, "is_authenticated", False) or not can_teach(actor):
        raise GradeSummaryError("Teacher summary access is required.")


def _can_read_class(actor, course: Course) -> bool:
    if getattr(actor, "is_superuser", False) or course.created_by_id == actor.pk:
        return True
    return CourseMembership.objects.filter(
        course=course, user=actor, role__in=STAFF_ROLES
    ).exists()


def _class(value: Course | int) -> Course:
    if isinstance(value, Course):
        course_id = value.pk
    elif isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GradeSummaryError("class_id must be a positive integer.")
    else:
        course_id = value
    try:
        return Course.objects.get(pk=course_id)
    except Course.DoesNotExist as exc:
        raise GradeSummaryError("The selected class was not found.") from exc


def _teaching_course(value: TeachingCourse | int) -> TeachingCourse:
    if isinstance(value, TeachingCourse):
        teaching_course_id = value.pk
    elif isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GradeSummaryError("teaching_course_id must be a positive integer.")
    else:
        teaching_course_id = value
    try:
        return TeachingCourse.objects.get(pk=teaching_course_id)
    except TeachingCourse.DoesNotExist as exc:
        raise GradeSummaryError("The selected course was not found.") from exc


def _test_user_ids(course_ids: Iterable[int]) -> set[int]:
    return set(
        Participant.objects.filter(
            session__course_id__in=list(course_ids), is_test=True, user_id__isnull=False
        ).values_list("user_id", flat=True)
    )


def _class_users(course: Course, *, include_test: bool, run_ids: set[int]) -> list:
    """Return named roster/participant accounts without guessing identities."""
    student_ids = set(
        CourseMembership.objects.filter(course=course, role=CourseMembership.Role.STUDENT).values_list(
            "user_id", flat=True
        )
    )
    participant_ids = set(
        Participant.objects.filter(
            session__course=course, is_test=False, user_id__isnull=False
        ).values_list("user_id", flat=True)
    )
    # A test participant may also have a roster account.  Excluding that
    # account by default prevents staff test runs entering named summaries.
    test_ids = _test_user_ids([course.pk])
    if include_test:
        participant_ids.update(
            Participant.objects.filter(
                session__course=course, is_test=True, user_id__isnull=False
            ).values_list("user_id", flat=True)
        )
    user_ids = (student_ids | participant_ids) - (set() if include_test else test_ids)
    # A persisted attempt is itself explicit participation.  Include it when
    # no roster row exists, while still applying the test-account exclusion.
    attempt_ids = set(
        AssessmentAttempt.objects.filter(run_id__in=run_ids).values_list("user_id", flat=True)
    ) - (set() if include_test else test_ids)
    user_ids.update(attempt_ids)
    if not user_ids:
        return []
    return list(get_user_model().objects.filter(pk__in=user_ids).order_by("id"))


def _run_possible_points(run: AssessmentRun) -> Decimal:
    """Derive the displayed run denominator for users without attempts."""
    manifest = run.manifest if isinstance(run.manifest, dict) else {}
    sections = manifest.get("sections")
    rows: list[dict[str, Any]] = []
    if isinstance(sections, list) and sections:
        for section in sections:
            if not isinstance(section, dict) or not isinstance(section.get("entries"), list):
                continue
            for entry in section["entries"]:
                if not isinstance(entry, dict):
                    continue
                if entry.get("kind") == "fixed" and isinstance(entry.get("item"), dict):
                    rows.append(entry["item"])
                elif entry.get("kind") == "pool":
                    candidates = entry.get("candidates", [])
                    size = entry.get("sample_size")
                    if isinstance(candidates, list) and isinstance(size, int) and size > 0:
                        point_values = [_decimal(row.get("points")) for row in candidates if isinstance(row, dict)]
                        rows.extend({"points": value} for value in point_values[:size] if value is not None)
    else:
        rows = [row for row in manifest.get("items", []) if isinstance(row, dict)]
    return sum((_decimal(row.get("points"), default=Decimal("0")) or Decimal("0") for row in rows), Decimal("0"))


def _grade_state(attempt: AssessmentAttempt, grade: AssessmentAttemptGrade | None) -> str:
    if attempt.status == AssessmentAttempt.Status.IN_PROGRESS:
        return "in_progress"
    if grade is None:
        # A submitted attempt without a materialized result is waiting for
        # automatic/manual grading, never a failing score.
        return "pending"
    if grade.status == AssessmentAttemptGrade.Status.GRADED and not (
        grade.pending_count or grade.ungraded_count or grade.error_count
    ):
        return "graded"
    if grade.pending_count or grade.status == AssessmentAttemptGrade.Status.PENDING:
        return "pending"
    if grade.ungraded_count or grade.error_count:
        return "ungraded"
    return "submitted"


def _attempt_possible(attempt: AssessmentAttempt, grade: AssessmentAttemptGrade | None) -> Decimal:
    if grade is not None:
        return _decimal(grade.possible_points, default=Decimal("0")) or Decimal("0")
    return sum((item.points for item in attempt.items.all()), Decimal("0"))


def _attempt_payload(
    attempt: AssessmentAttempt, grade: AssessmentAttemptGrade | None, *, include_audit: bool = False
) -> dict[str, Any]:
    state = _grade_state(attempt, grade)
    possible = _attempt_possible(attempt, grade)
    earned = None if grade is None else _decimal(grade.awarded_points)
    pending_count = 0 if grade is None else grade.pending_count
    result = {
        "id": str(attempt.public_id),
        "attempt_id": str(attempt.public_id),
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "state": state,
        "earned_points": _points_text(earned),
        "awarded_points": _points_text(earned),
        "possible_points": _points_text(possible),
        "pending_count": pending_count,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
    }
    if include_audit:
        result["run_id"] = str(attempt.run.public_id)
    return result


def _cell(
    attempts: list[AssessmentAttempt],
    grades: Mapping[int, AssessmentAttemptGrade],
    *,
    run: AssessmentRun,
) -> dict[str, Any]:
    ordered = sorted(
        attempts,
        key=lambda attempt: (
            attempt.submitted_at is not None,
            attempt.submitted_at or attempt.started_at,
            attempt.attempt_number,
            attempt.pk,
        ),
        reverse=True,
    )
    submitted = [attempt for attempt in ordered if attempt.status == AssessmentAttempt.Status.SUBMITTED]
    selected = submitted[0] if submitted else None
    active = next((attempt for attempt in ordered if attempt.status == AssessmentAttempt.Status.IN_PROGRESS), None)
    selected_grade = grades.get(selected.pk) if selected is not None else None
    if selected is not None:
        selected_payload = _attempt_payload(selected, selected_grade, include_audit=True)
        state = selected_payload["state"]
        earned = selected_payload["earned_points"]
        possible = selected_payload["possible_points"]
        pending_count = selected_payload["pending_count"]
        selected_id = selected_payload["id"]
    elif active is not None:
        active_payload = _attempt_payload(active, None, include_audit=True)
        state = "in_progress"
        earned = None
        possible = active_payload["possible_points"]
        pending_count = 0
        selected_id = None
    else:
        state = "not_started"
        earned = None
        possible = _points_text(_run_possible_points(run))
        pending_count = 0
        selected_id = None
    active_payload = (
        _attempt_payload(active, grades.get(active.pk), include_audit=True) if active is not None else None
    )
    return {
        "run_id": str(run.public_id),
        "run_title": run.title,
        "state": state,
        "status": state,
        "earned_points": earned,
        "awarded_points": earned,
        "possible_points": possible,
        "pending_count": pending_count,
        "attempt_id": selected_id,
        "selected_attempt_id": selected_id,
        "active_attempt": active_payload,
        "attempts": [_attempt_payload(attempt, grades.get(attempt.pk), include_audit=True) for attempt in ordered],
    }


def _run_distribution(cells: list[dict[str, Any]]) -> dict[str, Any]:
    graded = [cell for cell in cells if cell["state"] == "graded"]
    pending = sum(cell["state"] == "pending" for cell in cells)
    scores = []
    for cell in graded:
        earned = _decimal(cell["earned_points"], default=Decimal("0")) or Decimal("0")
        possible = _decimal(cell["possible_points"], default=Decimal("0")) or Decimal("0")
        scores.append(
            {
                "student_id": cell["student_id"],
                "attempt_id": cell["attempt_id"],
                "earned_points": _points_text(earned),
                "possible_points": _points_text(possible),
                "percent": _ratio(earned, possible),
            }
        )
    return {
        "scores": scores,
        "graded_count": len(graded),
        "excluded_pending_count": pending,
        "pending_count": pending,
    }


def _overall(cells: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(cells)
    graded = [row for row in rows if row["state"] == "graded"]
    earned = sum(
        (_decimal(row["earned_points"], default=Decimal("0")) or Decimal("0") for row in graded),
        Decimal("0"),
    )
    possible = sum(
        (_decimal(row["possible_points"], default=Decimal("0")) or Decimal("0") for row in graded),
        Decimal("0"),
    )
    pending = sum(row["state"] == "pending" for row in rows)
    return {
        "fully_graded_attempts": len(graded),
        "graded_count": len(graded),
        "earned_points": _points_text(earned),
        "possible_points": _points_text(possible),
        "pending_count": pending,
        "percent": _ratio(earned, possible),
    }


def _summary_for_class(actor, course: Course, *, include_test: bool = False) -> dict[str, Any]:
    if not _can_read_class(actor, course):
        raise GradeSummaryError("You do not have permission to view this class summary.")
    runs = list(
        AssessmentRun.objects.filter(course=course)
        .select_related("course")
        .order_by("created_at", "id")
    )
    run_ids = {run.pk for run in runs}
    users = _class_users(course, include_test=include_test, run_ids=run_ids)
    user_ids = {user.pk for user in users}
    attempts = list(
        AssessmentAttempt.objects.filter(run_id__in=run_ids, user_id__in=user_ids)
        .select_related("run", "user")
        .prefetch_related("items")
        .order_by("user_id", "run_id", "attempt_number", "id")
    )
    grades = {
        grade.attempt_id: grade
        for grade in AssessmentAttemptGrade.objects.filter(attempt_id__in=[attempt.pk for attempt in attempts])
    }
    by_user_run: dict[tuple[int, int], list[AssessmentAttempt]] = defaultdict(list)
    for attempt in attempts:
        by_user_run[(attempt.user_id, attempt.run_id)].append(attempt)
    rows = []
    cells_by_run: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for user in users:
        cells = {}
        for run in runs:
            cell = _cell(by_user_run[(user.pk, run.pk)], grades, run=run)
            cell["student_id"] = user.pk
            cells[str(run.public_id)] = cell
            cells_by_run[run.pk].append(cell)
        username = user.get_username() if hasattr(user, "get_username") else str(user)
        rows.append({"student_id": user.pk, "student_username": username, "cells": cells})

    run_payloads = []
    for run in runs:
        cells = cells_by_run[run.pk]
        states = [cell["state"] for cell in cells]
        completed = sum(state in {"submitted", "graded", "pending", "ungraded"} for state in states)
        distribution = _run_distribution(cells)
        run_payloads.append(
            {
                "id": run.id,
                "public_id": str(run.public_id),
                "title": run.title,
                "course_id": course.pk,
                "possible_points": _points_text(_run_possible_points(run)),
                "counts": {state: states.count(state) for state in SUMMARY_STATES},
                "completion": {
                    "completed": completed,
                    "denominator": len(users),
                    "percent": _percent(completed, len(users)),
                },
                "distribution": distribution,
            }
        )
    all_cells = [cell for values in cells_by_run.values() for cell in values]
    states = [cell["state"] for cell in all_cells]
    return {
        "scope": {"kind": "class", "id": course.pk, "class_id": course.pk, "title": course.title},
        "class": {"id": course.pk, "title": course.title},
        "runs": run_payloads,
        "students": rows,
        "counts": {state: states.count(state) for state in SUMMARY_STATES},
        "overall": _overall(all_cells),
        "roster": {"denominator": len(users), "student_count": len(users), "include_test": include_test},
    }


def class_grade_summary(actor, class_id: Course | int, *, include_test: bool = False) -> dict[str, Any]:
    """Return one explicitly scoped class's derived assessment summary."""
    _authenticated_teacher(actor)
    if not isinstance(include_test, bool):
        raise GradeSummaryError("include_test must be a boolean.")
    return _summary_for_class(actor, _class(class_id), include_test=include_test)


def _course_runs_payload(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for summary in summaries:
        rows.extend(summary["runs"])
    return rows


def teaching_course_grade_summary(
    actor, teaching_course_id: TeachingCourse | int, *, include_test: bool = False
) -> dict[str, Any]:
    """Summarize only classes the actor may read inside an owned grouping."""
    _authenticated_teacher(actor)
    group = _teaching_course(teaching_course_id)
    # Owning a TeachingCourse does not itself grant access to named class data.
    if not list_teaching_courses(actor=actor).filter(pk=group.pk).exists():
        raise GradeSummaryError("You do not have permission to view this course summary.")
    classes = list(Course.objects.filter(teaching_course=group).order_by("title", "id"))
    summaries = []
    for course in classes:
        if _can_read_class(actor, course):
            summaries.append(_summary_for_class(actor, course, include_test=include_test))
    runs = _course_runs_payload(summaries)
    student_rows: dict[int, dict[str, Any]] = {}
    all_cells = []
    for summary in summaries:
        for row in summary["students"]:
            target = student_rows.setdefault(
                row["student_id"],
                {"student_id": row["student_id"], "student_username": row["student_username"], "cells": {}},
            )
            target["cells"].update(deepcopy(row["cells"]))
        all_cells.extend(cell for row in summary["students"] for cell in row["cells"].values())
    return {
        "scope": {"kind": "course", "id": group.pk, "course_id": group.pk, "title": group.title},
        "course": {"id": group.pk, "title": group.title},
        "classes": summaries,
        "runs": runs,
        "students": [student_rows[key] for key in sorted(student_rows)],
        "overall": _overall(all_cells),
        "roster": {
            "denominator": sum(summary["roster"]["denominator"] for summary in summaries),
            "class_count": len(summaries),
            "include_test": include_test,
        },
    }


# These aliases keep the service discoverable for callers using the product's
# Class/Course vocabulary while preserving one implementation.
get_class_grade_summary = class_grade_summary
get_course_grade_summary = teaching_course_grade_summary
course_grade_summary = teaching_course_grade_summary
summarize_class = class_grade_summary
summarize_course = teaching_course_grade_summary


__all__ = [
    "GradeSummaryError",
    "SUMMARY_STATES",
    "class_grade_summary",
    "course_grade_summary",
    "get_class_grade_summary",
    "get_course_grade_summary",
    "summarize_class",
    "summarize_course",
    "teaching_course_grade_summary",
]
