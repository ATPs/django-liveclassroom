"""Public, read-only teaching examples shipped by a host installation."""

from django.db import models


class DemoLesson(models.Model):
    """One localized, reusable demo lesson and its representative classrooms.

    The teaching content itself remains ordinary ``Course``, ``Flow`` and
    ``LiveSession`` data.  This small registry is deliberately the only public
    marker: it lets a host expose examples without giving teachers permission
    to edit the common source records.
    """

    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        SIMPLIFIED_CHINESE = "zh-Hans", "Simplified Chinese"

    slug = models.SlugField(max_length=80)
    language = models.CharField(max_length=12, choices=Language.choices)
    title = models.CharField(max_length=200)
    course = models.ForeignKey("liveclassroom.Course", on_delete=models.PROTECT, related_name="demo_lessons")
    flow = models.OneToOneField("liveclassroom.Flow", on_delete=models.PROTECT, related_name="demo_lesson")
    ready_session = models.OneToOneField(
        "liveclassroom.LiveSession",
        on_delete=models.PROTECT,
        related_name="demo_ready_for",
    )
    live_session = models.OneToOneField(
        "liveclassroom.LiveSession",
        on_delete=models.PROTECT,
        related_name="demo_live_for",
    )
    ended_session = models.OneToOneField(
        "liveclassroom.LiveSession",
        on_delete=models.PROTECT,
        related_name="demo_ended_for",
    )
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["slug", "language"], name="lc_demo_lesson_slug_language"),
        ]
        ordering = ["slug", "language"]

    def __str__(self) -> str:
        return f"{self.title} ({self.language})"
