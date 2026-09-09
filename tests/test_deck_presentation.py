import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import DeckSnapshot
from liveclassroom.services.classroom import ClassroomError, create_instant_session, start_session
from liveclassroom.services.deck_snapshots import create_deck_snapshot
from liveclassroom.services.decks import create_deck
from liveclassroom.services.presentation import present_deck, update_deck_presentation


@pytest.fixture
def teacher(db):
    return get_user_model().objects.create_user(username="deck-present-teacher")


def _snapshot(teacher):
    deck = create_deck(
        actor=teacher,
        data={
            "title": "Cell lecture",
            "slides": [
                {"markdown": "# Diagram", "notes": "Keep private"},
                {"markdown": "# Question", "notes": "Ask for a prediction"},
            ],
        },
    )
    return create_deck_snapshot(actor=teacher, deck=deck, expected_version=1)


@pytest.mark.django_db
def test_native_deck_has_independent_audience_positions(teacher):
    snapshot = _snapshot(teacher)
    session = create_instant_session(owner=teacher, title="Deck classroom")
    start_session(session=session, actor=teacher)

    display = present_deck(session=session, actor=teacher, snapshot=snapshot, channels=["display"])
    participant = present_deck(session=session, actor=teacher, snapshot=snapshot, channels=["participants"])
    assert display["slide_index"] == 0
    assert participant["slide_key"] == display["slide_key"]

    moved = update_deck_presentation(
        session=session,
        actor=teacher,
        channels=["display"],
        action="next",
        expected_revision=display["revision"],
    )
    assert moved["slide_index"] == 1
    session.refresh_from_db()
    assert session.creation_settings["native_deck_presentations"]["participants"]["slide_index"] == 0


@pytest.mark.django_db
def test_native_deck_rejects_stale_navigation_and_keeps_snapshot_content(teacher):
    snapshot = _snapshot(teacher)
    session = create_instant_session(owner=teacher, title="Deck classroom")
    start_session(session=session, actor=teacher)
    current = present_deck(session=session, actor=teacher, snapshot=snapshot)
    update_deck_presentation(
        session=session,
        actor=teacher,
        channels=["display"],
        action="next",
        expected_revision=current["revision"],
    )
    with pytest.raises(ClassroomError, match="changed"):
        update_deck_presentation(
            session=session,
            actor=teacher,
            channels=["display"],
            action="previous",
            expected_revision=current["revision"],
        )
    assert snapshot.public_manifest[0]["markdown"] == "# Diagram"
    assert "Keep private" not in str(snapshot.public_manifest)


@pytest.mark.django_db
def test_deck_presentation_api_state_and_public_payload(teacher):
    snapshot = _snapshot(teacher)
    session = create_instant_session(owner=teacher, title="Deck classroom")
    start_session(session=session, actor=teacher)
    client = Client()
    client.force_login(teacher)
    response = client.post(
        reverse("liveclassroom:api-v1-session-presentation", args=[session.id]),
        data={"snapshot_id": snapshot.id, "channels": ["display"]},
        content_type="application/json",
    )
    assert response.status_code == 200
    state = client.get(reverse("liveclassroom:api-v1-state", args=[session.id]), {"channel": "display"}).json()
    assert state["current_activity"] is None
    assert state["current_deck"]["snapshot_id"] == snapshot.id
    assert state["current_deck"]["payload_url"].startswith("/api/")
    payload = client.get(
        reverse("liveclassroom:api-v1-session-deck-payload", args=[session.id, snapshot.id]),
        {"channel": "display"},
    )
    assert payload.status_code == 200
    assert payload.json()["slides"][0]["markdown"] == "# Diagram"
    assert "Keep private" not in payload.content.decode()


@pytest.mark.django_db
def test_foreign_teacher_cannot_present_snapshot(teacher):
    other = get_user_model().objects.create_user(username="deck-present-other")
    snapshot = _snapshot(teacher)
    session = create_instant_session(owner=other, title="Other classroom")
    start_session(session=session, actor=other)
    with pytest.raises(ClassroomError, match="permission"):
        present_deck(session=session, actor=other, snapshot=snapshot)
    assert DeckSnapshot.objects.filter(pk=snapshot.pk).exists()
