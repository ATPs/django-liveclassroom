"""Audited item overrides and explicit objective regrading."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from liveclassroom.models import AssessmentGradeDecision, AssessmentItemGrade, GradingRuleRevision
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempt_submission import submit_attempt
from liveclassroom.services.attempts import save_attempt_answer, start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.grade_corrections import (
    GradeCorrectionError,
    override_item_grade,
    regrade_attempts,
)


def _attempt(*, type_key, definition, points="3"):
    users = get_user_model()
    owner = users.objects.create_user(username=f"correction-owner-{uuid4().hex[:8]}")
    learner = users.objects.create_user(username=f"correction-learner-{uuid4().hex[:8]}")
    question = create_activity_definition(
        owner=owner, title="Correction question", type_key=type_key, definition=definition
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Correction assessment",
            "settings": {"max_attempts": 1, "audience": "authenticated_link"},
            "items": [{"revision_id": question.current_revision_id, "points": points}],
        },
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    attempt = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())[0]
    return owner, learner, run, attempt, attempt.items.get()


def _submit(*, attempt, learner, item, answer):
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer=answer,
        expected_version=0,
        request_id=uuid4(),
    )
    submit_attempt(actor=learner, attempt=attempt, request_id=uuid4(), expected_versions={str(item.key): 1})


@pytest.mark.django_db
def test_override_appends_actor_reason_and_old_new_point_history():
    owner, learner, _run, attempt, item = _attempt(
        type_key="essay", definition={"prompt": "Explain.", "max_length": 500}, points="3"
    )
    _submit(attempt=attempt, learner=learner, item=item, answer={"text": "Answer"})
    current = override_item_grade(
        attempt_item=item,
        normalized_score=Decimal("0.5"),
        comment="Partial evidence.",
        actor=owner,
        reason="Reviewed with the marking guide.",
    )
    assert current.status == AssessmentItemGrade.Status.GRADED
    assert current.source == "override"
    assert current.awarded_points == Decimal("1.50")
    decisions = list(AssessmentGradeDecision.objects.filter(item=item).order_by("id"))
    assert len(decisions) == 2
    assert decisions[0].normalized_score is None
    assert decisions[0].awarded_points is None
    assert decisions[1].normalized_score == Decimal("0.5000000000")
    assert decisions[1].awarded_points == Decimal("1.50")
    assert decisions[1].source == "override"
    assert decisions[1].actor_id == owner.pk
    assert decisions[1].reason == "Reviewed with the marking guide."
    assert decisions[1].comment == "Partial evidence."
    assert attempt.items.get().manifest["payload"]["prompt"] == "Explain."


@pytest.mark.django_db
def test_override_repeated_identical_request_is_a_stable_read():
    owner, learner, _run, attempt, item = _attempt(
        type_key="essay", definition={"prompt": "Explain.", "max_length": 500}, points="3"
    )
    _submit(attempt=attempt, learner=learner, item=item, answer={"text": "Answer"})
    first = override_item_grade(
        attempt_item=item, normalized_score="0.8", actor=owner, reason="Checked."
    )
    second = override_item_grade(
        attempt_item=item, normalized_score="0.8", actor=owner, reason="Checked."
    )
    assert first.pk == second.pk
    assert AssessmentGradeDecision.objects.filter(item=item).count() == 2


@pytest.mark.django_db
def test_override_rejects_wrong_role_blank_reason_and_open_attempt():
    owner, learner, _run, attempt, item = _attempt(
        type_key="essay", definition={"prompt": "Explain.", "max_length": 500}
    )
    with pytest.raises(GradeCorrectionError, match="submitted"):
        override_item_grade(attempt_item=item, normalized_score="0.5", actor=owner, reason="Checked.")
    _submit(attempt=attempt, learner=learner, item=item, answer={"text": "Answer"})
    with pytest.raises(GradeCorrectionError, match="reason"):
        override_item_grade(attempt_item=item, normalized_score="0.5", actor=owner, reason="  ")
    with pytest.raises(GradeCorrectionError, match="permission"):
        override_item_grade(attempt_item=item, normalized_score="0.5", actor=learner, reason="Checked.")


@pytest.mark.django_db
def test_regrade_uses_explicit_corrected_rule_and_preserves_original_manifest_and_answer():
    owner, learner, run, attempt, item = _attempt(
        type_key="numeric",
        definition={"prompt": "Value", "answer": 10, "tolerance": "0"},
        points="3",
    )
    _submit(attempt=attempt, learner=learner, item=item, answer={"value": "11"})
    before = item.manifest["payload"].copy()
    result = regrade_attempts(
        run=run,
        item_keys=[str(item.key)],
        rule_version="activity-registry-v2",
        rule_config={"answer": 11},
        actor=owner,
        reason="Corrected key after review.",
    )
    assert result["scanned"] == 1
    assert result["changed"] == 1
    assert result["failed"] == 0
    item.refresh_from_db()
    grade = item.grade
    assert grade.normalized_score == Decimal("1.0000000000")
    assert grade.awarded_points == Decimal("3.00")
    assert grade.source == "automatic"
    assert grade.rule_version == "activity-registry-v2"
    assert item.manifest["payload"] == before
    assert item.answer_revisions.order_by("version").last().answer == {"value": 11.0}
    decisions = list(AssessmentGradeDecision.objects.filter(item=item).order_by("id"))
    assert decisions[0].normalized_score == Decimal("0E-10")
    assert decisions[-1].source == "regrade"
    assert decisions[-1].normalized_score == Decimal("1.0000000000")
    assert decisions[-1].actor_id == owner.pk
    assert decisions[-1].reason == "Corrected key after review."
    revision = GradingRuleRevision.objects.get(run=run, item_key=item.key, rule_version="activity-registry-v2")
    assert revision.version == 1
    assert revision.configuration == {"answer": 11}
    assert revision.created_by_id == owner.pk
    assert revision.approved_at is not None

    resolved = regrade_attempts(
        run=run,
        item_keys=[str(item.key)],
        rule_version="activity-registry-v2",
        actor=owner,
        reason="Replayed approved correction.",
    )
    assert resolved["unchanged"] == 1
    assert GradingRuleRevision.objects.filter(run=run, item_key=item.key).count() == 1


@pytest.mark.django_db
def test_regrade_rejects_unknown_rule_without_mutation_and_preserves_manual_grade():
    owner, learner, run, attempt, item = _attempt(
        type_key="numeric", definition={"prompt": "Value", "answer": 10}, points="3"
    )
    _submit(attempt=attempt, learner=learner, item=item, answer={"value": "10"})
    before_count = AssessmentGradeDecision.objects.filter(item=item).count()
    with pytest.raises(GradeCorrectionError, match="approved"):
        regrade_attempts(run=run, rule_version="wrong-rule", actor=owner, reason="Checked.")
    assert AssessmentGradeDecision.objects.filter(item=item).count() == before_count

    manual = override_item_grade(attempt_item=item, normalized_score="0.2", actor=owner, reason="Manual check.")
    result = regrade_attempts(
        run=run,
        rule_version="activity-registry-v2",
        rule_config={"answer": 99},
        actor=owner,
        reason="New key.",
    )
    assert result["preserved_manual"] == 1
    manual.refresh_from_db()
    assert manual.normalized_score == Decimal("0.2")
    assert manual.source == "override"


@pytest.mark.django_db
def test_regrade_rejects_non_grading_revision_without_persisting_it():
    owner, _learner, run, _attempt_obj, item = _attempt(
        type_key="numeric", definition={"prompt": "Value", "answer": 10}, points="3"
    )
    _submit(attempt=_attempt_obj, learner=_learner, item=item, answer={"value": "10"})
    with pytest.raises(GradeCorrectionError, match="grading fields"):
        regrade_attempts(
            run=run,
            item_keys=[str(item.key)],
            rule_version="activity-registry-v2",
            rule_config={"prompt": "Changed prompt"},
            actor=owner,
            reason="Invalid correction.",
        )
    assert not GradingRuleRevision.objects.filter(run=run, item_key=item.key).exists()
