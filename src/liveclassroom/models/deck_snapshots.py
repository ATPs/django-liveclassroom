"""Immutable retained native-deck delivery snapshots."""

from django.db import models


class DeckSnapshot(models.Model):
    source_deck = models.ForeignKey(
        "liveclassroom.Deck", null=True, blank=True, on_delete=models.SET_NULL, related_name="snapshots"
    )
    source_version = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    theme = models.CharField(max_length=80, default="default")
    public_manifest = models.JSONField(default=list)
    private_notes = models.JSONField(default=dict)
    fingerprint = models.CharField(max_length=64)
    assets = models.ManyToManyField(
        "liveclassroom.ClassroomAsset", through="DeckSnapshotAsset", related_name="deck_snapshots"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")


class DeckSnapshotAsset(models.Model):
    snapshot = models.ForeignKey(DeckSnapshot, on_delete=models.CASCADE, related_name="asset_links")
    asset = models.ForeignKey(
        "liveclassroom.ClassroomAsset", on_delete=models.PROTECT, related_name="deck_snapshot_links"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["snapshot", "asset"], name="lc_deck_snapshot_asset_once")]
