"""HTTP permissions and decimal serialization for manual grading."""

import json
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse

from liveclassroom.models import AssessmentGradeDecision
from tests.test_manual_grading import _essay_attempt


@pytest.mark.django_db
def test_queue_and_manual_grade_api_are_staff_only_and_idempotent():
    owner, learner, run, attempt, item = _essay_attempt()
    queue_url = reverse("liveclassroom:api-v1-grading-queue")
    grade_url = reverse(
        "liveclassroom:api-v1-manual-grade", args=[attempt.public_id, item.key]
    )

    teacher = Client()
    teacher.force_login(owner)
    queue = teacher.get(queue_url, SCRIPT_NAME="/mounted")
    assert queue.status_code == 200
    assert queue.json()["count"] == 1
    assert queue.json()["items"][0]["answer"] == {
        "text": "A considered answer.\nWith a second line."
    }
    assert queue.json()["items"][0]["possible_points"] == "4.000000"

    student = Client()
    student.force_login(learner)
    denied_queue = student.get(queue_url)
    assert denied_queue.status_code == 403
    assert "answer" not in denied_queue.json()
    denied_grade = student.post(
        grade_url,
        data=json.dumps({"normalized_score": "0.5", "reason": "Checked."}),
        content_type="application/json",
    )
    assert denied_grade.status_code == 403
    assert "answer" not in denied_grade.json()

    body = {"awarded_points": "3", "comment": "Clear evidence.", "reason": "Reviewed."}
    response = teacher.post(grade_url, data=json.dumps(body), content_type="application/json")
    assert response.status_code == 200
    assert response.json()["normalized_score"] == "0.7500000000"
    assert response.json()["possible_points"] == "4.000000"
    assert response.json()["awarded_points"] == "3.00"
    repeated = teacher.post(grade_url, data=json.dumps(body), content_type="application/json")
    assert repeated.status_code == 200
    assert repeated.json()["awarded_points"] == "3.00"
    assert AssessmentGradeDecision.objects.filter(attempt=attempt, item=item).count() == 2
    assert teacher.get(queue_url).json() == {"items": [], "count": 0}


@pytest.mark.django_db
def test_manual_grade_api_rejects_bad_scores_reasons_and_wrong_attempt_item():
    owner, _learner, _run, attempt, item = _essay_attempt()
    client = Client()
    client.force_login(owner)
    url = reverse("liveclassroom:api-v1-manual-grade", args=[attempt.public_id, item.key])
    for body in (
        {"normalized_score": "-0.01", "reason": "Checked."},
        {"normalized_score": "1.01", "reason": "Checked."},
        {"normalized_score": "0.5", "reason": "  "},
    ):
        response = client.post(url, data=json.dumps(body), content_type="application/json")
        assert response.status_code == 400
        assert set(response.json()) == {"code", "detail"}

    wrong_item_url = reverse(
        "liveclassroom:api-v1-manual-grade", args=[attempt.public_id, uuid4()]
    )
    wrong = client.post(
        wrong_item_url,
        data=json.dumps({"normalized_score": "0.5", "reason": "Checked."}),
        content_type="application/json",
    )
    assert wrong.status_code == 404
    assert set(wrong.json()) == {"code", "detail"}
