import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import SessionEvent, SessionMessage, SessionStaff
from liveclassroom.services.classroom import create_instant_session, start_session


def post_json(client, url, payload=None, **headers):
    return client.post(
        url,
        data=json.dumps(payload or {}),
        content_type="application/json",
        **headers,
    )


@pytest.mark.django_db
def test_teacher_can_toggle_chat_and_students_receive_enabled_state(client):
    teacher = get_user_model().objects.create_user(username="chat-teacher")
    session = create_instant_session(owner=teacher, title="Chat controls")
    start_session(session=session, actor=teacher)
    student = Client()
    joined = post_json(student, reverse("liveclassroom:api-v1-join", args=[session.join_code]), {"display_name": "Ada"})
    assert joined.status_code == 201

    chat_url = reverse("liveclassroom:api-v1-chat-messages", args=[session.id])
    assert student.get(chat_url).json() == {"enabled": False, "messages": []}

    client.force_login(teacher)
    settings_url = reverse("liveclassroom:api-v1-chat-settings", args=[session.id])
    session.refresh_from_db()
    previous_version = session.state_version
    enabled = post_json(client, settings_url, {"enabled": True}, HTTP_IDEMPOTENCY_KEY="chat-enable-once")
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["version"] == previous_version + 1
    assert SessionEvent.objects.filter(session=session, event_type="chat.enabled").count() == 1

    assert student.get(chat_url).json()["enabled"] is True
    message = post_json(
        student,
        reverse("liveclassroom:api-v1-chat-send", args=[session.id]),
        {"body": "Hello"},
        HTTP_IDEMPOTENCY_KEY="chat-message-once",
    )
    assert message.status_code == 201

    disabled = post_json(client, settings_url, {"enabled": False})
    assert disabled.status_code == 200
    assert student.get(chat_url).json() == {"enabled": False, "messages": []}
    blocked = student.post(
        reverse("liveclassroom:api-v1-chat-send", args=[session.id]),
        data=json.dumps({"body": "Blocked"}),
        content_type="application/json",
    )
    assert blocked.json()["code"] == "chat_disabled"
    assert SessionMessage.objects.filter(session=session, body="Hello").exists()


@pytest.mark.django_db
def test_chat_toggle_allows_assistant_but_not_observer_and_uses_structured_errors(client):
    user_model = get_user_model()
    teacher = user_model.objects.create_user(username="chat-owner")
    assistant = user_model.objects.create_user(username="chat-assistant")
    observer = user_model.objects.create_user(username="chat-observer")
    session = create_instant_session(owner=teacher, title="Chat roles")
    SessionStaff.objects.create(session=session, user=assistant, role=SessionStaff.Role.ASSISTANT)
    SessionStaff.objects.create(session=session, user=observer, role=SessionStaff.Role.OBSERVER)
    settings_url = reverse("liveclassroom:api-v1-chat-settings", args=[session.id])

    client.force_login(assistant)
    assert post_json(client, settings_url, {"enabled": True}).status_code == 200
    client.force_login(observer)
    denied = post_json(client, settings_url, {"enabled": False})
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"
    client.force_login(teacher)
    malformed = post_json(client, settings_url, {"enabled": "yes"})
    assert malformed.status_code == 400
    assert malformed.json()["code"] == "invalid_request"
