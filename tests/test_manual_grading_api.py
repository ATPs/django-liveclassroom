"""HTTP permissions and decimal serialization for manual grading."""

import json
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse

from liveclassroom.models import AssessmentGradeDecision, AssessmentRun, Course, TeachingCourse
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


@pytest.mark.django_db
def test_queue_applies_class_and_course_scope_before_serializing_pending_items():
    owner, _learner, run_one, attempt_one, _item_one = _essay_attempt()
    other_owner, _other_learner, run_two, attempt_two, _item_two = _essay_attempt()
    program = TeachingCourse.objects.create(title="Scoped grading", created_by=owner)
    first = Course.objects.create(
        title="First scope", slug="manual-scope-first", created_by=owner, teaching_course=program
    )
    second = Course.objects.create(
        title="Second scope", slug="manual-scope-second", created_by=owner, teaching_course=program
    )
    run_one.course = first
    run_one.audience = AssessmentRun.Audience.CLASS
    run_one.save(update_fields=["course", "audience"])
    # The fixture's second run is deliberately reassigned to the same manager
    # so the scope filter, rather than owner isolation, determines visibility.
    run_two.owner = owner
    run_two.course = second
    run_two.audience = AssessmentRun.Audience.CLASS
    run_two.save(update_fields=["owner", "course", "audience"])

    client = Client()
    client.force_login(owner)
    queue_url = reverse("liveclassroom:api-v1-grading-queue")
    scoped = client.get(queue_url, {"class_id": first.id})
    assert scoped.status_code == 200
    assert [row["attempt_id"] for row in scoped.json()["items"]] == [str(attempt_one.public_id)]
    program_scope = client.get(queue_url, {"course_id": program.id})
    assert program_scope.status_code == 200
    assert {row["attempt_id"] for row in program_scope.json()["items"]} == {
        str(attempt_one.public_id), str(attempt_two.public_id),
    }
    mismatched = client.get(queue_url, {"run_id": run_one.public_id, "class_id": second.id})
    assert mismatched.status_code == 200
    assert mismatched.json() == {"items": [], "count": 0}
