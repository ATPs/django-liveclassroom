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
    reveal_settings = post_json(
        client,
        reverse("liveclassroom:api-v1-channel-settings", args=[session.id]),
        {"channel": "participants", "show_answer": True, "show_explanation": True},
    )
    assert reveal_settings.status_code == 200
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


@pytest.mark.django_db
def test_participant_state_requires_join_and_waiting_room_admission(client, classroom):
    session = classroom["session"]
    session.admission_mode = LiveSession.AdmissionMode.WAITING_ROOM
    session.save(update_fields=["admission_mode"])

    state_url = f"{reverse('liveclassroom:api-v1-state', args=[session.id])}?channel=participants"
    assert client.get(state_url).status_code == 403

    teacher = classroom["teacher"]
    client.force_login(teacher)
    post_json(client, reverse("liveclassroom:api-v1-start", args=[session.id]))

    student = Client()
    joined = post_json(student, reverse("liveclassroom:api-v1-join", args=[session.join_code]), {"display_name": "Ada"})
    assert joined.status_code == 201
    pending_state = student.get(reverse("liveclassroom:api-v1-state", args=[session.id]))
    assert pending_state.status_code == 200
    assert pending_state.json()["participant"]["admission_state"] == "pending"
    assert pending_state.json()["current_activity"] is None

    participant_id = joined.json()["participant_id"]
    admitted = post_json(
        client,
        reverse("liveclassroom:api-v1-admission", args=[session.id, participant_id]),
        {"admitted": True},
    )
    assert admitted.status_code == 200
    assert student.get(reverse("liveclassroom:api-v1-state", args=[session.id])).status_code == 200


@pytest.mark.django_db
def test_staff_roster_endpoint_does_not_expose_guest_identity(client, classroom):
    client.force_login(classroom["teacher"])
    started = post_json(client, reverse("liveclassroom:api-start", args=[classroom["session"].id]))
    assert started.status_code == 200
    student = Client()
    joined = post_json(
        student,
        reverse("liveclassroom:api-join", args=[classroom["session"].join_code]),
        {"display_name": "Ada"},
    )
    assert joined.status_code == 201

    response = client.get(reverse("liveclassroom:api-v1-participants", args=[classroom["session"].id]))
    assert response.status_code == 200
    assert response.json()["participants"][0]["display_name"] == "Ada"
    assert "guest_id" not in response.json()["participants"][0]


@pytest.mark.django_db
def test_staff_can_export_archive_and_csv_datasets_but_students_cannot(client, classroom):
    session = classroom["session"]
    teacher = classroom["teacher"]
    client.force_login(teacher)
    post_json(client, reverse("liveclassroom:api-start", args=[session.id]))
    launched = post_json(
        client,
        reverse("liveclassroom:api-launch", args=[session.id]),
        {"flow_item_id": classroom["item"].id},
    )
    activity_id = launched.json()["activity_id"]

    student = Client()
    joined = post_json(student, reverse("liveclassroom:api-join", args=[session.join_code]), {"display_name": "Ada"})
    assert joined.status_code == 201
    submitted = post_json(
        student,
        reverse("liveclassroom:api-submit", args=[activity_id]),
        {"answer": {"choice": "B"}},
    )
    assert submitted.status_code == 201

    archive = client.get(reverse("liveclassroom:api-v1-export", args=[session.id]))
    assert archive.status_code == 200
    assert archive["Content-Disposition"].endswith(f'"liveclassroom-{session.id}.json"')
    assert archive.json()["responses"][0]["display_name"] == "Ada"

    csv_response = client.get(
        reverse("liveclassroom:api-v1-export", args=[session.id]), {"format": "csv", "dataset": "responses"}
    )
    assert csv_response.status_code == 200
    assert "Ada" in csv_response.content.decode()
    assert student.get(reverse("liveclassroom:api-v1-export", args=[session.id])).status_code == 403


@pytest.mark.django_db
def test_reusable_activity_authoring_api_uses_registry_and_immutable_revisions(client):
    teacher = get_user_model().objects.create_user(username="author")
    client.force_login(teacher)
    created = post_json(
        client,
        reverse("liveclassroom:api-v1-activity-create"),
        {
            "title": "Quick check",
            "type_key": "single_choice",
            "definition": {"options": [{"id": "A", "text": "One"}]},
        },
    )
    assert created.status_code == 201
    activity_id = created.json()["id"]
    assert client.get(reverse("liveclassroom:api-v1-activity-definitions")).json()["activities"][0]["id"] == activity_id

    revised = post_json(
        client,
        reverse("liveclassroom:api-v1-activity-revise", args=[activity_id]),
        {"definition": {"options": [{"id": "A", "text": "Updated"}]}},
    )
    assert revised.status_code == 201
    assert revised.json()["revision"] == 2


@pytest.mark.django_db
def test_reusable_activity_authoring_idempotency_replays_without_duplicates(client):
    teacher = get_user_model().objects.create_user(username="author-retry")
    client.force_login(teacher)
    payload = {
        "title": "Retry-safe check",
        "type_key": "single_choice",
        "definition": {"options": [{"id": "A", "text": "One"}]},
    }
    headers = {"HTTP_IDEMPOTENCY_KEY": "activity-create-once"}
    first = client.post(
        reverse("liveclassroom:api-v1-activity-create"),
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )
    second = client.post(
        reverse("liveclassroom:api-v1-activity-create"),
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert second.headers["Idempotent-Replay"] == "true"
    assert teacher.liveclassroom_activity_definitions.count() == 1

    activity_id = first.json()["id"]
    revision_payload = {"definition": {"options": [{"id": "A", "text": "Updated"}]}}
    revision_headers = {"HTTP_IDEMPOTENCY_KEY": "activity-revise-once"}
    revised = client.post(
        reverse("liveclassroom:api-v1-activity-revise", args=[activity_id]),
        data=json.dumps(revision_payload),
        content_type="application/json",
        **revision_headers,
    )
    replayed = client.post(
        reverse("liveclassroom:api-v1-activity-revise", args=[activity_id]),
        data=json.dumps(revision_payload),
        content_type="application/json",
        **revision_headers,
    )
    assert revised.status_code == replayed.status_code == 201
    assert revised.json() == replayed.json()
    assert activity_id and teacher.liveclassroom_activity_definitions.get(id=activity_id).revisions.count() == 2


@pytest.mark.django_db
def test_channel_visibility_can_show_explanation_without_answer(client, classroom):
    session = classroom["session"]
    client.force_login(classroom["teacher"])
    post_json(client, reverse("liveclassroom:api-start", args=[session.id]))
    launched = post_json(
        client,
        reverse("liveclassroom:api-launch", args=[session.id]),
        {"flow_item_id": classroom["item"].id},
    )
    assert launched.status_code == 201

    student = Client()
    joined = post_json(student, reverse("liveclassroom:api-join", args=[session.join_code]), {"display_name": "Ada"})
    assert joined.status_code == 201
    settings_response = post_json(
        client,
        reverse("liveclassroom:api-v1-channel-settings", args=[session.id]),
        {"channel": "participants", "show_explanation": True},
    )
    assert settings_response.status_code == 200

    question = student.get(reverse("liveclassroom:api-v1-state", args=[session.id])).json()["current_activity"][
        "definition"
    ]["question"]
    assert "answer" not in question
    assert question["explanation_markdown"]
