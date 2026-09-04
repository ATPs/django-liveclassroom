import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from liveclassroom.models import LiveSession, Participant, SessionEvent


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
    assert Participant.objects.filter(session=session).count() == 1

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
