"""Focused read-only contracts for the paginated Results workspace."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import AssessmentAttempt, Course, CourseMembership, TeachingCourse
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition


def _assessment(owner, *, course=None, title="Results assessment"):
    question = create_activity_definition(
        owner=owner,
        title=f"{title} question",
        type_key="short_text",
        definition={"prompt": "Explain the result."},
    )
    settings = {"max_attempts": 1, "audience": "class" if course else "authenticated_link"}
    return create_assessment(
        actor=owner,
        data={
            "title": title,
            "course_id": course.id if course else None,
            "settings": settings,
            "items": [{"revision_id": question.current_revision_id, "points": "3"}],
        },
    )


def _run(owner, *, course=None, title="Results assessment"):
    assessment = _assessment(owner, course=course, title=title)
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


@pytest.mark.django_db
def test_results_runs_and_attempts_paginate_without_cross_owner_leakage():
    users = get_user_model()
    owner = users.objects.create_user(username="results-api-owner")
    learner = users.objects.create_user(username="results-api-learner")
    other = users.objects.create_user(username="results-api-other")
    assessment = _assessment(owner, title="Paged results")
    runs = [
        publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
        for _ in range(26)
    ]
    _run(other, title="Private other result")
    selected = runs[0]
    for index in range(26):
        student = learner if index == 0 else users.objects.create_user(username=f"results-api-student-{index}")
        start_or_resume_attempt(actor=student, run=selected, request_id=uuid4())

    client = Client()
    client.force_login(owner)
    run_page = client.get(reverse("liveclassroom:api-v1-browse-results"), {"page": 2, "page_size": 25})
    assert run_page.status_code == 200
    assert run_page.json()["count"] == 26
    assert len(run_page.json()["items"]) == 1
    assert "Private other result" not in str(run_page.json())

    attempt_page = client.get(
        reverse("liveclassroom:api-v1-result-attempts", args=[selected.public_id]),
        {"page": 2, "page_size": 25},
    )
    assert attempt_page.status_code == 200
    assert attempt_page.json()["count"] == 26
    assert len(attempt_page.json()["items"]) == 1
    assert attempt_page.json()["previous"]


@pytest.mark.django_db
def test_results_scope_and_attempt_detail_reauthorize_each_request():
    users = get_user_model()
    owner = users.objects.create_user(username="scoped-results-owner")
    other = users.objects.create_user(username="scoped-results-other")
    learner = users.objects.create_user(username="scoped-results-learner")
    program = TeachingCourse.objects.create(title="Scoped program", created_by=owner)
    cohort = Course.objects.create(
        title="Scoped class", slug="scoped-results", created_by=owner, teaching_course=program
    )
    CourseMembership.objects.create(course=cohort, user=learner, role=CourseMembership.Role.STUDENT)
    run = _run(owner, course=cohort, title="Scoped result")
    attempt = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())[0]
    client = Client()
    client.force_login(owner)

    visible = client.get(reverse("liveclassroom:api-v1-browse-results"), {"class_id": cohort.id})
    assert visible.status_code == 200
    assert [row["public_id"] for row in visible.json()["items"]] == [str(run.public_id)]
    assert client.get(
        reverse("liveclassroom:api-v1-result-attempts", args=[run.public_id]), {"course_id": program.id}
    ).status_code == 200
    assert client.get(
        reverse("liveclassroom:api-v1-result-attempts", args=[run.public_id]), {"class_id": cohort.id + 1}
    ).status_code == 404

    other_client = Client()
    other_client.force_login(other)
    assert other_client.get(reverse("liveclassroom:api-v1-result-attempt", args=[attempt.public_id])).status_code == 404


@pytest.mark.django_db
def test_learner_item_discovery_is_scoped_and_never_starts_an_attempt():
    users = get_user_model()
    owner = users.objects.create_user(username="learning-items-owner")
    learner = users.objects.create_user(username="learning-items-learner")
    program = TeachingCourse.objects.create(title="Learner items program", created_by=owner)
    cohort = Course.objects.create(
        title="Learner items class", slug="learning-items", created_by=owner, teaching_course=program
    )
    CourseMembership.objects.create(course=cohort, user=learner, role=CourseMembership.Role.STUDENT)
    run = _run(owner, course=cohort, title="Learner available result")
    client = Client()
    client.force_login(learner)
    before = AssessmentAttempt.objects.count()

    response = client.get(
        reverse("liveclassroom:api-v1-browse-learning-items", args=["assessments"]),
        {"course_id": program.id, "class_id": cohort.id},
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["items"] == [{
        "public_id": str(run.public_id),
        "title": "Learner available result",
        "url": reverse("liveclassroom:assessment-attempt", args=[run.public_id]),
    }]
    assert AssessmentAttempt.objects.count() == before
