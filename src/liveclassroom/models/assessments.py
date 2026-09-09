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


class AssessmentSection(models.Model):
    """An ordered group of fixed items and/or frozen question pools."""

    key = models.UUIDField(default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(
        AssessmentDefinition, on_delete=models.CASCADE, related_name="sections"
    )
    title = models.CharField(max_length=200)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(fields=["assessment", "key"], name="lc_assessment_section_key_once"),
            models.UniqueConstraint(
                fields=["assessment", "position"], name="lc_assessment_section_position_once"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.assessment}: {self.title}"


class AssessmentSectionEntry(models.Model):
    """A fixed assessment item or a question-bank sampling rule."""

    class Kind(models.TextChoices):
        FIXED = "fixed", "Fixed question"
        POOL = "pool", "Question pool"

    key = models.UUIDField(default=uuid.uuid4, editable=False)
    section = models.ForeignKey(AssessmentSection, on_delete=models.CASCADE, related_name="entries")
    position = models.PositiveIntegerField()
    kind = models.CharField(max_length=12, choices=Kind.choices)
    item = models.ForeignKey(
        AssessmentItem,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="section_entries",
    )
    bank = models.ForeignKey(
        "liveclassroom.QuestionBank",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assessment_pool_entries",
    )
    filters = models.JSONField(default=dict, blank=True)
    sample_size = models.PositiveIntegerField(null=True, blank=True)
    points = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    shuffle_options = models.BooleanField(default=False)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(fields=["section", "key"], name="lc_assessment_section_entry_key_once"),
            models.UniqueConstraint(
                fields=["section", "position"], name="lc_assessment_section_entry_position_once"
            ),
            models.UniqueConstraint(fields=["section", "item"], name="lc_assessment_section_fixed_item_once"),
        ]

    def __str__(self) -> str:
        return f"{self.section}: {self.position}"


class AssessmentRun(models.Model):
    """A published, immutable copy of one assessment draft.

    The JSON manifest deliberately contains the exact question revision content
    used at publication time.  The optional source link is provenance only and
    is never read when an attempt is delivered.
    """

    class Audience(models.TextChoices):
        AUTHENTICATED_LINK = "authenticated_link", "Authenticated link"
        CLASS = "class", "Class"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="liveclassroom_assessment_runs"
    )
    source_assessment = models.ForeignKey(
        AssessmentDefinition, null=True, blank=True, on_delete=models.SET_NULL, related_name="published_runs"
    )
    source_version = models.PositiveIntegerField()
    course = models.ForeignKey(
        "liveclassroom.Course", null=True, blank=True, on_delete=models.SET_NULL, related_name="assessment_runs"
    )
    audience = models.CharField(max_length=32, choices=Audience.choices)
    title = models.CharField(max_length=200)
    manifest = models.JSONField(default=dict)
    assets = models.ManyToManyField(
        "liveclassroom.ClassroomAsset", through="AssessmentRunAsset", related_name="assessment_runs"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["owner", "created_at"], name="liveclassro_owner_i_b6e114_idx"),
            models.Index(fields=["public_id"], name="liveclassro_public__15942a_idx"),
        ]

    def __str__(self) -> str:
        return self.title


class AssessmentRunAsset(models.Model):
    """Protected retained local content referenced by an assessment run."""

    run = models.ForeignKey(AssessmentRun, on_delete=models.CASCADE, related_name="asset_links")
    asset = models.ForeignKey(
        "liveclassroom.ClassroomAsset", on_delete=models.PROTECT, related_name="assessment_run_links"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "asset"], name="lc_assessment_run_asset_once")]
