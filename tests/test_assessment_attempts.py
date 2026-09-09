import json
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import AssessmentAttempt, Course, CourseMembership
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import start_or_resume_attempt
from liveclassroom.services.classroom import ClassroomError, create_activity_definition


def _run(owner, *, audience="authenticated_link", maximum=1, course=None):
    question = create_activity_definition(
        owner=owner,
        title="Question",
        type_key="single_choice",
        definition={
            "prompt": "Visible prompt",
            "options": [{"id": "a", "text": "A"}],
            "answer": "a",
            "explanation": "Private explanation",
        },
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Quiz",
            "course_id": course.id if course else None,
            "settings": {"max_attempts": maximum, "audience": audience},
            "items": [{"revision_id": question.current_revision_id}],
        },
    )
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


@pytest.mark.django_db
def test_start_reuses_active_attempt_and_copies_fixed_public_items():
    users = get_user_model()
    owner = users.objects.create_user(username="attempt-owner")
    alice = users.objects.create_user(username="attempt-alice")
    bob = users.objects.create_user(username="attempt-bob")
    run = _run(owner)
    first, created = start_or_resume_attempt(actor=alice, run=run, request_id=uuid4())
    repeated, created_again = start_or_resume_attempt(actor=alice, run=run, request_id=uuid4())
    other, other_created = start_or_resume_attempt(actor=bob, run=run, request_id=uuid4())
    assert created and not created_again and other_created
    assert first.pk == repeated.pk and first.pk != other.pk
    assert first.items.count() == 1
    detail = start_or_resume_attempt(actor=alice, run=run, request_id=uuid4())[0]
    assert detail.items.get().manifest["payload"]["prompt"] == "Visible prompt"


@pytest.mark.django_db
def test_completed_attempt_needs_explicit_new_request_and_limit_is_frozen():
    owner = get_user_model().objects.create_user(username="attempt-limit-owner")
    learner = get_user_model().objects.create_user(username="attempt-limit-learner")
    run = _run(owner, maximum=None)
    first, _ = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    first.status = AssessmentAttempt.Status.SUBMITTED
    first.save(update_fields=["status"])
    inspected, created = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    assert inspected.pk == first.pk and not created
    second, created = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4(), new_attempt=True)
    assert created and second.attempt_number == 2
    request_id = uuid4()
    start_or_resume_attempt(actor=learner, run=run, request_id=request_id)
    with pytest.raises(ClassroomError, match="different input"):
        start_or_resume_attempt(actor=learner, run=run, request_id=request_id, new_attempt=True)


@pytest.mark.django_db
def test_class_membership_is_checked_again_when_resuming():
    users = get_user_model()
    owner = users.objects.create_user(username="attempt-class-owner")
    learner = users.objects.create_user(username="attempt-class-learner")
    course = Course.objects.create(title="Cohort", slug="attempt-cohort", created_by=owner)
    CourseMembership.objects.create(course=course, user=learner, role=CourseMembership.Role.STUDENT)
    run = _run(owner, audience="class", course=course)
    attempt, _ = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    CourseMembership.objects.filter(course=course, user=learner).delete()
    with pytest.raises(ClassroomError, match="access"):
        start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    assert AssessmentAttempt.objects.filter(pk=attempt.pk).exists()


@pytest.mark.django_db
def test_attempt_api_hides_keys_and_get_has_no_creation_side_effect():
    users = get_user_model()
    owner = users.objects.create_user(username="attempt-api-owner")
    learner = users.objects.create_user(username="attempt-api-learner")
    other = users.objects.create_user(username="attempt-api-other")
    run = _run(owner)
    client = Client()
    client.force_login(learner)
    start_url = reverse("liveclassroom:api-v1-assessment-attempts", args=[run.public_id])
    response = client.post(start_url, data=json.dumps({"request_id": str(uuid4())}), content_type="application/json")
    assert response.status_code == 201
    payload = response.json()
    assert "answer" not in json.dumps(payload["items"][0]["payload"])
    assert "explanation" not in json.dumps(payload["items"][0])
    attempt_url = reverse("liveclassroom:api-v1-attempt-detail", args=[payload["id"]])
    assert client.get(attempt_url).status_code == 200
    intruder = Client()
    intruder.force_login(other)
    assert intruder.get(attempt_url).status_code == 404
    assert AssessmentAttempt.objects.filter(run=run).count() == 1
