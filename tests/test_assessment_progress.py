"""Focused privacy and status tests for teacher assessment progress."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import (
    AssessmentAttempt,
    AssessmentAttemptGrade,
    AssessmentRun,
    Course,
    CourseMembership,
    Participant,
)
from liveclassroom.services.assessment_progress import (
    AssessmentProgressError,
    get_student_overview,
    list_run_progress,
)
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.plans import create_session


def _run(owner, *, course=None, audience="authenticated_link"):
    question = create_activity_definition(
        owner=owner,
        title="Progress question",
        type_key="single_choice",
        definition={
            "prompt": "Pick",
            "options": [{"id": "a", "text": "A"}],
            "answer": "a",
        },
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Progress assessment",
            "course_id": course.id if course else None,
            "settings": {"audience": audience},
            "items": [{"revision_id": question.current_revision_id, "points": "2"}],
        },
    )
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


def _submitted(attempt, *, graded=False):
    attempt.status = "submitted"
    attempt.submitted_at = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    attempt.save(update_fields=["status", "submitted_at"])
    if graded:
        AssessmentAttemptGrade.objects.create(
            attempt=attempt,
            status="graded",
            possible_points=Decimal("2"),
            awarded_points=Decimal("2.00"),
            graded_count=1,
        )


@pytest.mark.django_db
def test_authenticated_link_counts_started_without_misleading_eligible_total():
    users = get_user_model()
    owner = users.objects.create_user(username="progress-link-owner")
    learner = users.objects.create_user(username="progress-link-learner")
    run = _run(owner)
    attempt, _ = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    payload = list_run_progress(owner, run)
    assert payload["counts"]["eligible_total"] is None
    assert payload["counts"]["started"] == 1
    assert payload["students"][0]["status"] == "in_progress"
    assert payload["pagination"]["page"] == 1
    _submitted(attempt, graded=True)
    payload = list_run_progress(owner, run, {"status": "graded", "page_size": 1})
    assert payload["counts"]["graded"] == 1
    assert payload["students"][0]["latest_attempt"]["grade"]["awarded_points"] == "2.00"


@pytest.mark.django_db
def test_class_roster_adds_not_started_and_excludes_test_account():
    users = get_user_model()
    owner = users.objects.create_user(username="progress-class-owner")
    started = users.objects.create_user(username="progress-class-started")
    waiting = users.objects.create_user(username="progress-class-waiting")
    test_user = users.objects.create_user(username="progress-class-test")
    course = Course.objects.create(title="Progress class", slug="progress-class", created_by=owner)
    for user in (started, waiting, test_user):
        CourseMembership.objects.create(course=course, user=user, role=CourseMembership.Role.STUDENT)
    run = _run(owner, course=course, audience=AssessmentRun.Audience.CLASS)
    attempt, _ = start_or_resume_attempt(actor=started, run=run, request_id=uuid4())
    _submitted(attempt)
    session = create_session(owner=owner, title="Progress live", course=course)
    Participant.objects.create(
        session=session,
        user=test_user,
        test_owner=owner,
        is_test=True,
        guest_id="progress-test",
        display_name="Test student",
    )
    payload = list_run_progress(owner, run)
    assert payload["counts"]["eligible_total"] == 2
    assert payload["counts"]["not_started"] == 1
    assert {row["student_username"] for row in payload["students"]} == {started.username, waiting.username}
    assert (
        list_run_progress(owner, run, {"status": "not_started"})["students"][0]["student_username"]
        == waiting.username
    )


@pytest.mark.django_db
def test_progress_permission_filters_and_student_overview_has_no_side_effects():
    users = get_user_model()
    owner = users.objects.create_user(username="progress-private-owner")
    student = users.objects.create_user(username="progress-private-student")
    other = users.objects.create_user(username="progress-private-other")
    run = _run(owner)
    attempt, _ = start_or_resume_attempt(actor=student, run=run, request_id=uuid4())
    before_attempts = AssessmentAttempt.objects.count()
    with pytest.raises(AssessmentProgressError):
        list_run_progress(other, run)
    overview = get_student_overview(owner, student)
    assert overview["student"]["username"] == student.username
    assert overview["attempts"][0]["id"] == str(attempt.public_id)
    assert AssessmentAttempt.objects.count() == before_attempts
    with pytest.raises(AssessmentProgressError):
        get_student_overview(other, student)


@pytest.mark.django_db
def test_progress_api_is_mount_safe_and_does_not_expose_answers():
    users = get_user_model()
    owner = users.objects.create_user(username="progress-api-owner")
    student = users.objects.create_user(username="progress-api-student")
    run = _run(owner)
    attempt, _ = start_or_resume_attempt(actor=student, run=run, request_id=uuid4())
    client = Client()
    client.force_login(owner)
    response = client.get(reverse("liveclassroom:api-v1-assessment-run-progress", args=[run.public_id]))
    assert response.status_code == 200
    assert response.json()["students"][0]["student_username"] == student.username
    assert "answer" not in response.json()["students"][0]
    overview = client.get(reverse("liveclassroom:api-v1-student-overview", args=[student.id]))
    assert overview.status_code == 200
    assert overview.json()["attempts"][0]["id"] == str(attempt.public_id)
    intruder = Client()
    intruder.force_login(student)
    assert (
        intruder.get(
            reverse("liveclassroom:api-v1-assessment-run-progress", args=[run.public_id])
        ).status_code
        == 404
    )
