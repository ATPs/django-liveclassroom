"""Durable, mutable result-release decisions for immutable assessment runs."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class AssessmentResultRelease(models.Model):
    """Current release state for one run/dimension or one attempt/dimension.

    A null ``attempt`` is a run-wide decision.  Release metadata is kept out
    of ``AssessmentRun.manifest`` so publishing remains an immutable content
    operation.  The actor and timestamp are retained for an audit trail.
    """

    class Dimension(models.TextChoices):
        SCORES = "scores", "Scores"
        ANSWERS = "answers", "Answers"
        EXPLANATIONS = "explanations", "Explanations"
        COMMENTS = "comments", "Comments"

    run = models.ForeignKey(
        "liveclassroom.AssessmentRun",
        on_delete=models.CASCADE,
        related_name="result_releases",
    )
    attempt = models.ForeignKey(
        "liveclassroom.AssessmentAttempt",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="result_releases",
    )
    dimension = models.CharField(max_length=20, choices=Dimension.choices)
    released = models.BooleanField(default=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liveclassroom_result_releases",
    )
    released_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("run", "attempt", "dimension", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["run", "dimension"],
                condition=Q(attempt__isnull=True),
                name="lc_result_release_run_once",
            ),
            models.UniqueConstraint(
                fields=["run", "attempt", "dimension"],
                condition=Q(attempt__isnull=False),
                name="lc_result_release_attempt_once",
            ),
        ]

    def __str__(self) -> str:
        target = f"attempt {self.attempt_id}" if self.attempt_id else f"run {self.run_id}"
        return f"{self.dimension} release for {target}"


# Short vocabulary for integrations and tests that use the contract name.
ResultRelease = AssessmentResultRelease


__all__ = ["AssessmentResultRelease", "ResultRelease"]
