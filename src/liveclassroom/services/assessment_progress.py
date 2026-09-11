"""Permission-scoped progress views for published assessment runs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Q

from liveclassroom.integrations.host import host_can_view_assessment_results, host_can_view_roster
from liveclassroom.models import (
    AssessmentAttempt,
    AssessmentAttemptGrade,
    AssessmentRun,
    Course,
    CourseMembership,
    Participant,
    Submission,
)

from .classroom import ClassroomError
from .permissions import can_teach

STAFF_ROLES = (CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT)
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
PROGRESS_STATUSES = frozenset(
    {"not_started", "in_progress", "submitted", "graded", "pending_manual", "ungraded"}
)


class AssessmentProgressError(ClassroomError):
    """A progress request is invalid or outside the actor's named-read scope."""


def _authenticated(actor) -> bool:
    return bool(getattr(actor, "is_authenticated", False) and can_teach(actor))


def _can_read_course(actor, course: Course | None) -> bool:
    if course is None or not _authenticated(actor):
        return False
    if getattr(actor, "is_superuser", False) or course.created_by_id == actor.pk:
        return True
    return CourseMembership.objects.filter(
        course=course, user=actor, role__in=STAFF_ROLES
    ).exists()


def can_read_run_progress(actor, run: AssessmentRun) -> bool:
    """Return whether the actor may read named progress for ``run``."""
    if not _authenticated(actor):
        return False
    package_allowed = bool(
        getattr(actor, "is_superuser", False)
        or run.owner_id == actor.pk
        or _can_read_course(actor, getattr(run, "course", None))
    )
    return host_can_view_assessment_results(
        actor=actor, run_id=run.pk, package_allowed=package_allowed
    )


def _run_or_denied(actor, run: AssessmentRun) -> AssessmentRun:
    if not isinstance(run, AssessmentRun) or not can_read_run_progress(actor, run):
        raise AssessmentProgressError("You do not have permission to view assessment progress.")
    return run


def _positive_int(value: Any, field: str, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise AssessmentProgressError(f"{field} must be a positive integer.") from exc
    if isinstance(value, bool) or result < 1 or str(result) != str(value).strip():
        raise AssessmentProgressError(f"{field} must be a positive integer.")
    return result


def _filters(filters: Mapping[str, Any] | None) -> dict[str, Any]:
    if filters is None:
        filters = {}
    if not isinstance(filters, Mapping):
        raise AssessmentProgressError("filters must be an object.")
    allowed = {"page", "page_size", "status", "student_id", "user_id", "class_id", "include_test"}
    unknown = set(filters) - allowed
    if unknown:
        raise AssessmentProgressError(f"Unsupported progress filters: {', '.join(sorted(map(str, unknown)))}.")
    page = _positive_int(filters.get("page"), "page", 1)
    page_size = _positive_int(filters.get("page_size"), "page_size", DEFAULT_PAGE_SIZE)
    if page_size > MAX_PAGE_SIZE:
        raise AssessmentProgressError(f"page_size cannot exceed {MAX_PAGE_SIZE}.")
    status = filters.get("status")
    if status not in (None, "") and status not in PROGRESS_STATUSES:
        raise AssessmentProgressError("status is not a supported progress status.")
    student_id = filters.get("student_id", filters.get("user_id"))
    if student_id not in (None, ""):
        student_id = _positive_int(student_id, "student_id")
    class_id = filters.get("class_id")
    if class_id not in (None, ""):
        class_id = _positive_int(class_id, "class_id")
    include_test = filters.get("include_test", False)
    if isinstance(include_test, str):
        include_test = include_test.casefold() in {"1", "true", "yes"}
    if not isinstance(include_test, bool):
        raise AssessmentProgressError("include_test must be a boolean.")
    return {
        "page": page,
        "page_size": page_size,
        "status": status or None,
        "student_id": student_id,
        "class_id": class_id,
        "include_test": include_test,
    }


def _test_user_ids() -> set[int]:
    return set(
        Participant.objects.filter(is_test=True, user_id__isnull=False).values_list("user_id", flat=True)
    )


def _username(user) -> str:
    getter = getattr(user, "get_username", None)
    return getter() if callable(getter) else str(user)


def _decimal(value):
    return format(value, "f") if value is not None else None


def _attempt_status(attempt: AssessmentAttempt, grades: Mapping[int, AssessmentAttemptGrade]) -> str:
    grade = grades.get(attempt.pk)
    if attempt.status == AssessmentAttempt.Status.IN_PROGRESS:
        return "in_progress"
    if grade is None:
        return "submitted"
    if grade.status == AssessmentAttemptGrade.Status.GRADED:
        return "graded"
    if grade.pending_count:
        return "pending_manual"
    if grade.ungraded_count or grade.error_count or grade.status == AssessmentAttemptGrade.Status.PENDING:
        return "ungraded"
    return "submitted"


def _grade_payload(grade: AssessmentAttemptGrade | None) -> dict[str, Any] | None:
    if grade is None:
        return None
    return {
        "status": grade.status,
        "awarded_points": _decimal(grade.awarded_points),
        "possible_points": _decimal(grade.possible_points),
        "graded_count": grade.graded_count,
        "pending_count": grade.pending_count,
        "ungraded_count": grade.ungraded_count,
        "error_count": grade.error_count,
    }


def _attempt_payload(attempt: AssessmentAttempt, grades: Mapping[int, AssessmentAttemptGrade]) -> dict[str, Any]:
    grade = grades.get(attempt.pk)
    return {
        "id": str(attempt.public_id),
        "run_id": str(attempt.run.public_id),
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "progress_status": _attempt_status(attempt, grades),
        "started_at": attempt.started_at.isoformat(),
        "deadline_at": attempt.deadline_at.isoformat() if attempt.deadline_at else None,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "finalization_reason": attempt.finalization_reason or None,
        "grade": _grade_payload(grade),
    }


def _row(user, attempts: list[AssessmentAttempt], grades: Mapping[int, AssessmentAttemptGrade]) -> dict[str, Any]:
    ordered = sorted(attempts, key=lambda value: (value.attempt_number, value.pk), reverse=True)
    latest = ordered[0] if ordered else None
    status = _attempt_status(latest, grades) if latest is not None else "not_started"
    return {
        "student_id": user.pk,
        "student_username": _username(user),
        "status": status,
        "attempt_count": len(ordered),
        "latest_attempt": _attempt_payload(latest, grades) if latest is not None else None,
        "attempts": [_attempt_payload(attempt, grades) for attempt in ordered],
    }


def _roster_users(actor, run: AssessmentRun):
    if run.course_id is None:
        return []
    if not host_can_view_roster(
        actor=actor, course_id=run.course_id, package_allowed=_can_read_course(actor, run.course)
    ):
        return []
    user_model = get_user_model()
    return list(
        user_model.objects.filter(
            liveclassroom_memberships__course_id=run.course_id,
            liveclassroom_memberships__role=CourseMembership.Role.STUDENT,
        )
        .order_by("id")
        .distinct()
    )


def _run_attempts(run: AssessmentRun, *, include_test: bool) -> list[AssessmentAttempt]:
    queryset = AssessmentAttempt.objects.filter(run=run).select_related("run", "user").order_by(
        "user_id", "-attempt_number", "-id"
    )
    if not include_test:
        test_ids = _test_user_ids()
        if test_ids:
            queryset = queryset.exclude(user_id__in=test_ids)
    return list(queryset)


def list_run_progress(
    actor, run: AssessmentRun, filters: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """List bounded, named learner progress for one published run."""
    run = _run_or_denied(actor, run)
    options = _filters(filters)
    if options["class_id"] is not None and options["class_id"] != run.course_id:
        raise AssessmentProgressError("The selected class is not attached to this assessment run.")
    attempts = _run_attempts(run, include_test=options["include_test"])
    grouped: dict[int, list[AssessmentAttempt]] = {}
    for attempt in attempts:
        grouped.setdefault(attempt.user_id, []).append(attempt)
    grades = {
        grade.attempt_id: grade
        for grade in AssessmentAttemptGrade.objects.filter(attempt_id__in=[attempt.pk for attempt in attempts])
    }
    users = {attempt.user_id: attempt.user for attempt in attempts}
    roster = _roster_users(actor, run)
    if roster:
        for user in roster:
            if options["include_test"] or user.pk not in _test_user_ids():
                users.setdefault(user.pk, user)
    rows = [_row(users[user_id], grouped.get(user_id, []), grades) for user_id in sorted(users)]
    if options["student_id"] is not None:
        rows = [row for row in rows if row["student_id"] == options["student_id"]]
    if options["status"] is not None:
        rows = [row for row in rows if row["status"] == options["status"]]
    eligible_total = (
        sum(options["include_test"] or user.pk not in _test_user_ids() for user in roster)
        if run.course_id is not None
        else None
    )
    counts = {
        "eligible_total": eligible_total,
        "started": sum(row["status"] != "not_started" for row in rows),
        "in_progress": sum(row["status"] == "in_progress" for row in rows),
        "submitted": sum(row["status"] in {"submitted", "graded", "pending_manual", "ungraded"} for row in rows),
        "graded": sum(row["status"] == "graded" for row in rows),
        "pending_manual": sum(row["status"] == "pending_manual" for row in rows),
        "ungraded": sum(row["status"] == "ungraded" for row in rows),
        "not_started": sum(row["status"] == "not_started" for row in rows),
    }
    total = len(rows)
    start = (options["page"] - 1) * options["page_size"]
    end = start + options["page_size"]
    return {
        "run": {
            "id": run.id,
            "public_id": str(run.public_id),
            "title": run.title,
            "audience": run.audience,
            "course_id": run.course_id,
        },
        "counts": counts,
        "pagination": {
            "page": options["page"],
            "page_size": options["page_size"],
            "total": total,
            "has_next": end < total,
            "has_previous": start > 0,
        },
        "students": rows[start:end],
    }


def _accessible_runs(actor, *, class_id: int | None = None):
    if not _authenticated(actor):
        raise AssessmentProgressError("Teacher access is required.")
    query = Q(owner_id=actor.pk)
    if getattr(actor, "is_superuser", False):
        query = Q()
    else:
        query |= Q(course__created_by_id=actor.pk) | Q(
            course__memberships__user_id=actor.pk, course__memberships__role__in=STAFF_ROLES
        )
    runs = AssessmentRun.objects.filter(query).select_related("course").distinct()
    if class_id is not None:
        runs = runs.filter(course_id=class_id)
    return runs


def get_student_overview(actor, user, class_id: int | None = None) -> dict[str, Any]:
    """Return a named learner overview without creating attendance or attempts."""
    if not _authenticated(actor) or not getattr(user, "pk", None):
        raise AssessmentProgressError("Teacher access is required.")
    if class_id is not None:
        class_id = _positive_int(class_id, "class_id")
        try:
            course = Course.objects.get(pk=class_id)
        except Course.DoesNotExist as exc:
            raise AssessmentProgressError("The selected class was not found.") from exc
        if not _can_read_course(actor, course):
            raise AssessmentProgressError("You do not have permission to view this student.")
    # A configured host can narrow access below the package's owner/course
    # scope.  Apply that per run before retrieving this learner's attempts.
    runs = [run for run in _accessible_runs(actor, class_id=class_id) if can_read_run_progress(actor, run)]
    attempts = list(
        AssessmentAttempt.objects.filter(run__in=runs, user_id=user.pk)
        .select_related("run", "user")
        .order_by("-started_at", "-id")
    )
    if not attempts:
        if class_id is None:
            raise AssessmentProgressError("The student is outside your named progress scope.")
        if not CourseMembership.objects.filter(
            course_id=class_id, user_id=user.pk, role=CourseMembership.Role.STUDENT
        ).exists():
            raise AssessmentProgressError("The student is outside your named progress scope.")
    grades = {
        grade.attempt_id: grade
        for grade in AssessmentAttemptGrade.objects.filter(attempt_id__in=[attempt.pk for attempt in attempts])
    }
    attempt_rows = [_attempt_payload(attempt, grades) for attempt in attempts]
    course_ids = {run.course_id for run in runs if run.course_id is not None}
    participation = []
    participants = Participant.objects.filter(
        user_id=user.pk, is_test=False, session__course_id__in=course_ids
    ).select_related("session").order_by("-joined_at", "-id")
    for participant in participants:
        activity_count = Submission.objects.filter(participant=participant, is_stale=False).count()
        participation.append(
            {
                "session_id": participant.session_id,
                "session_title": participant.session.title,
                "session_status": participant.session.status,
                "participant_id": participant.id,
                "admission_state": participant.admission_state,
                "joined_at": participant.joined_at.isoformat(),
                "last_seen_at": participant.last_seen_at.isoformat() if participant.last_seen_at else None,
                "activity_count": activity_count,
            }
        )
    statuses = [row["progress_status"] for row in attempt_rows]
    return {
        "student": {"id": user.pk, "username": _username(user)},
        "summary": {
            "attempt_count": len(attempt_rows),
            "in_progress": statuses.count("in_progress"),
            "submitted": sum(status in {"submitted", "graded", "pending_manual", "ungraded"} for status in statuses),
            "graded": statuses.count("graded"),
            "pending_manual": statuses.count("pending_manual"),
            "ungraded": statuses.count("ungraded"),
        },
        "attempts": attempt_rows,
        "participation": participation,
    }


__all__ = [
    "AssessmentProgressError",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "PROGRESS_STATUSES",
    "can_read_run_progress",
    "get_student_overview",
    "list_run_progress",
]
