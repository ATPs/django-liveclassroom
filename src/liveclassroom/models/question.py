from django.db import models


class Question(models.Model):
    class Type(models.TextChoices):
        SINGLE_CHOICE = "single_choice", "Single choice"
        MULTIPLE_CHOICE = "multiple_choice", "Multiple choice"
        TRUE_FALSE = "true_false", "True / false"
        POLL = "poll", "Poll"
        SHORT_TEXT = "short_text", "Short text"

    schema_version = models.PositiveSmallIntegerField(default=1)
    question_type = models.CharField(max_length=32, choices=Type.choices)
    stem_markdown = models.TextField()
    data = models.JSONField(default=dict, help_text="Versioned display definition, such as choices.")
    answer = models.JSONField(default=list, blank=True)
    explanation_markdown = models.TextField(blank=True)
    difficulty = models.PositiveSmallIntegerField(null=True, blank=True)
    tags = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=32, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.stem_markdown[:80]
