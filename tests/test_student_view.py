import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from liveclassroom.models import LiveSession, Participant, ParticipantConnection, SessionEvent, SessionMessage
from liveclassroom.services.analytics import session_analytics
from liveclassroom.services.classroom import (
    create_activity_definition,
    create_instant_session,
    publish_activity_to_channel,
    start_session,
    submit_answer,
)
from liveclassroom.services.exports import csv_export, json_archive


@pytest.mark.django_db
def test_manager_can_inspect_then_explicitly_act_as_participant(client):
    user = get_user_model().objects.create_user(username="teacher", password="secret")
    session = LiveSession.objects.create(teacher=user, title="Live class")
    participant = Participant.objects.create(
        session=session,
        guest_id="student-1",
        display_name="Student One",
        admission_state=Participant.AdmissionState.ADMITTED,
    )
    client.force_login(user)

    page = client.get(reverse("liveclassroom:student-view", args=[session.id]))
    assert page.status_code == 200
    assert "preview=1" in page.content.decode()
    assert Participant.objects.filter(session=session).count() == 1

    preview = client.get(f"{reverse('liveclassroom:api-v1-state', args=[session.id])}?preview=1&channel=participants")
    assert preview.status_code == 200
    assert preview.json()["participant"] is None
    assert preview.json()["act_as_active"] is False

    roster = client.get(reverse("liveclassroom:api-v1-participants", args=[session.id])).json()["participants"]
    inspect_token = roster[0]["inspection_token"]
    state = client.get(
        f"{reverse('liveclassroom:api-v1-state', args=[session.id])}?act_as_token={inspect_token}"
    )
    assert state.status_code == 200
    assert state.json()["participant"]["id"] == participant.id
    assert state.json()["act_as_active"] is False

    activated = client.post(
        reverse("liveclassroom:api-v1-student-view-activate", args=[session.id]),
        data=json.dumps({"participant_id": participant.id, "confirm": True}),
        content_type="application/json",
    )
    assert activated.status_code == 200
    assert SessionEvent.objects.filter(
        session=session,
        event_type="participant.act_as.activated",
        actor=user,
        participant=participant,
    ).exists()


@pytest.mark.django_db
def test_test_student_is_reused_and_excluded_from_normal_results(client):
    teacher = get_user_model().objects.create_user(username="test-student-teacher")
    session = create_instant_session(owner=teacher, title="Test student class")
    definition = create_activity_definition(
        owner=teacher,
        title="A poll",
        type_key="liveclassroom.poll",
        definition={"options": [{"id": "yes", "text": "Yes"}]},
    )
    start_session(session=session, actor=teacher)
    from liveclassroom.services.classroom import launch_item

    activity = launch_item(session=session, item=definition, actor=teacher)
    publish_activity_to_channel(session=session, activity=activity, channel="participants", actor=teacher)
    client.force_login(teacher)
    url = reverse("liveclassroom:api-v1-test-student", args=[session.id])
    first = client.post(url, data="{}", content_type="application/json")
    second = client.post(url, data="{}", content_type="application/json")

    assert first.status_code == second.status_code == 200
    participant = Participant.objects.get(session=session, is_test=True)
    assert first.json()["participant"]["id"] == second.json()["participant"]["id"] == participant.id
    submit_answer(
        activity=activity,
        participant=participant,
        answer={"choice": "yes"},
        actor=teacher,
        activity_revision_id=activity.current_revision_id,
        require_published=True,
    )
    assert session_analytics(session)["attendance"]["total"] == 0
    assert session_analytics(session)["activities"][0]["submitted_count"] == 0
    ParticipantConnection.objects.create(participant=participant, connection_id="test-student-connection")
    assert session_analytics(session)["attendance"]["currently_connected"] == 0
    assert client.get(reverse("liveclassroom:api-v1-participants", args=[session.id])).json()["participants"] == []

    SessionMessage.objects.create(
        session=session,
        participant=participant,
        display_name=participant.display_name,
        body="test-only",
    )
    assert session_analytics(session)["chat"]["message_count"] == 0
    assert "test-only" not in "".join(json_archive(session))
    assert "test-only" not in "".join(csv_export(session, "chat"))
    token = first.json()["act_as_token"]
    chat = client.get(f"{reverse('liveclassroom:api-v1-chat-messages', args=[session.id])}?act_as_token={token}")
    assert chat.json() == {"enabled": False, "messages": []}

    events = SessionEvent.objects.filter(session=session, event_type="participant.act_as.activated")
    before_events = events.count()
    renewed = client.post(
        reverse("liveclassroom:api-v1-renew-test-student", args=[session.id]),
        data="{}",
        content_type="application/json",
    )
    assert renewed.status_code == 200
    assert renewed.json()["participant"]["id"] == participant.id
    assert events.count() == before_events
