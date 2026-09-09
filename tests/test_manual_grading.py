"""Manual grading of submitted subjective assessment items."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from liveclassroom.models import (
    AssessmentAttemptGrade,
    AssessmentGradeDecision,
    AssessmentItemGrade,
)
from liveclassroom.services.assessment_grading import grade_submitted_attempt
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempt_submission import submit_attempt
from liveclassroom.services.attempts import save_attempt_answer, start_or_resume_attempt
from liveclassroom.services.classroom import ClassroomError, create_activity_definition
from liveclassroom.services.manual_grading import (
    ManualGradingError,
    list_manual_grading_items,
    save_manual_grade,
)


def _essay_attempt(*, points="4"):
    users = get_user_model()
    owner = users.objects.create_user(username=f"manual-owner-{uuid4().hex[:8]}")
    learner = users.objects.create_user(username=f"manual-learner-{uuid4().hex[:8]}")
    question = create_activity_definition(
        owner=owner,
        title="Essay question",
        type_key="essay",
        definition={"prompt": "Explain the result.\nUse evidence.", "max_length": 500},
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Essay assessment",
            "settings": {"max_attempts": 1, "audience": "authenticated_link"},
            "items": [{"revision_id": question.current_revision_id, "points": points}],
        },
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    attempt = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())[0]
    item = attempt.items.get()
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"text": "A considered answer.\nWith a second line."},
        expected_version=0,
        request_id=uuid4(),
    )
    submit_attempt(actor=learner, attempt=attempt, request_id=uuid4(), expected_versions={str(item.key): 1})
    grade_submitted_attempt(attempt=attempt)
    return owner, learner, run, attempt, item


@pytest.mark.django_db
def test_queue_returns_only_pending_manual_items_and_retains_prompt_and_answer():
    owner, learner, run, attempt, item = _essay_attempt()
    rows = list_manual_grading_items(owner, run_id=run.public_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["attempt_id"] == str(attempt.public_id)
    assert row["item_key"] == str(item.key)
    assert row["student_id"] == learner.pk
    assert row["student_username"] == learner.username
    assert row["prompt"] == "Explain the result.\nUse evidence."
    assert row["retained_prompt"] == row["prompt"]
    assert row["answer"] == {"text": "A considered answer.\nWith a second line."}
    assert row["possible_points"] == Decimal("4.000000")
    assert row["status"] == AssessmentItemGrade.Status.PENDING
    assert row["decision"]["normalized_score"] is None
    assert row["decision"]["awarded_points"] is None
    with pytest.raises(ManualGradingError, match="Teacher grading access"):
        list_manual_grading_items(learner, run_id=run.public_id)


@pytest.mark.django_db
def test_manual_grade_scales_decimal_points_preserves_answer_and_recomputes_total():
    owner, _learner, run, attempt, item = _essay_attempt()
    result = save_manual_grade(
        attempt_item=item,
        normalized_score=Decimal("0.75"),
        comment="Clear reasoning.",
        actor=owner,
        reason="Reviewed against the prompt.",
    )
    result.refresh_from_db()
    assert result.status == AssessmentItemGrade.Status.GRADED
    assert result.normalized_score == Decimal("0.7500000000")
    assert result.awarded_points == Decimal("3.00")
    assert result.retained_answer == {"text": "A considered answer.\nWith a second line."}
    assert result.comment == "Clear reasoning."
    aggregate = AssessmentAttemptGrade.objects.get(attempt=attempt)
    assert aggregate.status == AssessmentAttemptGrade.Status.GRADED
    assert aggregate.possible_points == Decimal("4.00")
    assert aggregate.awarded_points == Decimal("3.00")
    decisions = AssessmentGradeDecision.objects.filter(attempt=attempt, item=item).order_by("id")
    assert decisions.count() == 2
    manual = decisions.last()
    assert manual.source == "manual"
    assert manual.actor_id == owner.pk
    assert manual.reason == "Reviewed against the prompt."
    assert manual.comment == "Clear reasoning."
    assert manual.retained_answer == result.retained_answer
    assert list_manual_grading_items(owner, run_id=run.public_id) == []


@pytest.mark.django_db
def test_explicit_zero_is_valid_and_repeated_request_does_not_duplicate_decision():
    owner, _learner, _run, attempt, item = _essay_attempt(points="5")
    first = save_manual_grade(
        attempt_item=item,
        normalized_score=0,
        actor=owner,
        comment="No credit awarded.",
        reason="The response does not address the question.",
    )
    second = save_manual_grade(
        attempt_item=item,
        normalized_score=0,
        actor=owner,
        comment="No credit awarded.",
        reason="The response does not address the question.",
    )
    assert first.pk == second.pk
    assert AssessmentGradeDecision.objects.filter(attempt=attempt, item=item).count() == 2
    assert AssessmentAttemptGrade.objects.get(attempt=attempt).awarded_points == Decimal("0.00")


@pytest.mark.django_db
@pytest.mark.parametrize("score", [Decimal("-0.01"), Decimal("1.01")])
def test_manual_grade_rejects_out_of_range_scores(score):
    owner, _learner, _run, _attempt, item = _essay_attempt()
    with pytest.raises(ManualGradingError, match="between zero and one"):
        save_manual_grade(attempt_item=item, normalized_score=score, actor=owner, reason="Checked.")
    assert not AssessmentItemGrade.objects.filter(item=item, source="manual").exists()


@pytest.mark.django_db
def test_manual_grade_requires_reason_bounded_comment_and_authorized_staff():
    owner, learner, _run, _attempt, item = _essay_attempt()
    with pytest.raises(ManualGradingError, match="reason is required"):
        save_manual_grade(attempt_item=item, normalized_score="0.5", actor=owner, reason="  ")
    with pytest.raises(ManualGradingError, match="at most 4000"):
        save_manual_grade(
            attempt_item=item,
            normalized_score="0.5",
            actor=owner,
            reason="Checked.",
            comment="x" * 4001,
        )
    with pytest.raises(ManualGradingError, match="permission"):
        save_manual_grade(attempt_item=item, normalized_score="0.5", actor=learner, reason="Checked.")
    assert AssessmentGradeDecision.objects.filter(item=item, source="manual").count() == 0


@pytest.mark.django_db
def test_queue_excludes_objective_items_and_submitted_attempts_are_required():
    owner, learner, run, attempt, _item = _essay_attempt()
    assert list_manual_grading_items(owner, run_id=run.id)
    attempt.status = "in_progress"
    attempt.save(update_fields=["status"])
    with pytest.raises(ClassroomError, match="submitted"):
        grade_submitted_attempt(attempt=attempt)
    with pytest.raises(ManualGradingError, match="submitted"):
        save_manual_grade(
            attempt_item=attempt.items.get(), normalized_score="0.5", actor=owner, reason="Checked."
        )
    assert list_manual_grading_items(owner, run_id=run.id) == []
