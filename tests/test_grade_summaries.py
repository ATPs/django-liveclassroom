"""Derived class and course grade-summary contracts."""

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
    TeachingCourse,
)
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.grade_summaries import (
    GradeSummaryError,
    class_grade_summary,
    teaching_course_grade_summary,
)
from liveclassroom.services.organization import assign_class
from liveclassroom.services.plans import create_session


def _run(owner, course, *, title, points="2", maximum=None):
    question = create_activity_definition(
        owner=owner,
        title=title,
        type_key="single_choice",
        definition={
            "prompt": title,
            "options": [{"id": "a", "text": "A"}],
            "answer": "a",
        },
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": title,
            "course_id": course.id,
            "settings": {"audience": AssessmentRun.Audience.CLASS, "max_attempts": maximum},
            "items": [{"revision_id": question.current_revision_id, "points": points}],
        },
    )
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


def _submitted(attempt, *, awarded="1.00", possible="2.00", status="graded", pending=0):
    attempt.status = AssessmentAttempt.Status.SUBMITTED
    attempt.submitted_at = attempt.started_at
    attempt.save(update_fields=["status", "submitted_at"])
    AssessmentAttemptGrade.objects.create(
        attempt=attempt,
        status=status,
        possible_points=Decimal(possible),
        awarded_points=Decimal(awarded),
        graded_count=0 if status == "pending" else 1,
        pending_count=pending,
    )


@pytest.mark.django_db
def test_class_summary_selects_latest_submitted_keeps_all_attempts_and_excludes_tests():
    users = get_user_model()
    owner = users.objects.create_user(username="summary-owner")
    student = users.objects.create_user(username="summary-student")
    waiting = users.objects.create_user(username="summary-waiting")
    test_user = users.objects.create_user(username="summary-test")
    course = Course.objects.create(title="Summary class", slug="summary-class", created_by=owner)
    for user in (student, waiting, test_user):
        CourseMembership.objects.create(course=course, user=user, role=CourseMembership.Role.STUDENT)
    run = _run(owner, course, title="Exam", maximum=None)
    first, _ = start_or_resume_attempt(actor=student, run=run, request_id=uuid4())
    _submitted(first, awarded="2.00")
    second, _ = start_or_resume_attempt(actor=student, run=run, request_id=uuid4(), new_attempt=True)
    _submitted(second, awarded="0.00", status="pending", pending=1)
    active, _ = start_or_resume_attempt(actor=student, run=run, request_id=uuid4(), new_attempt=True)
    test_attempt, _ = start_or_resume_attempt(actor=test_user, run=run, request_id=uuid4())
    _submitted(test_attempt, awarded="2.00")
    session = create_session(owner=owner, title="Summary session", course=course)
    Participant.objects.create(
        session=session,
        user=test_user,
        test_owner=owner,
        is_test=True,
        display_name="test",
        guest_id="summary-test",
    )

    payload = class_grade_summary(owner, course)
    assert [row["student_username"] for row in payload["students"]] == [student.username, waiting.username]
    cell = next(row for row in payload["students"] if row["student_id"] == student.pk)["cells"][str(run.public_id)]
    assert cell["state"] == "pending"
    assert cell["attempt_id"] == str(second.public_id)
    assert cell["active_attempt"]["id"] == str(active.public_id)
    assert len(cell["attempts"]) == 3
    assert payload["runs"][0]["completion"] == {"completed": 1, "denominator": 2, "percent": "50.00"}
    assert payload["runs"][0]["distribution"]["graded_count"] == 0
    assert payload["runs"][0]["distribution"]["excluded_pending_count"] == 1


@pytest.mark.django_db
def test_summary_distinguishes_zero_and_pending_and_handles_unequal_points_and_empty_class():
    users = get_user_model()
    owner = users.objects.create_user(username="summary-empty-owner")
    student = users.objects.create_user(username="summary-zero-student")
    course = Course.objects.create(title="Empty summary", slug="empty-summary", created_by=owner)
    CourseMembership.objects.create(course=course, user=student, role=CourseMembership.Role.STUDENT)
    first = _run(owner, course, title="Two points", points="2")
    second = _run(owner, course, title="Five points", points="5")
    first_attempt, _ = start_or_resume_attempt(actor=student, run=first, request_id=uuid4())
    _submitted(first_attempt, awarded="0.00", possible="2.00")
    second_attempt, _ = start_or_resume_attempt(actor=student, run=second, request_id=uuid4())
    _submitted(second_attempt, awarded="0.00", possible="5.00", status="pending", pending=1)
    payload = class_grade_summary(owner, course)
    cells = payload["students"][0]["cells"]
    assert cells[str(first.public_id)]["state"] == "graded"
    assert cells[str(first.public_id)]["earned_points"] == "0.00"
    assert payload["overall"]["earned_points"] == "0.00"
    assert payload["overall"]["possible_points"] == "2.00"
    assert payload["overall"]["pending_count"] == 1
    empty = Course.objects.create(title="No students", slug="no-students", created_by=owner)
    empty_payload = class_grade_summary(owner, empty)
    assert empty_payload["roster"]["denominator"] == 0
    assert empty_payload["runs"] == []


@pytest.mark.django_db
def test_course_summary_only_includes_authorized_classes_and_api_denies_students():
    users = get_user_model()
    owner = users.objects.create_user(username="summary-course-owner")
    student = users.objects.create_user(username="summary-course-student")
    foreign = users.objects.create_user(username="summary-course-foreign")
    group = TeachingCourse.objects.create(title="Grouped", created_by=owner)
    owned = Course.objects.create(title="Owned class", slug="owned-summary", created_by=owner)
    assign_class(actor=owner, teaching_course=group, cohort=owned)
    foreign_class = Course.objects.create(
        title="Foreign class", slug="foreign-summary", created_by=foreign, teaching_course=group
    )
    CourseMembership.objects.create(course=owned, user=student, role=CourseMembership.Role.STUDENT)
    _run(owner, owned, title="Owned exam")
    _run(foreign, foreign_class, title="Foreign exam")
    payload = teaching_course_grade_summary(owner, group)
    assert [row["class"]["title"] for row in payload["classes"]] == [owned.title]
    with pytest.raises(GradeSummaryError):
        class_grade_summary(student, owned)
    client = Client()
    client.force_login(student)
    response = client.get(reverse("liveclassroom:api-v1-class-grade-summary", args=[owned.pk]))
    assert response.status_code == 404
    client.force_login(owner)
    assert client.get(reverse("liveclassroom:api-v1-course-grade-summary", args=[owned.pk])).status_code == 200
    group_response = client.get(
        reverse("liveclassroom:api-v1-teaching-course-grade-summary", args=[group.pk])
    )
    assert group_response.status_code == 200
    assert group_response.json()["classes"][0]["class"]["id"] == owned.pk
