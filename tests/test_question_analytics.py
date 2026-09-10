"""Retained-question outcome analytics stay aggregate unless explicitly requested."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import AnswerRevision, AssessmentItemGrade
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.question_analytics import QuestionAnalyticsError, question_analytics


def _run(owner):
    question = create_activity_definition(
        owner=owner,
        title="Analytics choice",
        type_key="single_choice",
        definition={
            "prompt": "Choose A",
            "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
            "answer": "a",
        },
    )
    assessment = create_assessment(
        actor=owner,
        data={"title": "Analytics quiz", "items": [{"revision_id": question.current_revision_id, "points": "2"}]},
    )
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


def _answered_attempt(user, run, choice):
    attempt, _ = start_or_resume_attempt(actor=user, run=run, request_id=uuid4())
    attempt.status = "submitted"
    attempt.save(update_fields=["status"])
    item = attempt.items.get()
    AnswerRevision.objects.create(item=item, version=1, answer={"choice": choice}, request_id=uuid4(), request_hash="a")
    AssessmentItemGrade.objects.create(
        item=item,
        status="graded",
        normalized_score=Decimal("1") if choice == "a" else Decimal("0"),
        possible_points=Decimal("2"),
        awarded_points=Decimal("2") if choice == "a" else Decimal("0"),
        retained_answer={"choice": choice},
    )
    return attempt


@pytest.mark.django_db
def test_question_analytics_uses_assigned_attempt_items_and_hides_answers_by_default():
    users = get_user_model()
    owner = users.objects.create_user(username="analytics-owner")
    first = users.objects.create_user(username="analytics-first")
    second = users.objects.create_user(username="analytics-second")
    run = _run(owner)
    _answered_attempt(first, run, "a")
    _answered_attempt(second, run, "b")

    payload = question_analytics(owner, run)
    question = payload["questions"][0]
    assert payload["denominators"]["assigned_students"] == 2
    assert question["assigned"] == 2
    assert question["answered"] == 2
    assert question["fully_graded"] == 2
    assert question["mean_normalized_score"] == "0.5000"
    assert question["options"][1]["selection_count"] == 1
    assert question["common_wrong_options"] == [{"id": "b", "text": "B", "count": 1, "share_selecting": "50.00"}]
    assert "named_responses" not in question
    assert question_analytics(owner, run, include_named=True)["questions"][0]["named_responses"][0]["answer"]


@pytest.mark.django_db
def test_question_analytics_api_is_mount_safe_and_denies_unrelated_accounts():
    users = get_user_model()
    owner = users.objects.create_user(username="analytics-api-owner")
    learner = users.objects.create_user(username="analytics-api-learner")
    run = _run(owner)
    _answered_attempt(learner, run, "a")
    owner_client = Client()
    owner_client.force_login(owner)
    response = owner_client.get(reverse("liveclassroom:api-v1-assessment-run-question-analytics", args=[run.public_id]))
    assert response.status_code == 200
    assert "named_responses" not in response.content.decode()
    learner_client = Client()
    learner_client.force_login(learner)
    denied = learner_client.get(
        reverse("liveclassroom:api-v1-assessment-run-question-analytics", args=[run.public_id])
    )
    assert denied.status_code == 404
    with pytest.raises(QuestionAnalyticsError):
        question_analytics(learner, run, include_named=True)
