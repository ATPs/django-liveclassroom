"""API privacy checks for assessment result release."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import AssessmentRun
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.result_release import release_result_dimension


def _fixture():
    users = get_user_model()
    owner = users.objects.create_user(username="release-api-owner", is_staff=True)
    learner = users.objects.create_user(username="release-api-learner")
    other = users.objects.create_user(username="release-api-other")
    question = create_activity_definition(
        owner=owner,
        title="API release question",
        type_key="single_choice",
        definition={
            "prompt": "API prompt",
            "options": [{"id": "a", "text": "A"}],
            "answer": "a",
            "explanation": "API explanation",
        },
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "API release",
            "settings": {
                "audience": AssessmentRun.Audience.AUTHENTICATED_LINK,
                "release_policy": {
                    "scores": "manual",
                    "answers": "manual",
                    "explanations": "manual",
                    "comments": "manual",
                },
            },
            "items": [{"revision_id": question.current_revision_id}],
        },
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    attempt, _ = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    return owner, learner, other, run, attempt


@pytest.mark.django_db
def test_result_endpoint_is_own_attempt_and_mount_safe():
    owner, learner, other, run, attempt = _fixture()
    client = Client()
    client.force_login(learner)
    url = reverse("liveclassroom:api-v1-attempt-result", args=[attempt.public_id])
    response = client.get(url)
    assert response.status_code == 200
    payload = response.json()
    assert payload["released"] == {
        "scores": False,
        "answers": False,
        "explanations": False,
        "comments": False,
    }
    assert "answer" not in payload["items"][0]
    assert "answer_key" not in payload["items"][0]
    assert client.get(reverse("liveclassroom:api-v1-attempt-result", args=[uuid4()])).status_code == 404
    intruder = Client()
    intruder.force_login(other)
    assert intruder.get(url).status_code == 404


@pytest.mark.django_db
def test_teacher_can_release_explicit_dimension_and_student_sees_only_that_dimension():
    owner, learner, other, run, attempt = _fixture()
    teacher = Client()
    teacher.force_login(owner)
    url = reverse("liveclassroom:api-v1-assessment-run-release", args=[run.public_id])
    response = teacher.post(
        url,
        data=json.dumps({"dimension": "explanations", "attempt_id": str(attempt.public_id)}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["attempt_id"] == str(attempt.public_id)
    student = Client()
    student.force_login(learner)
    payload = student.get(reverse("liveclassroom:api-v1-attempt-result", args=[attempt.public_id])).json()
    assert payload["released"]["explanations"] is True
    assert payload["items"][0]["explanation"] == "API explanation"
    assert "answer_key" not in payload["items"][0]
    assert "score" not in payload
    assert teacher.post(
        url,
        data=json.dumps({"dimension": "scores", "attempt_id": str(uuid4())}),
        content_type="application/json",
    ).status_code == 404


@pytest.mark.django_db
def test_submitted_attempt_detail_uses_result_policy():
    owner, learner, other, run, attempt = _fixture()
    attempt.status = "submitted"
    attempt.submitted_at = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    attempt.save(update_fields=["status", "submitted_at"])
    client = Client()
    client.force_login(learner)
    payload = client.get(reverse("liveclassroom:api-v1-attempt-detail", args=[attempt.public_id])).json()
    assert "answer" not in payload["items"][0]
    assert "answer_key" not in payload["items"][0]
    release_result_dimension(run=run, dimension="answers", actor=owner, attempt=attempt)
    payload = client.get(reverse("liveclassroom:api-v1-attempt-detail", args=[attempt.public_id])).json()
    assert payload["released"]["answers"] is True
    assert "answer_key" in payload["items"][0]
