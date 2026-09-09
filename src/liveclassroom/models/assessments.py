"""Reusable, fixed-question assessment drafts.

An assessment stores references to immutable activity revisions.  It is a
teacher authoring object; publication and student delivery copy those rows in
later tasks.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class AssessmentDefinition(models.Model):
    """A teacher-owned draft made from pinned activity revisions."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="liveclassroom_assessments",
    )
    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    course = models.ForeignKey(
        "liveclassroom.Course",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assessments",
    )
    version = models.PositiveIntegerField(default=1)
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        indexes = [models.Index(fields=["owner", "updated_at"])]

    def __str__(self) -> str:
        return self.title


class AssessmentItem(models.Model):
    """One ordered assessment question pinned to an immutable revision."""

    key = models.UUIDField(default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(AssessmentDefinition, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveIntegerField()
    question_revision = models.ForeignKey(
        "liveclassroom.ActivityDefinitionRevision",
        on_delete=models.PROTECT,
        related_name="assessment_items",
    )
    points = models.DecimalField(max_digits=16, decimal_places=6)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(fields=["assessment", "key"], name="lc_assessment_item_key_once"),
            models.UniqueConstraint(fields=["assessment", "position"], name="lc_assessment_item_position_once"),
        ]

    def __str__(self) -> str:
        return f"{self.assessment}: {self.position}"
