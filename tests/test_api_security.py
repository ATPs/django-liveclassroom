import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import SessionStaff
from liveclassroom.services.classroom import (
    ClassroomError,
    create_activity_definition,
    create_instant_session,
    launch_item,
    publish_activity_to_channel,
    set_activity_state,
    start_session,
)


def post_json(client, url, payload=None):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json")


@pytest.mark.django_db
def test_session_controller_cannot_launch_another_teachers_private_activity():
    user_model = get_user_model()
    teacher = user_model.objects.create_user(username="session-teacher")
    another_teacher = user_model.objects.create_user(username="another-teacher")
    session = create_instant_session(owner=teacher, title="Private activity boundary")
    private_activity = create_activity_definition(
        owner=another_teacher,
        title="Private prompt",
        type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "A", "text": "Only the owner may use this"}]},
    )
    start_session(session=session, actor=teacher)

    with pytest.raises(ClassroomError, match="permission to use this activity"):
        launch_item(session=session, item=private_activity, actor=teacher)


@pytest.mark.django_db
def test_observer_state_does_not_include_projector_channel():
    user_model = get_user_model()
    teacher = user_model.objects.create_user(username="state-teacher")
    observer = user_model.objects.create_user(username="state-observer")
    session = create_instant_session(owner=teacher, title="Observer boundary")
    SessionStaff.objects.create(session=session, user=observer, role=SessionStaff.Role.OBSERVER)
    activity_definition = create_activity_definition(
        owner=teacher,
        title="Visible participant prompt",
        type_key="liveclassroom.poll",
        definition={"options": [{"id": "A", "text": "One"}]},
    )
    start_session(session=session, actor=teacher)
    launch_item(session=session, item=activity_definition, actor=teacher)

    observer_client = Client()
    observer_client.force_login(observer)
    response = observer_client.get(
        reverse("liveclassroom:api-v1-state", args=[session.id]), {"channel": "participants"}
    )

    assert response.status_code == 200
    assert set(response.json()["channels"]) == {"participants"}
    default_state = observer_client.get(reverse("liveclassroom:api-state", args=[session.id]))
    assert default_state.status_code == 200
    assert set(default_state.json()["channels"]) == {"participants"}


@pytest.mark.django_db
def test_student_history_keeps_answers_hidden_when_activity_was_revealed_globally():
    user_model = get_user_model()
    teacher = user_model.objects.create_user(username="history-teacher")
    session = create_instant_session(owner=teacher, title="History boundary")
    activity_definition = create_activity_definition(
        owner=teacher,
        title="Answer stays private",
        type_key="liveclassroom.single_choice",
        definition={
            "options": [{"id": "A", "text": "Wrong"}, {"id": "B", "text": "Right"}],
            "answer": ["B"],
            "explanation_markdown": "Teacher-only explanation",
        },
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=activity_definition, actor=teacher)
    publish_activity_to_channel(
        session=session,
        activity=activity,
        channel="participants",
        actor=teacher,
        allow_review=True,
    )
    set_activity_state(activity=activity, state="closed", actor=teacher)
    set_activity_state(activity=activity, state="revealed", actor=teacher)

    student = Client()
    joined = post_json(student, reverse("liveclassroom:api-v1-join", args=[session.join_code]), {"display_name": "Ada"})
    assert joined.status_code == 201
    current_state = student.get(reverse("liveclassroom:api-v1-state", args=[session.id]))
    assert current_state.status_code == 200
    assert "answer" not in current_state.json()["current_activity"]["definition"]
    response = student.get(reverse("liveclassroom:api-v1-history", args=[session.id]))

    assert response.status_code == 200
    definition = response.json()["activities"][0]["definition"]
    assert "answer" not in definition
    assert "explanation_markdown" not in definition


@pytest.mark.django_db
def test_student_history_uses_each_activity_revision_not_current_channel_revision():
    user_model = get_user_model()
    teacher = user_model.objects.create_user(username="history-revision-teacher")
    session = create_instant_session(owner=teacher, title="History revisions")
    first_definition = create_activity_definition(
        owner=teacher,
        title="First question",
        type_key="liveclassroom.single_choice",
        definition={
            "prompt": "First prompt",
            "options": [{"id": "A", "text": "First option"}],
            "answer": ["A"],
            "explanation_markdown": "First explanation",
        },
    )
    second_definition = create_activity_definition(
        owner=teacher,
        title="Second question",
        type_key="liveclassroom.single_choice",
        definition={
            "prompt": "Second prompt",
            "options": [{"id": "B", "text": "Second option"}],
            "answer": ["B"],
            "explanation_markdown": "Second explanation",
        },
    )
    start_session(session=session, actor=teacher)
    first_activity = launch_item(session=session, item=first_definition, actor=teacher)
    second_activity = launch_item(session=session, item=second_definition, actor=teacher)
    first_activity.reviewable = True
    first_activity.save(update_fields=["reviewable"])
    second_activity.reviewable = True
    second_activity.save(update_fields=["reviewable"])

    student = Client()
    joined = post_json(student, reverse("liveclassroom:api-v1-join", args=[session.join_code]), {"display_name": "Ada"})
    assert joined.status_code == 201

    response = student.get(reverse("liveclassroom:api-v1-history", args=[session.id]))

    assert response.status_code == 200
    activities = response.json()["activities"]
    assert [activity["id"] for activity in activities] == [first_activity.id, second_activity.id]
    assert [activity["definition"]["title"] for activity in activities] == [
        "First question",
        "Second question",
    ]
    for activity in activities:
        assert "answer" not in activity["definition"]
        assert "explanation_markdown" not in activity["definition"]


@pytest.mark.django_db
def test_observer_cannot_export_named_session_archive():
    user_model = get_user_model()
    teacher = user_model.objects.create_user(username="export-teacher")
    observer = user_model.objects.create_user(username="export-observer")
    session = create_instant_session(owner=teacher, title="Export boundary")
    SessionStaff.objects.create(session=session, user=observer, role=SessionStaff.Role.OBSERVER)
    observer_client = Client()
    observer_client.force_login(observer)

    response = observer_client.get(reverse("liveclassroom:api-v1-export", args=[session.id]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_idempotency_key_rejects_different_input_and_releases_failed_reservation():
    teacher = get_user_model().objects.create_user(username="idempotency-teacher")
    session = create_instant_session(owner=teacher, title="Idempotency boundary")
    start_url = reverse("liveclassroom:api-v1-start", args=[session.id])
    key = "start-once"

    anonymous = Client()
    denied = anonymous.post(start_url, data="{}", content_type="application/json", HTTP_IDEMPOTENCY_KEY=key)
    assert denied.status_code == 403

    teacher_client = Client()
    teacher_client.force_login(teacher)
    started = teacher_client.post(
        start_url,
        data="{}",
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert started.status_code == 200
    changed_input = teacher_client.post(
        start_url,
        data=json.dumps({"different": True}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=key,
    )

    assert changed_input.status_code == 409
