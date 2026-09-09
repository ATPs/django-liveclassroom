"""Immutable native-deck delivery snapshots.

Snapshots deliberately copy the slide manifest instead of reading the mutable
deck draft at delivery time.  Native assets are retained through protected
links; host-managed external references keep their own access semantics.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from django.db import transaction

from liveclassroom.models import Deck, DeckSnapshot, DeckSnapshotAsset

from .classroom import ClassroomError
from .decks import _owner


def snapshot_fingerprint(*, public_manifest: list[dict], private_notes: dict[str, str], theme: str) -> str:
    """Return a deterministic content signature for an immutable delivery."""
    value = {"public_manifest": public_manifest, "private_notes": private_notes, "theme": theme}
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def deck_snapshot_payload(snapshot: DeckSnapshot, *, include_private: bool = False) -> dict:
    """Serialize only delivery-safe fields unless teacher-private data is requested."""
    payload = {
        "id": snapshot.id,
        "source_deck_id": snapshot.source_deck_id,
        "source_version": snapshot.source_version,
        "title": snapshot.title,
        "theme": snapshot.theme,
        "slides": deepcopy(snapshot.public_manifest),
        "fingerprint": snapshot.fingerprint,
    }
    if include_private:
        payload["private_notes"] = deepcopy(snapshot.private_notes)
    return payload


@transaction.atomic
def create_deck_snapshot(*, actor, deck: Deck, expected_version: int) -> DeckSnapshot:
    """Freeze a currently owned deck and retain every local asset it uses."""
    _owner(actor, deck)
    locked = Deck.objects.select_for_update().prefetch_related("slides__assets").get(pk=deck.pk)
    if (
        isinstance(expected_version, bool)
        or not isinstance(expected_version, int)
        or expected_version != locked.version
    ):
        raise ClassroomError("The deck changed; refresh before delivering it.")

    public_manifest: list[dict] = []
    private_notes: dict[str, str] = {}
    assets = []
    seen_assets = set()
    for slide in locked.slides.all():
        key = str(slide.key)
        asset_ids = []
        for asset in slide.assets.all():
            # Deck editing already validated ownership.  Repeat that condition
            # here so direct ORM-created decks never turn a foreign asset into
            # a retained delivery resource.
            if asset.owner_id != actor.pk and not getattr(actor, "is_superuser", False):
                raise ClassroomError("You do not have permission to retain this asset.")
            asset_ids.append(str(asset.public_id))
            if asset.pk not in seen_assets:
                assets.append(asset)
                seen_assets.add(asset.pk)
        public_manifest.append(
            {"key": key, "position": slide.position, "markdown": slide.markdown, "asset_ids": asset_ids}
        )
        if slide.notes:
            private_notes[key] = slide.notes

    snapshot = DeckSnapshot.objects.create(
        source_deck=locked,
        source_version=locked.version,
        title=locked.title,
        theme=locked.theme,
        public_manifest=deepcopy(public_manifest),
        private_notes=deepcopy(private_notes),
        fingerprint=snapshot_fingerprint(
            public_manifest=public_manifest, private_notes=private_notes, theme=locked.theme
        ),
    )
    DeckSnapshotAsset.objects.bulk_create(
        [DeckSnapshotAsset(snapshot=snapshot, asset=asset) for asset in assets]
    )
    return snapshot
