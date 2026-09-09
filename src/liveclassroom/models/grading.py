"""Durable automatic grade results and append-only grade decisions.

The attempt and item grade rows are the current materialized result.  A
decision row is an immutable audit snapshot so later manual grading and
regrading can add a new decision without changing the submitted attempt or
an earlier decision.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class AssessmentAttemptGrade(models.Model):
    """Current aggregate for one finalized assessment attempt."""

    class Status(models.TextChoices):
        GRADED = "graded", "Graded"
        PENDING = "pending", "Pending"

    attempt = models.OneToOneField(
        "liveclassroom.AssessmentAttempt",
        on_delete=models.CASCADE,
        related_name="grade",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    possible_points = models.DecimalField(max_digits=16, decimal_places=6, default=0)
    awarded_points = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    graded_count = models.PositiveIntegerField(default=0)
    pending_count = models.PositiveIntegerField(default=0)
    ungraded_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_possible_points(self):
        return self.possible_points

    @property
    def total_awarded_points(self):
        return self.awarded_points

    def __str__(self) -> str:
        return f"Grade for attempt {self.attempt_id}"


class AssessmentItemGrade(models.Model):
    """The latest result for one immutable retained attempt item."""

    class Status(models.TextChoices):
        GRADED = "graded", "Graded"
        PENDING = "pending", "Pending"
        UNGRADED = "ungraded", "Ungraded"
        ERROR = "error", "Error"

    item = models.OneToOneField(
        "liveclassroom.AssessmentAttemptItem",
        on_delete=models.CASCADE,
        related_name="grade",
    )
    status = models.CharField(max_length=16, choices=Status.choices)
    normalized_score = models.DecimalField(
        max_digits=12, decimal_places=10, null=True, blank=True
    )
    possible_points = models.DecimalField(max_digits=16, decimal_places=6)
    awarded_points = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True
    )
    retained_answer = models.JSONField(null=True, blank=True)
    source = models.CharField(max_length=32, default="automatic")
    rule_version = models.CharField(max_length=100, default="activity-registry-v1")
    diagnostic_code = models.CharField(max_length=64, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    graded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def answer(self):
        """Compatibility vocabulary for callers that call the snapshot answer."""
        return self.retained_answer

    @property
    def attempt_item(self):
        return self.item

    def __str__(self) -> str:
        return f"Grade for attempt item {self.item_id}"


class AssessmentGradeDecision(models.Model):
    """Immutable record of each automatic or later grading decision."""

    attempt = models.ForeignKey(
        "liveclassroom.AssessmentAttempt",
        on_delete=models.CASCADE,
        related_name="grade_decisions",
    )
    item = models.ForeignKey(
        "liveclassroom.AssessmentAttemptItem",
        on_delete=models.CASCADE,
        related_name="grade_decisions",
    )
    status = models.CharField(max_length=16)
    normalized_score = models.DecimalField(
        max_digits=12, decimal_places=10, null=True, blank=True
    )
    possible_points = models.DecimalField(max_digits=16, decimal_places=6)
    awarded_points = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True
    )
    retained_answer = models.JSONField(null=True, blank=True)
    source = models.CharField(max_length=32, default="automatic")
    rule_version = models.CharField(max_length=100, default="activity-registry-v1")
    diagnostic_code = models.CharField(max_length=64, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liveclassroom_grade_decisions",
    )
    reason = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    @property
    def answer(self):
        return self.retained_answer

    @property
    def attempt_item(self):
        return self.item

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=["attempt", "created_at"], name="lc_grade_decision_attempt_idx"),
            models.Index(fields=["item", "created_at"], name="lc_grade_decision_item_idx"),
        ]

    def __str__(self) -> str:
        return f"Grade decision for attempt item {self.item_id}"


# Short names make the result vocabulary easy for task 32/33 integrations
# while retaining explicit model names for migrations and admin code.
AttemptGrade = AssessmentAttemptGrade
AttemptItemGrade = AssessmentItemGrade
GradeDecision = AssessmentGradeDecision


__all__ = [
    "AssessmentAttemptGrade",
    "AssessmentItemGrade",
    "AssessmentGradeDecision",
    "AttemptGrade",
    "AttemptItemGrade",
    "GradeDecision",
]
