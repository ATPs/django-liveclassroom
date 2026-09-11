"""Automatic grading of immutable submitted assessment attempts."""

from decimal import Decimal
from io import StringIO
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from liveclassroom.models import (
    AssessmentAttemptGrade,
    AssessmentGradeDecision,
    AssessmentItemGrade,
)
from liveclassroom.services.assessment_grading import (
    AssessmentGradingError,
    grade_pending_attempts,
    grade_submitted_attempt,
    score_retained_item,
)
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempt_submission import submit_attempt
from liveclassroom.services.attempts import save_attempt_answer, start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition


def _payload(type_key, definition, points="1"):
    return {"type_key": type_key, "possible_points": points, "definition": definition}


@pytest.mark.parametrize(
    ("type_key", "definition", "answer", "expected"),
    [
        (
            "liveclassroom.single_choice",
            {"prompt": "Pick", "options": [{"id": "A", "text": "One"}], "answer": "A"},
            {"choice": "A"},
            ("graded", Decimal("1"), Decimal("3.00")),
        ),
        (
            "liveclassroom.multiple_choice",
            {
                "prompt": "Pick",
                "options": [{"id": "A", "text": "One"}, {"id": "B", "text": "Two"}],
                "answer": ["A", "B"],
                "partial_credit": True,
            },
            {"choices": ["A"]},
            ("graded", Decimal("0.5"), Decimal("1.50")),
        ),
        (
            "liveclassroom.numeric",
            {"prompt": "Value", "answer": 10, "tolerance": "0.1"},
            {"value": "10.1"},
            ("graded", Decimal("1"), Decimal("3.00")),
        ),
        (
            "liveclassroom.short_text",
            {"prompt": "Name", "answer": "RNA"},
            {"text": "rna"},
            ("graded", Decimal("1"), Decimal("3.00")),
        ),
    ],
)
def test_score_retained_item_uses_registry_and_decimal_scaling(type_key, definition, answer, expected):
    status, score, points = expected
    result = score_retained_item(
        _payload(type_key, definition, "3" if type_key != "liveclassroom.numeric" else "3"), answer
    )
    assert (result["status"], result["normalized_score"], result["awarded_points"]) == (
        status,
        score,
        points,
    )


def test_score_retained_item_numeric_tolerance_boundaries_and_unanswered_zero():
    payload = _payload("liveclassroom.numeric", {"prompt": "Value", "answer": 10, "tolerance": "0.1"}, "3")
    assert score_retained_item(payload, {"value": "10.1"})["normalized_score"] == Decimal("1")
    assert score_retained_item(payload, {"value": "10.1001"})["normalized_score"] == Decimal("0")
    zero_key = _payload("liveclassroom.numeric", {"prompt": "Value", "answer": 0}, "2")
    result = score_retained_item(zero_key, None)
    assert result["status"] == "graded"
    assert result["normalized_score"] == Decimal("0")
    assert result["awarded_points"] == Decimal("0.00")


def test_missing_key_is_ungraded_and_malformed_saved_answer_is_error():
    no_key = score_retained_item(_payload("liveclassroom.short_text", {"prompt": "Name"}, "2"), None)
    assert no_key["status"] == "ungraded"
    assert no_key["normalized_score"] is None
    assert no_key["awarded_points"] is None
    malformed = score_retained_item(
        _payload("liveclassroom.numeric", {"prompt": "Value", "answer": 10}, "2"), {"value": "NaN"}
    )
    assert malformed["status"] == "error"
    assert malformed["diagnostic_code"] == "invalid_saved_answer"
    missing = score_retained_item(
        _payload("vendor.missing", {"prompt": "Value", "answer": "x"}, "2"), {"value": "x"}
    )
    assert missing["status"] == "error"
    assert missing["diagnostic_code"] == "missing_grader"


def test_score_retained_item_rejects_out_of_range_plugin_score(monkeypatch):
    from liveclassroom.registry import ActivityType, activity_registry

    key = "vendor.bad_grader"
    activity_registry.register(
        ActivityType(
            key,
            validate_definition=lambda value: value,
            score_submission=lambda answer, definition: {"score": 2},
        ),
        replace=True,
    )
    try:
        result = score_retained_item(_payload(key, {"answer": "yes"}, "1"), {"value": "yes"})
    finally:
        activity_registry.unregister(key)
    assert result["status"] == "error"
    assert result["diagnostic_code"] == "invalid_saved_answer"


def _attempt(owner, learner, *, type_key="liveclassroom.single_choice", definition=None, points="2"):
    definition = definition or {
        "prompt": "Pick one",
        "options": [{"id": "A", "text": "One"}, {"id": "B", "text": "Two"}],
        "answer": "A",
    }
    source_key = type_key.removeprefix("liveclassroom.")
    question = create_activity_definition(
        owner=owner,
        title="Grade question",
        type_key=source_key,
        definition=definition,
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Grade assessment",
            "settings": {"max_attempts": 1, "audience": "authenticated_link"},
            "items": [{"revision_id": question.current_revision_id, "points": points}],
        },
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    return start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())[0]


@pytest.mark.django_db
def test_submitted_attempt_is_graded_once_and_decision_is_append_only():
    users = get_user_model()
    owner = users.objects.create_user(username="grade-owner")
    learner = users.objects.create_user(username="grade-learner")
    attempt = _attempt(owner, learner)
    item = attempt.items.get()
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"choice": "A"},
        expected_version=0,
        request_id=uuid4(),
    )
    with TestCase.captureOnCommitCallbacks(execute=True):
        submit_attempt(actor=learner, attempt=attempt, request_id=uuid4(), expected_versions={str(item.key): 1})
    assert AssessmentAttemptGrade.objects.filter(attempt=attempt).exists()
    first = grade_submitted_attempt(attempt=attempt)
    second = grade_submitted_attempt(attempt=attempt)
    assert first.pk == second.pk
    assert first.status == "graded"
    assert first.awarded_points == Decimal("2.00")
    assert AssessmentItemGrade.objects.filter(item=item).count() == 1
    assert AssessmentGradeDecision.objects.filter(attempt=attempt, item=item).count() == 1


@pytest.mark.django_db
def test_unresolved_items_keep_aggregate_pending_without_failing_score():
    users = get_user_model()
    owner = users.objects.create_user(username="pending-owner")
    learner = users.objects.create_user(username="pending-learner")
    attempt = _attempt(
        owner,
        learner,
        type_key="liveclassroom.short_text",
        definition={"prompt": "Name"},
        points="3",
    )
    submit_attempt(actor=learner, attempt=attempt, request_id=uuid4())
    aggregate = grade_submitted_attempt(attempt=attempt)
    item_grade = attempt.items.get().grade
    assert item_grade.status == "ungraded"
    assert aggregate.status == "pending"
    assert aggregate.ungraded_count == 1
    assert aggregate.awarded_points == Decimal("0.00")


@pytest.mark.django_db
def test_only_submitted_attempts_are_gradable():
    users = get_user_model()
    owner = users.objects.create_user(username="open-grade-owner")
    learner = users.objects.create_user(username="open-grade-learner")
    attempt = _attempt(owner, learner)
    with pytest.raises(AssessmentGradingError, match="submitted"):
        grade_submitted_attempt(attempt=attempt)


@pytest.mark.django_db
def test_submission_failure_is_recoverable_by_bounded_command(monkeypatch):
    users = get_user_model()
    owner = users.objects.create_user(username="recovery-owner")
    learner = users.objects.create_user(username="recovery-learner")
    attempt = _attempt(owner, learner)
    import liveclassroom.services.assessment_grading as grading_module

    def fail_once(*args, **kwargs):
        raise RuntimeError("temporary scorer failure")

    monkeypatch.setattr(grading_module, "grade_submitted_attempt", fail_once)
    with TestCase.captureOnCommitCallbacks(execute=True):
        submit_attempt(actor=learner, attempt=attempt, request_id=uuid4())
    assert not AssessmentAttemptGrade.objects.filter(attempt=attempt).exists()
    monkeypatch.setattr(grading_module, "grade_submitted_attempt", grade_submitted_attempt)
    output = StringIO()
    call_command("grade_pending_attempts", "--limit", "500", stdout=output)
    assert "graded=1" in output.getvalue()
    assert AssessmentGradeDecision.objects.filter(attempt=attempt).count() == 1
    repeat = grade_pending_attempts(limit=500)
    assert repeat["already_graded"] == 1
    assert AssessmentGradeDecision.objects.filter(attempt=attempt).count() == 1
