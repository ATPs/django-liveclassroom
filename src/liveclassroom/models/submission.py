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

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["activity", "participant", "attempt"], name="lc_submission_attempt")
        ]
        ordering = ["activity", "participant", "attempt"]

    def __str__(self) -> str:
        return f"{self.participant} → {self.activity} (attempt {self.attempt})"
