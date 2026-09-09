"""Native reusable deck definitions, ordered slides, and explicit asset links."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Deck(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="liveclassroom_decks")
    course = models.ForeignKey(
        "liveclassroom.Course", null=True, blank=True, on_delete=models.SET_NULL, related_name="decks"
    )
    title = models.CharField(max_length=200)
    theme = models.CharField(max_length=80, default="default")
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        indexes = [models.Index(fields=["owner", "updated_at"])]

    def __str__(self) -> str:
        return self.title


class DeckSlide(models.Model):
    deck = models.ForeignKey(Deck, on_delete=models.CASCADE, related_name="slides")
    key = models.UUIDField(default=uuid.uuid4, editable=False)
    position = models.PositiveIntegerField()
    markdown = models.TextField()
    notes = models.TextField(blank=True)
    assets = models.ManyToManyField(
        "liveclassroom.ClassroomAsset", through="DeckSlideAsset", related_name="deck_slides"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(fields=["deck", "key"], name="lc_deck_slide_key_once"),
            models.UniqueConstraint(fields=["deck", "position"], name="lc_deck_slide_position_once"),
        ]


class DeckSlideAsset(models.Model):
    slide = models.ForeignKey(DeckSlide, on_delete=models.CASCADE, related_name="asset_links")
    asset = models.ForeignKey("liveclassroom.ClassroomAsset", on_delete=models.PROTECT, related_name="deck_slide_links")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["slide", "asset"], name="lc_deck_slide_asset_once")]
