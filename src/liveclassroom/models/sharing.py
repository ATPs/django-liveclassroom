"""Explicit named grants for reusable authoring content."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ContentShare(models.Model):
    """One revocable grant to one exact reusable object.

    Resource IDs deliberately remain a validated scalar rather than a generic
    foreign key: only the four supported authoring resources are shareable.
    """

    class Kind(models.TextChoices):
        QUESTION = "question", "Question"
        BANK = "bank", "Question bank"
        DECK = "deck", "Deck"
        ASSESSMENT = "assessment", "Assessment"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="liveclassroom_content_shares_created"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="liveclassroom_content_shares_received"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    resource_id = models.PositiveBigIntegerField()
    source_fingerprint = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "recipient", "kind", "resource_id"),
                condition=Q(revoked_at__isnull=True),
                name="lc_content_share_active_once",
            ),
            models.CheckConstraint(condition=Q(resource_id__gt=0), name="lc_content_share_resource_positive"),
        ]
        indexes = [
            models.Index(fields=("recipient", "kind", "resource_id"), name="lc_content_share_read_idx"),
        ]

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def clean(self) -> None:
        if self.owner_id and self.owner_id == self.recipient_id:
            raise ValidationError({"recipient": "The owner already has access to this content."})


__all__ = ["ContentShare"]
