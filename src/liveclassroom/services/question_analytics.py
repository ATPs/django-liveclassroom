"""Permission-scoped analytics for retained assessment questions.

Question analytics deliberately reads the immutable attempt-item manifest.  A
definition can be edited after a run is published, and a question-bank pool
can assign only a subset of its candidates, so neither the current definition
nor the run roster is a suitable denominator.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.db.models import Prefetch

from liveclassroom.models import (
    AnswerRevision,
    AssessmentAttempt,
    AssessmentAttemptItem,
    AssessmentItemGrade,
    AssessmentRun,
    Course,
    CourseMembership,
    Participant,
)

from .classroom import ClassroomError
from .manual_grading import can_grade_attempt
from .permissions import can_teach

POINT_QUANTUM = Decimal("0.01")
RATIO_QUANTUM = Decimal("0.0001")
STAFF_ROLES = (CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT)


class QuestionAnalyticsError(ClassroomError):
    """Analytics are unavailable or outside the actor's staff scope."""


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _decimal_text(value: Decimal | None, *, quantum: Decimal = POINT_QUANTUM) -> str | None:
    if value is None:
        return None
    return format(value.quantize(quantum, rounding=ROUND_HALF_UP), "f")


def _percent(numerator: int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    return _decimal_text(Decimal(numerator) * Decimal("100") / Decimal(denominator))


def _ratio(numerator: Decimal, denominator: Decimal) -> str | None:
    if denominator <= 0:
        return None
    return _decimal_text(numerator / denominator, quantum=RATIO_QUANTUM)


def _json_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _canonical_question(value: Any) -> Any:
    """Canonicalize display-only option ordering for a retained fingerprint."""
    if isinstance(value, dict):
        output = {key: _canonical_question(child) for key, child in value.items()}
        options = output.get("options")
        if isinstance(options, list) and all(isinstance(option, dict) and "id" in option for option in options):
            output["options"] = sorted(options, key=lambda option: str(option["id"]))
        return output
    if isinstance(value, list):
        return [_canonical_question(child) for child in value]
    return value


def _run(value: AssessmentRun | int | str) -> AssessmentRun:
    if isinstance(value, AssessmentRun):
        return value
    query = AssessmentRun.objects
    try:
        if isinstance(value, int) and not isinstance(value, bool):
            return query.get(pk=value)
        return query.get(public_id=value)
    except (AssessmentRun.DoesNotExist, ValueError, TypeError) as exc:
        raise QuestionAnalyticsError("The selected assessment run was not found.") from exc


def _course(value: Course | int) -> Course:
    if isinstance(value, Course):
        return value
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise QuestionAnalyticsError("class_id must be a positive integer.")
    try:
        return Course.objects.get(pk=value)
    except Course.DoesNotExist as exc:
        raise QuestionAnalyticsError("The selected class was not found.") from exc


def _can_read_run(actor, run: AssessmentRun) -> bool:
    if not getattr(actor, "is_authenticated", False) or not can_teach(actor):
        return False
    from .assessment_progress import can_read_run_progress

    return can_read_run_progress(actor, run)


def _authorized_run(actor, run: AssessmentRun) -> None:
    if not _can_read_run(actor, run):
        raise QuestionAnalyticsError("You do not have permission to view question analytics.")


def _can_view_named_responses(actor, run: AssessmentRun) -> bool:
    """Require grading authorization for every concrete named attempt.

    Assessment runs are not classroom sessions, so a run identifier must never
    be passed to the session-oriented named-response host hook.
    """
    attempts = AssessmentAttempt.objects.filter(run=run).only("id", "run_id")
    return all(can_grade_attempt(actor, attempt) for attempt in attempts)


def _test_user_ids(run: AssessmentRun) -> set[int]:
    query = Participant.objects.filter(is_test=True, user_id__isnull=False)
    if run.course_id is not None:
        query = query.filter(session__course_id=run.course_id)
    else:
        # A link-only run has no class scope.  There is no safe way to infer
        # which test account was intended for this run, so do not guess from
        # unrelated classroom sessions.
        return set()
    return set(query.values_list("user_id", flat=True))


def _attempt_sort(attempt: AssessmentAttempt) -> tuple:
    return (
        attempt.status == AssessmentAttempt.Status.SUBMITTED,
        attempt.submitted_at is not None,
        attempt.submitted_at or attempt.started_at,
        attempt.attempt_number,
        attempt.pk,
    )


def _selected_attempts(attempts: Iterable[AssessmentAttempt]) -> list[AssessmentAttempt]:
    """Use the latest submitted attempt, retaining an active attempt if none submitted."""
    by_user: dict[int, list[AssessmentAttempt]] = defaultdict(list)
    for attempt in attempts:
        by_user[attempt.user_id].append(attempt)
    selected = []
    for rows in by_user.values():
        submitted = [row for row in rows if row.status == AssessmentAttempt.Status.SUBMITTED]
        selected.append(max(submitted or rows, key=_attempt_sort))
    return sorted(selected, key=lambda row: (row.user_id, row.pk))


def _latest_answer(item: AssessmentAttemptItem) -> AnswerRevision | None:
    cached = getattr(item, "_prefetched_objects_cache", {}).get("answer_revisions")
    if cached is not None:
        return cached[0] if cached else None
    return item.answer_revisions.order_by("-version").first()


def _item_question(item: AssessmentAttemptItem) -> dict[str, Any]:
    manifest = item.manifest if isinstance(item.manifest, dict) else {}
    payload = manifest.get("payload", manifest.get("definition", {}))
    payload = deepcopy(payload) if isinstance(payload, dict) else {}
    metadata = manifest.get("metadata", {})
    metadata = deepcopy(metadata) if isinstance(metadata, dict) else {}
    type_key = manifest.get("type_key", "")
    revision_id = manifest.get("revision_id")
    revision = manifest.get("revision")
    fingerprint = _json_fingerprint(
        _canonical_question(
            {
                "type_key": type_key,
                "schema_version": manifest.get("schema_version"),
                "payload": payload,
                "metadata": metadata,
            }
        )
    )
    identity = (
        f"revision:{revision_id}:fingerprint:{fingerprint}"
        if revision_id is not None
        else f"fingerprint:{fingerprint}"
    )
    return {
        "identity": identity,
        "revision_id": revision_id,
        "revision": revision,
        "definition_id": manifest.get("definition_id"),
        "fingerprint": fingerprint,
        "type_key": type_key,
        "schema_version": manifest.get("schema_version"),
        "payload": payload,
        "metadata": metadata,
        "points": _decimal(item.points) or _decimal(manifest.get("points")) or Decimal("0"),
    }


def _answer_selections(answer: Any) -> list[str]:
    if not isinstance(answer, dict):
        return []
    choices = answer.get("choices")
    if isinstance(choices, (list, tuple, set)):
        return [str(value) for value in choices if value is not None]
    choice = answer.get("choice")
    if choice is not None and choice != "":
        return [str(choice)]
    # A few host activity adapters use ``selected`` for a single or multiple
    # choice response.  It is safe to interpret it only as option IDs here.
    selected = answer.get("selected")
    if isinstance(selected, (list, tuple, set)):
        return [str(value) for value in selected if value is not None]
    if selected not in (None, ""):
        return [str(selected)]
    return []


def _answer_is_present(answer: AnswerRevision | None) -> bool:
    return answer is not None


def _answer_key(payload: dict[str, Any]) -> set[str]:
    value = payload.get("answer", payload.get("correct_answer"))
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value}
    if value is None:
        return set()
    return {str(value)}


def _options(payload: dict[str, Any]) -> list[dict[str, Any]]:
    options = payload.get("options")
    if not isinstance(options, list):
        return []
    rows = []
    for option in options:
        if not isinstance(option, dict) or option.get("id") is None:
            continue
        rows.append({"id": str(option["id"]), "text": str(option.get("text", ""))})
    return rows


def _named_payload(
    item_row: dict[str, Any], answer: AnswerRevision | None, attempt: AssessmentAttempt
) -> dict[str, Any]:
    return {
        "student_id": attempt.user_id,
        "student_username": attempt.user.get_username() if hasattr(attempt.user, "get_username") else str(attempt.user),
        "item_key": str(item_row["item"].key),
        "answer": deepcopy(answer.answer) if answer is not None else None,
        "answered": _answer_is_present(answer),
        "attempt_id": str(attempt.public_id),
    }


def _empty_group(run: AssessmentRun, question: dict[str, Any]) -> dict[str, Any]:
    payload = question["payload"]
    options = [
        {
            "id": option["id"],
            "text": option["text"],
            "selection_count": 0,
            "share_selecting": "0.00",
        }
        for option in _options(payload)
    ]
    return {
        "key": f"run:{run.public_id}:{question['identity']}",
        "run_id": str(run.public_id),
        "run_date": run.created_at.date().isoformat(),
        "question_revision_id": question["revision_id"],
        "revision_id": question["revision_id"],
        "revision": question["revision"],
        "definition_id": question["definition_id"],
        "fingerprint": question["fingerprint"],
        "type_key": question["type_key"],
        "schema_version": question["schema_version"],
        "prompt": payload.get("prompt", payload.get("title", "")),
        "metadata": {
            "difficulty": question["metadata"].get("difficulty"),
            "tags": deepcopy(question["metadata"].get("tags", [])),
        },
        "author_difficulty": question["metadata"].get("difficulty"),
        "possible_points": _decimal_text(question["points"]),
        "assigned": 0,
        "answered": 0,
        "fully_graded": 0,
        "pending": 0,
        "ungraded": 0,
        "error": 0,
        "graded_sample_count": 0,
        "mean_normalized_score": None,
        "full_correct_count": 0,
        "full_credit_rate": None,
        "observed_difficulty": {
            "mean_normalized_score": None,
            "full_credit_rate": None,
            "sample_count": 0,
        },
        "options": options,
        "option_selection_counts": {},
        "common_wrong_options": [],
        "participation_trend": {
            "run_id": str(run.public_id),
            "date": run.created_at.date().isoformat(),
            "assigned": 0,
            "answered": 0,
            "submitted": 0,
        },
    }


def _finalize_group(group: dict[str, Any], wrong_counts: dict[str, int], assigned: int) -> None:
    group["option_selection_counts"] = {
        row["id"]: row["selection_count"] for row in group["options"] if row["selection_count"]
    }
    group["common_wrong_options"] = [
        {
            "id": option["id"],
            "text": option["text"],
            "count": wrong_counts.get(option["id"], 0),
            "share_selecting": _percent(wrong_counts.get(option["id"], 0), assigned),
        }
        for option in group["options"]
        if wrong_counts.get(option["id"], 0)
    ]
    group["common_wrong_options"].sort(key=lambda row: (-row["count"], row["id"]))


def _build_run_payload(actor, run: AssessmentRun, *, include_named: bool = False) -> dict[str, Any]:
    test_ids = _test_user_ids(run)
    attempts = list(
        AssessmentAttempt.objects.filter(run=run)
        .exclude(user_id__in=test_ids)
        .select_related("user")
        .prefetch_related(
            Prefetch("items", queryset=AssessmentAttemptItem.objects.order_by("position", "id").prefetch_related(
                Prefetch("answer_revisions", queryset=AnswerRevision.objects.order_by("-version")),
                "grade",
            ))
        )
        .order_by("user_id", "id")
    )
    selected = _selected_attempts(attempts)
    groups: dict[str, dict[str, Any]] = {}
    wrong_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    score_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    score_counts: dict[str, int] = defaultdict(int)
    named_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    participation: dict[str, dict[str, int]] = defaultdict(lambda: {"assigned": 0, "answered": 0, "submitted": 0})
    for attempt in selected:
        for item in attempt.items.all():
            question = _item_question(item)
            group = groups.setdefault(question["identity"], _empty_group(run, question))
            group["assigned"] += 1
            group["participation_trend"]["assigned"] += 1
            participation[question["identity"]]["assigned"] += 1
            answer = _latest_answer(item)
            answered = _answer_is_present(answer)
            if answered:
                group["answered"] += 1
                group["participation_trend"]["answered"] += 1
                participation[question["identity"]]["answered"] += 1
            if attempt.status == AssessmentAttempt.Status.SUBMITTED:
                group["participation_trend"]["submitted"] += 1
                participation[question["identity"]]["submitted"] += 1
            try:
                grade = item.grade
            except AssessmentItemGrade.DoesNotExist:
                grade = None
            status = grade.status if grade is not None else (
                "pending" if attempt.status == AssessmentAttempt.Status.SUBMITTED else "ungraded"
            )
            if status == AssessmentItemGrade.Status.GRADED and grade.normalized_score is not None:
                normalized = _decimal(grade.normalized_score)
                if normalized is not None:
                    group["fully_graded"] += 1
                    group["graded_sample_count"] += 1
                    score_totals[question["identity"]] += normalized
                    score_counts[question["identity"]] += 1
                    if normalized >= Decimal("1"):
                        group["full_correct_count"] += 1
            elif status == AssessmentItemGrade.Status.PENDING:
                group["pending"] += 1
            elif status in {AssessmentItemGrade.Status.UNGRADED, AssessmentItemGrade.Status.ERROR}:
                group["ungraded"] += 1
                if status == AssessmentItemGrade.Status.ERROR:
                    group["error"] += 1
            selections = _answer_selections(answer.answer if answer is not None else None)
            option_rows = {option["id"]: option for option in group["options"]}
            correct = _answer_key(question["payload"])
            for selection in selections:
                if selection in option_rows:
                    option_rows[selection]["selection_count"] += 1
                if selection not in correct and selection in option_rows:
                    wrong_counts[question["identity"]][selection] += 1
            if include_named:
                named_rows[question["identity"]].append(_named_payload({"item": item}, answer, attempt))

    for identity, group in groups.items():
        count = score_counts[identity]
        total = score_totals[identity]
        group["mean_normalized_score"] = _ratio(total, Decimal(count)) if count else None
        group["full_credit_rate"] = _percent(group["full_correct_count"], count) if count else None
        group["observed_difficulty"] = {
            "mean_normalized_score": group["mean_normalized_score"],
            "full_credit_rate": group["full_credit_rate"],
            "sample_count": count,
        }
        _finalize_group(group, wrong_counts[identity], group["assigned"])
        if include_named:
            group["named_responses"] = named_rows[identity]
    groups_list = sorted(
        groups.values(),
        key=lambda row: (row["revision_id"] is None, str(row["revision_id"]), row["fingerprint"]),
    )
    assigned = sum(row["assigned"] for row in groups_list)
    answered = sum(row["answered"] for row in groups_list)
    submitted_users = sum(1 for attempt in selected if attempt.status == AssessmentAttempt.Status.SUBMITTED)
    return {
        "protocol_version": 1,
        "run": {
            "id": run.id,
            "public_id": str(run.public_id),
            "title": run.title,
            "course_id": run.course_id,
            "date": run.created_at.date().isoformat(),
        },
        "denominators": {
            "assigned_items": assigned,
            "assigned_students": len(selected),
            "answered_items": answered,
            "submitted_students": submitted_users,
            "test_participants_excluded": len(test_ids),
        },
        "questions": groups_list,
        "participation_trends": [
            {
                "run_id": str(run.public_id),
                "date": run.created_at.date().isoformat(),
                "assigned_students": len(selected),
                "assigned_items": assigned,
                "answered_items": answered,
                "submitted_students": submitted_users,
            }
        ],
    }


def question_analytics(actor, run: AssessmentRun | int | str, *, include_named: bool = False) -> dict[str, Any]:
    """Return aggregate question outcomes for one retained assessment run."""
    if not isinstance(include_named, bool):
        raise QuestionAnalyticsError("include_named must be a boolean.")
    selected_run = _run(run)
    _authorized_run(actor, selected_run)
    if include_named and not _can_view_named_responses(actor, selected_run):
        raise QuestionAnalyticsError("You do not have permission to view named responses.")
    return _build_run_payload(actor, selected_run, include_named=include_named)


def course_question_analytics(actor, course: Course | int, *, include_named: bool = False) -> dict[str, Any]:
    """Return separate run-context rows and trends for one authorized class."""
    selected_course = _course(course)
    if not getattr(actor, "is_authenticated", False) or not can_teach(actor):
        raise QuestionAnalyticsError("You do not have permission to view question analytics.")
    if not (
        getattr(actor, "is_superuser", False)
        or selected_course.created_by_id == actor.pk
        or CourseMembership.objects.filter(course=selected_course, user=actor, role__in=STAFF_ROLES).exists()
    ):
        raise QuestionAnalyticsError("You do not have permission to view question analytics.")
    runs = list(AssessmentRun.objects.filter(course=selected_course).order_by("created_at", "id"))
    if any(not _can_read_run(actor, run) for run in runs):
        raise QuestionAnalyticsError("You do not have permission to view question analytics.")
    if include_named and any(not _can_view_named_responses(actor, run) for run in runs):
        raise QuestionAnalyticsError("You do not have permission to view named responses.")
    payloads = [_build_run_payload(actor, run, include_named=include_named) for run in runs]
    questions = [question for payload in payloads for question in payload["questions"]]
    trends = [trend for payload in payloads for trend in payload["participation_trends"]]
    totals = {
        key: sum(payload["denominators"][key] for payload in payloads)
        for key in ("assigned_items", "answered_items", "submitted_students")
    }
    totals["assigned_students"] = sum(payload["denominators"]["assigned_students"] for payload in payloads)
    totals["test_participants_excluded"] = sum(
        payload["denominators"]["test_participants_excluded"] for payload in payloads
    )
    return {
        "protocol_version": 1,
        "scope": {"kind": "class", "id": selected_course.pk, "title": selected_course.title},
        "denominators": totals,
        "questions": questions,
        "participation_trends": trends,
        "runs": [payload["run"] for payload in payloads],
    }


# Descriptive aliases keep this service easy to discover for host integrations.
assessment_question_analytics = question_analytics
run_question_analytics = question_analytics
class_question_analytics = course_question_analytics


__all__ = [
    "QuestionAnalyticsError",
    "assessment_question_analytics",
    "class_question_analytics",
    "course_question_analytics",
    "question_analytics",
    "run_question_analytics",
]
