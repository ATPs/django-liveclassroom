import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import Deck
from liveclassroom.services.classroom import ClassroomError
from liveclassroom.services.decks import copy_deck, create_deck, replace_deck_slides


@pytest.mark.django_db
def test_deck_reorder_copy_and_stale_version_are_atomic():
    teacher = get_user_model().objects.create_user(username="deck-owner")
    deck = create_deck(
        actor=teacher,
        data={"title": "Cells", "slides": [{"markdown": "# One", "notes": "private"}, {"markdown": "# Two"}]},
    )
    old_keys = [str(slide.key) for slide in deck.slides.all()]
    changed = replace_deck_slides(
        actor=teacher,
        deck=deck,
        expected_version=1,
        slides=[
            {"key": old_keys[1], "markdown": "# Two"},
            {"key": old_keys[0], "markdown": "# One", "notes": "private"},
        ],
    )
    assert changed.version == 2
    assert [slide.markdown for slide in changed.slides.all()] == ["# Two", "# One"]
    with pytest.raises(ClassroomError, match="changed"):
        replace_deck_slides(actor=teacher, deck=changed, expected_version=1, slides=[])
    copied = copy_deck(actor=teacher, deck=changed)
    assert copied.pk != changed.pk
    assert [slide.markdown for slide in copied.slides.all()] == ["# Two", "# One"]
    assert {slide.key for slide in copied.slides.all()}.isdisjoint({slide.key for slide in changed.slides.all()})


@pytest.mark.django_db
def test_deck_api_keeps_notes_owner_only():
    users = get_user_model()
    owner = users.objects.create_user(username="deck-api-owner")
    other = users.objects.create_user(username="deck-api-other")
    client = Client()
    client.force_login(owner)
    response = client.post(
        reverse("liveclassroom:api-v1-decks"),
        data=json.dumps({"title": "Deck", "slides": [{"markdown": "# Intro", "notes": "Do not show"}]}),
        content_type="application/json",
    )
    assert response.status_code == 201
    deck_id = response.json()["id"]
    assert response.json()["slides"][0]["notes"] == "Do not show"
    listed = client.get(reverse("liveclassroom:api-v1-decks")).json()["decks"]
    assert "notes" not in listed[0]["slides"][0]
    intruder = Client()
    intruder.force_login(other)
    assert intruder.get(reverse("liveclassroom:api-v1-deck-detail", args=[deck_id])).status_code == 404
    assert Deck.objects.filter(pk=deck_id).exists()
