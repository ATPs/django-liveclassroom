"""Independent authenticated assessment attempts and fixed item assignments."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class AssessmentAttempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        SUBMITTED = "submitted", "Submitted"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    run = models.ForeignKey("liveclassroom.AssessmentRun", on_delete=models.PROTECT, related_name="attempts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="liveclassroom_attempts")
    attempt_number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(auto_now_add=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    finalization_reason = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ("run", "user", "attempt_number")
        constraints = [
            models.UniqueConstraint(fields=["run", "user", "attempt_number"], name="lc_attempt_number_once"),
            models.UniqueConstraint(
                fields=["run", "user"], condition=Q(status="in_progress"), name="lc_one_active_attempt"
            ),
        ]


class AssessmentAttemptItem(models.Model):
    attempt = models.ForeignKey(AssessmentAttempt, on_delete=models.CASCADE, related_name="items")
    key = models.UUIDField(default=uuid.uuid4, editable=False)
    position = models.PositiveIntegerField()
    points = models.DecimalField(max_digits=16, decimal_places=6)
    manifest = models.JSONField(default=dict)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(fields=["attempt", "key"], name="lc_attempt_item_key_once"),
            models.UniqueConstraint(fields=["attempt", "position"], name="lc_attempt_item_position_once"),
        ]


class AttemptStartReceipt(models.Model):
    """Replay a start/new-attempt command without allocating another attempt."""

    run = models.ForeignKey("liveclassroom.AssessmentRun", on_delete=models.CASCADE, related_name="start_receipts")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="liveclassroom_attempt_start_receipts"
    )
    request_id = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    attempt = models.ForeignKey(AssessmentAttempt, null=True, on_delete=models.SET_NULL, related_name="start_receipts")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "user", "request_id"], name="lc_attempt_start_receipt_once")
        ]


class AnswerRevision(models.Model):
    """One immutable answer saved for an assessment attempt item.

    Revisions are deliberately separate from the assignment manifest.  The
    latest row is the current answer, while every earlier row remains
    available to finalization and audit code.  Saves and finalization acquire
    the attempt lock before this item lock.
    """

    item = models.ForeignKey(
        AssessmentAttemptItem, on_delete=models.CASCADE, related_name="answer_revisions"
    )
    version = models.PositiveIntegerField()
    answer = models.JSONField(default=dict)
    request_id = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liveclassroom_answer_revisions",
    )
    saved_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("item", "version")
        constraints = [
            models.UniqueConstraint(fields=["item", "version"], name="lc_answer_revision_once"),
        ]
        indexes = [models.Index(fields=["item", "version"], name="lc_answer_item_version_idx")]

    def __str__(self) -> str:
        return f"{self.item_id}: answer v{self.version}"


class AttemptAnswerReceipt(models.Model):
    """The idempotent result of one attempt answer command.

    Request IDs are scoped to an attempt, so a lost response can be retried
    after later answers have been written without creating another revision.
    """

    attempt = models.ForeignKey(
        AssessmentAttempt, on_delete=models.CASCADE, related_name="answer_receipts"
    )
    request_id = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    revision = models.ForeignKey(
        AnswerRevision, on_delete=models.CASCADE, related_name="request_receipts"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "request_id"], name="lc_attempt_answer_receipt_once"
            )
        ]
