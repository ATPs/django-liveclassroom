import pytest
from django.test import Client
from django.urls import reverse

from liveclassroom.services.classroom import create_instant_session, start_session
from liveclassroom.services.deck_snapshots import create_deck_snapshot
from liveclassroom.services.decks import create_deck
from liveclassroom.services.presentation import present_deck


@pytest.fixture
def teacher(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="deck-browser-teacher")


@pytest.mark.django_db
def test_admitted_participant_can_read_only_the_active_snapshot_payload(teacher):
    deck = create_deck(actor=teacher, data={"title": "Live deck", "slides": [{"markdown": "# Welcome"}]})
    snapshot = create_deck_snapshot(actor=teacher, deck=deck, expected_version=1)
    session = create_instant_session(owner=teacher, title="Live deck class")
    start_session(session=session, actor=teacher)
    present_deck(session=session, actor=teacher, snapshot=snapshot, channels=["participants"])

    participant_client = Client()
    joined = participant_client.post(
        reverse("liveclassroom:api-v1-join", args=[session.join_code]),
        data={"display_name": "Learner"},
        content_type="application/json",
    )
    assert joined.status_code == 201
    payload = participant_client.get(
        reverse("liveclassroom:api-v1-session-deck-payload", args=[session.id, snapshot.id]),
        {"channel": "participants"},
    )
    assert payload.status_code == 200
    assert payload.json()["slides"][0]["markdown"] == "# Welcome"

    stranger = Client()
    assert stranger.get(
        reverse("liveclassroom:api-v1-session-deck-payload", args=[session.id, snapshot.id]),
        {"channel": "participants"},
    ).status_code == 404
