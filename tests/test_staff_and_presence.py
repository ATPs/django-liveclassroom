import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import Participant, ParticipantConnection, SessionEvent, SessionStaff
from liveclassroom.services.classroom import (
    create_instant_session,
    mark_participant_connected,
    mark_participant_disconnected,
)


def post_json(client, url, payload=None, **headers):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json", **headers)


@pytest.mark.django_db
def test_staff_assignment_exposes_capabilities_and_keeps_audit_history():
    user_model = get_user_model()
    teacher = user_model.objects.create_user(username="staff-owner")
    assistant = user_model.objects.create_user(username="staff-assistant")
    session = create_instant_session(owner=teacher, title="Staff roles")
    client = Client()
    client.force_login(teacher)

    assign_url = reverse("liveclassroom:api-v1-staff-assign", args=[session.id])
    assigned = post_json(client, assign_url, {"user_id": assistant.id, "role": "assistant"})

    assert assigned.status_code == 201
    assert assigned.json()["capabilities"] == ["manage_admission", "moderate_chat", "view_analytics"]
    staff_url = reverse("liveclassroom:api-v1-staff", args=[session.id])
    assert client.get(staff_url).json()["my_capabilities"] == [
        "manage_session",
        "manage_staff",
        "manage_admission",
        "view_display",
        "view_analytics",
    ]
    assignment = SessionStaff.objects.get(session=session, user=assistant)
    removed = post_json(client, reverse("liveclassroom:api-v1-staff-remove", args=[session.id, assignment.id]))
    assert removed.status_code == 200
    assert not SessionStaff.objects.filter(pk=assignment.id).exists()
    event_types = SessionEvent.objects.filter(session=session, event_type__startswith="staff.").values_list(
        "event_type", flat=True
    )
    assert list(event_types) == [
        "staff.assigned",
        "staff.removed",
    ]


@pytest.mark.django_db
def test_assistant_cannot_manage_staff_but_can_view_own_capabilities():
    user_model = get_user_model()
    teacher = user_model.objects.create_user(username="staff-permission-owner")
    assistant = user_model.objects.create_user(username="staff-permission-assistant")
    target = user_model.objects.create_user(username="staff-permission-target")
    session = create_instant_session(owner=teacher, title="Staff permissions")
    SessionStaff.objects.create(session=session, user=assistant, role=SessionStaff.Role.ASSISTANT)
    client = Client()
    client.force_login(assistant)

    listed = client.get(reverse("liveclassroom:api-v1-staff", args=[session.id]))
    assert listed.status_code == 200
    assert listed.json()["my_capabilities"] == ["manage_admission", "moderate_chat", "view_analytics"]
    denied = post_json(
        client,
        reverse("liveclassroom:api-v1-staff-assign", args=[session.id]),
        {"user_id": target.id, "role": "observer"},
    )
    assert denied.status_code == 403


@pytest.mark.django_db
def test_one_websocket_disconnect_leaves_another_connection_online():
    teacher = get_user_model().objects.create_user(username="presence-owner")
    session = create_instant_session(owner=teacher, title="Presence")
    participant = Participant.objects.create(session=session, guest_id="presence-guest", display_name="Ada")

    mark_participant_connected(participant=participant, connection_id="tab-a")
    mark_participant_connected(participant=participant, connection_id="tab-b")
    mark_participant_disconnected(participant=participant, connection_id="tab-a")
    participant.refresh_from_db()

    assert participant.disconnected_at is None
    assert ParticipantConnection.objects.filter(participant=participant, disconnected_at__isnull=True).count() == 1
    mark_participant_disconnected(participant=participant, connection_id="tab-b")
    participant.refresh_from_db()
    assert participant.disconnected_at is not None
