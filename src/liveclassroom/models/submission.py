from django.db import models

from .session import LiveActivity, Participant


class Submission(models.Model):
    activity = models.ForeignKey(LiveActivity, on_delete=models.CASCADE, related_name="submissions")
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="submissions")
    answer = models.JSONField(default=dict)
    attempt = models.PositiveSmallIntegerField(default=1)
    score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    response_ms = models.PositiveIntegerField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    current_revision = models.ForeignKey(
        "liveclassroom.SubmissionRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for_submissions",
    )
    is_stale = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["activity", "participant", "attempt"], name="lc_submission_attempt")
        ]
        ordering = ["activity", "participant", "attempt"]

    def __str__(self) -> str:
        return f"{self.participant} → {self.activity} (attempt {self.attempt})"


class SubmissionRevision(models.Model):
    """An immutable answer update, including the exact activity revision answered."""

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="revisions")
    revision = models.PositiveIntegerField()
    activity_revision = models.ForeignKey(
        "liveclassroom.ActivityRunRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submission_revisions",
    )
    answer = models.JSONField(default=dict)
    score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    response_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["submission", "revision"]
        constraints = [models.UniqueConstraint(fields=["submission", "revision"], name="lc_submission_revision_once")]
