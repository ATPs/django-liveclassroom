"""Authorized CSV and JSON projections for assessment results.

The projection is assembled from retained attempts, answer revisions, current
grades, and grade decisions in one transaction.  CSV is intentionally a
small selected-result view; JSON retains the complete authorized attempt
history without copying private question manifests or answer keys.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC
from decimal import Decimal
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from liveclassroom.models import (
    AnswerRevision,
    AssessmentAttempt,
    AssessmentAttemptGrade,
    AssessmentAttemptItem,
    AssessmentGradeDecision,
    AssessmentItemGrade,
    AssessmentRun,
    Course,
    CourseMembership,
    Participant,
)

from .classroom import ClassroomError
from .manual_grading import can_grade_attempt
from .permissions import can_teach
from .result_release import student_result_payload

STAFF_ROLES = (CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT)
SCHEMA_VERSION = 1


class AssessmentExportError(ClassroomError):
    """An export request is malformed or outside its authorization scope."""


class _Echo:
    def write(self, value: str) -> str:
        return value


def _json(value: Any) -> str:
    return json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _utc(value) -> str | None:
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    try:
        return format(Decimal(str(value)), "f")
    except Exception:
        return str(value)


def _text(value: Any) -> str:
    """Neutralize spreadsheet formulas while preserving ordinary Unicode text."""
    if value is None:
        return ""
    result = str(value)
    stripped = result.lstrip()
    if stripped and stripped[0] in "=+-@":
        return "'" + result
    return result


def _run(value: AssessmentRun | int | str) -> AssessmentRun:
    if isinstance(value, AssessmentRun):
        return value
    try:
        if isinstance(value, int) and not isinstance(value, bool):
            return AssessmentRun.objects.select_related("course").get(pk=value)
        return AssessmentRun.objects.select_related("course").get(public_id=value)
    except (AssessmentRun.DoesNotExist, ValueError, TypeError) as exc:
        raise AssessmentExportError("The selected assessment run was not found.") from exc


def _course(value: Course | int) -> Course:
    if isinstance(value, Course):
        return value
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AssessmentExportError("class_id must be a positive integer.")
    try:
        return Course.objects.get(pk=value)
    except Course.DoesNotExist as exc:
        raise AssessmentExportError("The selected class was not found.") from exc


def _test_ids(runs: Iterable[AssessmentRun]) -> set[int]:
    course_ids = {run.course_id for run in runs if run.course_id is not None}
    if not course_ids:
        return set()
    return set(
        Participant.objects.filter(session__course_id__in=course_ids, is_test=True, user_id__isnull=False).values_list(
            "user_id", flat=True
        )
    )


def _staff_can_export_run(actor, run: AssessmentRun) -> bool:
    """Export uses the explicit named-result/grading capability."""
    return can_grade_attempt(actor, AssessmentAttempt(run=run))


def _authorize_teacher(actor, runs: list[AssessmentRun]) -> None:
    if not getattr(actor, "is_authenticated", False) or not can_teach(actor):
        raise AssessmentExportError("Teacher result export access is required.")
    if any(not _staff_can_export_run(actor, run) for run in runs):
        raise AssessmentExportError("You do not have permission to export these results.")


def _attempt_queryset(runs: list[AssessmentRun], test_ids: set[int]):
    return (
        AssessmentAttempt.objects.filter(run__in=runs)
        .exclude(user_id__in=test_ids)
        .select_related("run", "user")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=AssessmentAttemptItem.objects.order_by("position", "id").prefetch_related(
                    Prefetch("answer_revisions", queryset=AnswerRevision.objects.order_by("version", "id")),
                    Prefetch("grade_decisions", queryset=AssessmentGradeDecision.objects.order_by("created_at", "id")),
                    "grade",
                ),
            ),
            "grade",
        )
        .order_by("run_id", "user_id", "attempt_number", "id")
    )


def _grade(item: AssessmentAttemptItem) -> AssessmentItemGrade | None:
    try:
        return item.grade
    except AssessmentItemGrade.DoesNotExist:
        return None


def _attempt_grade(attempt: AssessmentAttempt) -> AssessmentAttemptGrade | None:
    try:
        return attempt.grade
    except AssessmentAttemptGrade.DoesNotExist:
        return None


def _latest_submitted(attempts: Iterable[AssessmentAttempt]) -> list[AssessmentAttempt]:
    by_student: dict[tuple[int, int], list[AssessmentAttempt]] = defaultdict(list)
    for attempt in attempts:
        if attempt.status == AssessmentAttempt.Status.SUBMITTED:
            by_student[(attempt.run_id, attempt.user_id)].append(attempt)
    return [
        max(
            rows,
            key=lambda row: (
                row.submitted_at is not None,
                row.submitted_at.timestamp() if row.submitted_at is not None else 0,
                row.attempt_number,
                row.pk,
            ),
        )
        for rows in by_student.values()
    ]


def _item_type(item: AssessmentAttemptItem) -> str | None:
    manifest = item.manifest if isinstance(item.manifest, dict) else {}
    value = manifest.get("type_key")
    return value if isinstance(value, str) else None


def _item_row(item: AssessmentAttemptItem, *, include_answer: bool = True) -> dict[str, Any]:
    grade = _grade(item)
    revisions = list(item.answer_revisions.all())
    decisions = list(item.grade_decisions.all())
    result: dict[str, Any] = {
        "item_key": str(item.key),
        "position": item.position,
        "type_key": _item_type(item),
        "possible_points": _decimal(item.points),
        "answer_revisions": [
            {
                "version": row.version,
                "answer": row.answer if include_answer else None,
                "actor_id": row.actor_id,
                "saved_at": _utc(row.saved_at),
            }
            for row in revisions
        ],
        "current_grade": None,
        "grade_decisions": [
            {
                "status": row.status,
                "normalized_score": _decimal(row.normalized_score),
                "awarded_points": _decimal(row.awarded_points),
                "source": row.source,
                "rule_version": row.rule_version,
                "comment": row.comment,
                "actor_id": row.actor_id,
                "reason": row.reason,
                "created_at": _utc(row.created_at),
            }
            for row in decisions
        ],
    }
    if grade is not None:
        result["current_grade"] = {
            "status": grade.status,
            "normalized_score": _decimal(grade.normalized_score),
            "awarded_points": _decimal(grade.awarded_points),
            "possible_points": _decimal(grade.possible_points),
            "source": grade.source,
            "rule_version": grade.rule_version,
            "feedback": grade.comment,
            "graded_at": _utc(grade.graded_at),
        }
    if include_answer:
        result["answer"] = revisions[-1].answer if revisions else None
    return result


def _attempt_row(attempt: AssessmentAttempt, *, details: bool = True) -> dict[str, Any]:
    grade = _attempt_grade(attempt)
    result: dict[str, Any] = {
        "attempt_id": str(attempt.public_id),
        "run_id": str(attempt.run.public_id),
        "run_title": attempt.run.title,
        "student_id": attempt.user_id,
        "student_identifier": attempt.user.get_username()
        if hasattr(attempt.user, "get_username")
        else str(attempt.user),
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "started_at": _utc(attempt.started_at),
        "submitted_at": _utc(attempt.submitted_at),
        "earned_points": _decimal(grade.awarded_points) if grade is not None else None,
        "possible_points": _decimal(grade.possible_points)
        if grade is not None
        else _decimal(sum((item.points for item in attempt.items.all()), Decimal("0"))),
        "pending_count": grade.pending_count if grade is not None else 0,
        "ungraded_count": grade.ungraded_count if grade is not None else 0,
        "error_count": grade.error_count if grade is not None else 0,
        "aggregate_grade": (
            {
                "status": grade.status,
                "awarded_points": _decimal(grade.awarded_points),
                "possible_points": _decimal(grade.possible_points),
                "graded_count": grade.graded_count,
                "pending_count": grade.pending_count,
                "ungraded_count": grade.ungraded_count,
                "error_count": grade.error_count,
                "updated_at": _utc(grade.updated_at),
            }
            if grade is not None
            else None
        ),
    }
    if details:
        result["items"] = [_item_row(item) for item in attempt.items.all()]
    return result


def _meta(*, scope: str, selection_rule: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": scope,
        "selection_rule": selection_rule,
        "exported_at": _utc(timezone.now()),
    }


@transaction.atomic
def teacher_result_projection(actor, runs: Iterable[AssessmentRun], *, details: bool = True) -> dict[str, Any]:
    """Build one consistent authorized teacher projection for requested runs."""
    selected_runs = list(runs)
    _authorize_teacher(actor, selected_runs)
    test_ids = _test_ids(selected_runs)
    attempts = list(_attempt_queryset(selected_runs, test_ids))
    return {
        "meta": _meta(
            scope="teacher",
            selection_rule=(
                "CSV selects latest submitted attempt per student and run; JSON retains all authorized attempts."
            ),
        ),
        "runs": [
            {
                "id": run.id,
                "public_id": str(run.public_id),
                "title": run.title,
                "course_id": run.course_id,
                "created_at": _utc(run.created_at),
            }
            for run in selected_runs
        ],
        "attempts": [_attempt_row(attempt, details=details) for attempt in attempts],
        "selected_attempts": [_attempt_row(attempt, details=details) for attempt in _latest_submitted(attempts)],
        "test_participants_excluded": len(test_ids),
    }


def teacher_run_export(actor, run: AssessmentRun | int | str, *, details: bool = True) -> dict[str, Any]:
    return teacher_result_projection(actor, [_run(run)], details=details)


def teacher_class_export(actor, course: Course | int, *, details: bool = True) -> dict[str, Any]:
    selected_course = _course(course)
    if not getattr(actor, "is_authenticated", False) or not can_teach(actor):
        raise AssessmentExportError("Teacher result export access is required.")
    if not (
        getattr(actor, "is_superuser", False)
        or selected_course.created_by_id == actor.pk
        or CourseMembership.objects.filter(course=selected_course, user=actor, role__in=STAFF_ROLES).exists()
    ):
        raise AssessmentExportError("You do not have permission to export this class.")
    runs = list(
        AssessmentRun.objects.filter(course=selected_course).select_related("course").order_by("created_at", "id")
    )
    return teacher_result_projection(actor, runs, details=details) | {
        "meta": _meta(
            scope="teacher-class",
            selection_rule=(
                "CSV selects latest submitted attempt per student and run; JSON retains all authorized attempts."
            ),
        ),
        "class": {"id": selected_course.id, "title": selected_course.title},
    }


def _csv_rows(projection: dict[str, Any], *, details: bool) -> Iterator[dict[str, Any]]:
    columns = (
        "run_title",
        "run_id",
        "student_identifier",
        "attempt_number",
        "status",
        "submitted_at",
        "earned_points",
        "possible_points",
        "pending_count",
        "ungraded_count",
    )
    detail_columns = columns + (
        "item_key",
        "item_type",
        "answer",
        "current_grade",
        "feedback",
    )
    for attempt in projection["selected_attempts"]:
        base = {
            "run_title": _text(attempt["run_title"]),
            "run_id": attempt["run_id"],
            "student_identifier": _text(attempt["student_identifier"]),
            "attempt_number": attempt["attempt_number"],
            "status": attempt["status"],
            "submitted_at": attempt["submitted_at"],
            "earned_points": attempt["earned_points"],
            "possible_points": attempt["possible_points"],
            "pending_count": attempt["pending_count"],
            "ungraded_count": attempt["ungraded_count"],
        }
        if not details:
            yield {key: base[key] for key in columns}
            continue
        items = attempt.get("items", [])
        if not items:
            yield {key: base[key] for key in detail_columns}
            continue
        for item in items:
            grade = item.get("current_grade") or {}
            yield {
                **base,
                "item_key": item["item_key"],
                "item_type": item["type_key"],
                "answer": _json(item.get("answer")),
                "current_grade": _json(grade) if grade else "",
                "feedback": _text(grade.get("feedback", "")),
            }


def teacher_csv_export(projection: dict[str, Any], *, details: bool = False) -> Iterator[str]:
    fields = [
        "run_title",
        "run_id",
        "student_identifier",
        "attempt_number",
        "status",
        "submitted_at",
        "earned_points",
        "possible_points",
        "pending_count",
        "ungraded_count",
    ]
    if details:
        fields.extend(["item_key", "item_type", "answer", "current_grade", "feedback"])
    writer = csv.DictWriter(_Echo(), fieldnames=fields, extrasaction="ignore")
    yield writer.writeheader()
    for row in _csv_rows(projection, details=details):
        yield writer.writerow(row)


def teacher_json_export(projection: dict[str, Any]) -> Iterator[str]:
    """Stream a complete JSON projection after authorization and consistency capture."""
    yield _json(projection)


def student_result_projection(actor, attempt: AssessmentAttempt | int | str) -> dict[str, Any]:
    """Return only dimensions released to the owner of one attempt."""
    if not getattr(actor, "is_authenticated", False):
        raise AssessmentExportError("Authentication required.")
    if isinstance(attempt, AssessmentAttempt):
        selected = attempt
    else:
        try:
            selected = AssessmentAttempt.objects.select_related("run", "user").get(public_id=attempt)
        except (AssessmentAttempt.DoesNotExist, ValueError, TypeError) as exc:
            raise AssessmentExportError("The assessment attempt was not found.") from exc
    if selected.user_id != actor.pk:
        raise AssessmentExportError("The assessment attempt was not found.")
    try:
        result = student_result_payload(attempt=selected)
    except ClassroomError as exc:
        raise AssessmentExportError(str(exc)) from exc
    return {
        "meta": _meta(
            scope="student", selection_rule="Only this authenticated student's attempt and released result dimensions."
        ),
        "attempt": result,
    }


def student_json_export(projection: dict[str, Any]) -> Iterator[str]:
    yield _json(projection)


def student_csv_export(projection: dict[str, Any]) -> Iterator[str]:
    result = projection["attempt"]
    fields = [
        "run_id",
        "attempt_number",
        "status",
        "submitted_at",
        "item_key",
        "item_type",
        "answer",
        "score",
        "explanation",
        "comment",
    ]
    writer = csv.DictWriter(_Echo(), fieldnames=fields)
    yield writer.writeheader()
    for item in result.get("items", []):
        yield writer.writerow(
            {
                "run_id": result["run_id"],
                "attempt_number": result["attempt_number"],
                "status": result["status"],
                "submitted_at": result["submitted_at"],
                "item_key": item.get("key"),
                "item_type": item.get("type_key"),
                "answer": _json(item.get("answer")) if "answer" in item else "",
                "score": _json(item.get("score")) if "score" in item else "",
                "explanation": _text(item.get("explanation", "")),
                "comment": _text(item.get("comment", "")),
            }
        )


__all__ = [
    "AssessmentExportError",
    "SCHEMA_VERSION",
    "student_csv_export",
    "student_json_export",
    "student_result_projection",
    "teacher_class_export",
    "teacher_csv_export",
    "teacher_json_export",
    "teacher_result_projection",
    "teacher_run_export",
]
