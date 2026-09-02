from django.db import models

from .course import Course
from .question import Question


class Flow(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="flows")
    title = models.CharField(max_length=200)
    slug = models.SlugField()
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["course", "slug"], name="lc_flow_slug_per_course")]
        ordering = ["course", "title"]

    def __str__(self) -> str:
        return f"{self.course}: {self.title}"


class FlowItem(models.Model):
    class Kind(models.TextChoices):
        MARKDOWN = "markdown", "Markdown"
        QUESTION = "question", "Question"
        POLL = "poll", "Poll"
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        URL = "url", "URL"
        IFRAME = "iframe", "IFrame"
        TIMER = "timer", "Timer"

    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveIntegerField()
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=200, blank=True)
    content = models.JSONField(default=dict, blank=True)
    question = models.ForeignKey(
        Question,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="flow_items",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["flow", "position"], name="lc_flow_item_position")]
        ordering = ["flow", "position"]

    def __str__(self) -> str:
        return f"{self.flow} #{self.position}: {self.kind}"
