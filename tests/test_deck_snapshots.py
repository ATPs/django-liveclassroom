import pytest
from django.contrib.auth import get_user_model

from liveclassroom.models import ClassroomAsset, DeckSnapshot
from liveclassroom.services.classroom import ClassroomError
from liveclassroom.services.deck_snapshots import create_deck_snapshot, deck_snapshot_payload
from liveclassroom.services.decks import create_deck, replace_deck_slides


@pytest.mark.django_db
def test_deck_snapshot_retains_manifest_and_keeps_notes_private():
    teacher = get_user_model().objects.create_user(username="snapshot-owner")
    asset = ClassroomAsset.objects.create(
        owner=teacher,
        source="upload",
        original_name="diagram.png",
        kind="video",
        content_type="video/mp4",
        byte_size=4,
    )
    deck = create_deck(
        actor=teacher,
        data={
            "title": "Cells",
            "theme": "light",
            "slides": [{"markdown": "# A", "notes": "say this", "asset_ids": [str(asset.public_id)]}],
        },
    )
    first = create_deck_snapshot(actor=teacher, deck=deck, expected_version=1)
    replace_deck_slides(actor=teacher, deck=deck, expected_version=1, slides=[{"markdown": "# Changed"}])
    second = create_deck_snapshot(actor=teacher, deck=deck, expected_version=2)

    assert first.public_manifest[0]["markdown"] == "# A"
    assert second.public_manifest[0]["markdown"] == "# Changed"
    assert list(first.assets.all()) == [asset]
    public = deck_snapshot_payload(first)
    assert "say this" not in str(public)
    assert deck_snapshot_payload(first, include_private=True)["private_notes"]
    deck.delete()
    first.refresh_from_db()
    assert first.source_deck_id is None
    assert first.assets.get() == asset


@pytest.mark.django_db
def test_deck_snapshot_requires_current_owned_deck_and_is_fingerprinted():
    users = get_user_model()
    owner = users.objects.create_user(username="snapshot-owner-two")
    other = users.objects.create_user(username="snapshot-other")
    deck = create_deck(actor=owner, data={"title": "Deck", "slides": []})
    with pytest.raises(ClassroomError, match="permission"):
        create_deck_snapshot(actor=other, deck=deck, expected_version=1)
    with pytest.raises(ClassroomError, match="changed"):
        create_deck_snapshot(actor=owner, deck=deck, expected_version=2)
    snapshot = create_deck_snapshot(actor=owner, deck=deck, expected_version=1)
    assert len(snapshot.fingerprint) == 64
    assert DeckSnapshot.objects.filter(fingerprint=snapshot.fingerprint).exists()
