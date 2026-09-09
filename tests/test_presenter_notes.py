"""Teacher-only retained presenter notes and bounded deck themes."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.services.classroom import ClassroomError, create_instant_session, start_session
from liveclassroom.services.deck_snapshots import create_deck_snapshot
from liveclassroom.services.decks import create_deck, replace_deck_slides
from liveclassroom.services.presentation import present_deck


@pytest.mark.django_db
def test_presenter_notes_are_retained_and_teacher_only():
    users = get_user_model()
    teacher = users.objects.create_user(username="presenter-notes-teacher")
    other = users.objects.create_user(username="presenter-notes-other")
    deck = create_deck(
        actor=teacher,
        data={
            "title": "Cell lecture",
            "theme": "dark",
            "slides": [
                {"markdown": "# Public", "notes": "Mention the diagram."},
                {"markdown": "# Next", "notes": "Ask for a prediction."},
            ],
        },
    )
    snapshot = create_deck_snapshot(actor=teacher, deck=deck, expected_version=1)
    session = create_instant_session(owner=teacher, title="Notes classroom")
    start_session(session=session, actor=teacher)
    present_deck(session=session, actor=teacher, snapshot=snapshot, channels=["display"])

    teacher_client = Client()
    teacher_client.force_login(teacher)
    notes_url = reverse("liveclassroom:api-v1-session-deck-notes", args=[session.id, snapshot.id])
    notes = teacher_client.get(notes_url)
    assert notes.status_code == 200
    assert notes.json()["notes"][0]["notes"] == "Mention the diagram."
    assert "Cache-Control" in notes.headers

    payload = teacher_client.get(
        reverse("liveclassroom:api-v1-session-deck-payload", args=[session.id, snapshot.id]),
        {"channel": "display"},
    )
    assert payload.status_code == 200
    assert "Mention the diagram." not in payload.content.decode()

    other_client = Client()
    other_client.force_login(other)
    assert other_client.get(notes_url).status_code == 404

    participant_client = Client()
    joined = participant_client.post(
        reverse("liveclassroom:api-v1-join", args=[session.join_code]),
        data={"display_name": "Learner"},
        content_type="application/json",
    )
    assert joined.status_code == 201
    assert participant_client.get(notes_url, {"channel": "participants"}).status_code == 404

    # A later draft edit cannot rewrite the delivered private notes.
    replace_deck_slides(
        actor=teacher,
        deck=deck,
        expected_version=1,
        slides=[{"markdown": "# Changed", "notes": "Changed source notes."}],
    )
    notes_again = teacher_client.get(notes_url)
    assert notes_again.json()["notes"][0]["notes"] == "Mention the diagram."


@pytest.mark.django_db
def test_deck_theme_is_allowlisted_and_frozen_in_preview_document():
    teacher = get_user_model().objects.create_user(username="theme-teacher")
    deck = create_deck(actor=teacher, data={"title": "Themed", "theme": "dark", "slides": [{"markdown": "# One"}]})
    assert deck.theme == "dark"
    with pytest.raises(ClassroomError, match="theme"):
        create_deck(actor=teacher, data={"title": "Unsafe", "theme": "custom-css", "slides": []})

    from liveclassroom.deck_views import deck_preview_document

    document = deck_preview_document(deck)
    assert "slides: true" in document
    assert "theme: dark" in document
    assert document.endswith("# One")
