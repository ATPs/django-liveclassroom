import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.deck_views import deck_preview_markdown
from liveclassroom.services.decks import create_deck


@pytest.mark.django_db
def test_deck_preview_uses_public_slides_only_and_owner_route():
    users = get_user_model()
    owner = users.objects.create_user(username="deck-preview-owner")
    other = users.objects.create_user(username="deck-preview-other")
    deck = create_deck(
        actor=owner,
        data={
            "title": "Cells",
            "slides": [
                {"markdown": "# Public", "notes": "do not show"},
                {"markdown": "# Second", "notes": "also private"},
            ],
        },
    )
    markdown = deck_preview_markdown(deck)
    assert markdown == "# Public\n\n---\n\n# Second"
    assert "private" not in markdown
    client = Client()
    client.force_login(other)
    assert client.get(reverse("liveclassroom:deck-preview", args=[deck.id])).status_code == 404


@pytest.mark.django_db
def test_owned_assets_list_is_private_to_teacher():
    users = get_user_model()
    owner = users.objects.create_user(username="deck-assets-owner")
    other = users.objects.create_user(username="deck-assets-other")
    owner_client = Client()
    owner_client.force_login(owner)
    assert owner_client.get(reverse("liveclassroom:api-v1-assets")).status_code == 200
    other_client = Client()
    other_client.force_login(other)
    assert other_client.get(reverse("liveclassroom:api-v1-assets")).json() == {"assets": []}
