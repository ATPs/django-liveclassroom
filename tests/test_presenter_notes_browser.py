"""HTTP/browser-boundary checks for presenter note secrecy."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.services.classroom import create_instant_session, start_session
from liveclassroom.services.deck_snapshots import create_deck_snapshot
from liveclassroom.services.decks import create_deck
from liveclassroom.services.presentation import present_deck


@pytest.mark.django_db
def test_public_state_contains_teacher_notes_url_but_no_notes():
    owner = get_user_model().objects.create_user(username="notes-state-owner")
    deck = create_deck(actor=owner, data={"title": "State", "slides": [{"markdown": "# Visible", "notes": "Private"}]})
    snapshot = create_deck_snapshot(actor=owner, deck=deck, expected_version=1)
    session = create_instant_session(owner=owner, title="State classroom")
    start_session(session=session, actor=owner)
    present_deck(session=session, actor=owner, snapshot=snapshot, channels=["display", "participants"])
    client = Client()
    client.force_login(owner)
    state = client.get(reverse("liveclassroom:api-v1-state", args=[session.id]), {"channel": "display"})
    assert state.status_code == 200
    current = state.json()["current_deck"]
    assert current["notes_url"].startswith("/api/")
    assert "Private" not in state.content.decode()

    participant = Client()
    assert participant.post(
        reverse("liveclassroom:api-v1-join", args=[session.join_code]),
        data={"display_name": "Learner"},
        content_type="application/json",
    ).status_code == 201
    student_state = participant.get(
        reverse("liveclassroom:api-v1-state", args=[session.id]), {"channel": "participants"}
    )
    assert student_state.status_code == 200
    student_deck = student_state.json()["current_deck"]
    assert "notes_url" not in student_deck
    assert "Private" not in student_state.content.decode()
