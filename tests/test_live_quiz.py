import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import Course, Flow, FlowItem, LiveSession, Question


@pytest.fixture
def classroom():
    teacher = get_user_model().objects.create_user(username="teacher", password="password")
    course = Course.objects.create(title="RNA-seq", slug="rna-seq", created_by=teacher)
    flow = Flow.objects.create(course=course, title="Introduction", slug="introduction")
    question = Question.objects.create(
        question_type=Question.Type.SINGLE_CHOICE,
        stem_markdown="Which input does DESeq2 use?",
        data={
            "options": [
                {"id": "A", "text": "TPM"},
                {"id": "B", "text": "Raw counts"},
            ]
        },
        answer=["B"],
        explanation_markdown="DESeq2 models raw counts.",
    )
    item = FlowItem.objects.create(
        flow=flow,
        position=1,
        kind=FlowItem.Kind.QUESTION,
        title="DESeq2 input",
        question=question,
    )
    session = LiveSession.objects.create(course=course, flow=flow, teacher=teacher)
    return {"teacher": teacher, "item": item, "session": session}


def post_json(client, url, payload=None):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json")


@pytest.mark.django_db
def test_teacher_to_guest_quiz_lifecycle(client, classroom):
    session = classroom["session"]
    client.force_login(classroom["teacher"])

    started = post_json(client, reverse("liveclassroom:api-start", args=[session.id]))
    assert started.status_code == 200

    launched = post_json(
        client,
        reverse("liveclassroom:api-launch", args=[session.id]),
        {"flow_item_id": classroom["item"].id},
    )
    assert launched.status_code == 201
    activity_id = launched.json()["activity_id"]

    student = Client()
    joined = post_json(student, reverse("liveclassroom:api-join", args=[session.join_code]), {"display_name": "Ada"})
    assert joined.status_code == 201

    before_answer = student.get(reverse("liveclassroom:api-state", args=[session.id])).json()
    question = before_answer["current_activity"]["definition"]["question"]
    assert "answer" not in question
    assert "explanation_markdown" not in question

    submitted = post_json(student, reverse("liveclassroom:api-submit", args=[activity_id]), {"answer": {"choice": "B"}})
    assert submitted.status_code == 201
    duplicate = post_json(
        student,
        reverse("liveclassroom:api-submit", args=[activity_id]),
        {"answer": {"choice": "B"}},
    )
    assert duplicate.status_code == 409

    closed = post_json(client, reverse("liveclassroom:api-close", args=[activity_id]))
    assert closed.status_code == 200
    revealed = post_json(client, reverse("liveclassroom:api-reveal", args=[activity_id]))
    assert revealed.status_code == 200

    after_reveal = student.get(reverse("liveclassroom:api-state", args=[session.id])).json()
    assert after_reveal["current_activity"]["definition"]["question"]["answer"] == ["B"]
    assert after_reveal["current_activity"]["definition"]["question"]["explanation_markdown"]

    results = client.get(reverse("liveclassroom:api-results", args=[activity_id]))
    assert results.status_code == 200
    assert results.json()["choices"] == {"B": 1}


@pytest.mark.django_db
def test_students_cannot_launch_or_view_results(client, classroom):
    session = classroom["session"]
    unauthorised_launch = post_json(
        client,
        reverse("liveclassroom:api-launch", args=[session.id]),
        {"flow_item_id": classroom["item"].id},
    )

    assert unauthorised_launch.status_code == 403
