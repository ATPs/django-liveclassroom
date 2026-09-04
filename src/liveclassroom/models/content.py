from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver

from .activity import ActivityDefinition
from .course import Course
from .question import Question


class Flow(models.Model):
    course = models.ForeignKey(Course, null=True, blank=True, on_delete=models.SET_NULL, related_name="flows")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liveclassroom_flows_created",
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField()
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["course", "slug"], name="lc_flow_slug_per_course")]
        ordering = ["course", "title"]

    def __str__(self) -> str:
        return f"{self.course or 'Instant flow'}: {self.title}"


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
    activity_definition = models.ForeignKey(
        ActivityDefinition,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="legacy_flow_items",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["flow", "position"], name="lc_flow_item_position")]
        ordering = ["flow", "position"]

    def __str__(self) -> str:
        return f"{self.flow} #{self.position}: {self.kind}"

    def clean(self) -> None:
        if self.activity_definition_id and self.activity_definition.course_id:
            if self.flow_id and self.flow.course_id and self.activity_definition.course_id != self.flow.course_id:
                raise ValidationError({"activity_definition": "The activity must belong to the flow's course."})


class FlowStep(models.Model):
    """Modern flow ordering record; FlowItem remains for compatibility."""

    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name="steps")
    position = models.PositiveIntegerField()
    activity_definition = models.ForeignKey(
        ActivityDefinition,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="flow_steps",
    )
    kind = models.CharField(max_length=32, default="activity")
    title = models.CharField(max_length=200, blank=True)
    content = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["flow", "position"]
        constraints = [models.UniqueConstraint(fields=["flow", "position"], name="lc_flow_step_position")]

    def __str__(self) -> str:
        return f"{self.flow} step {self.position}: {self.kind}"

    def clean(self) -> None:
        if self.activity_definition_id and self.activity_definition.course_id:
            if self.flow_id and self.flow.course_id and self.activity_definition.course_id != self.flow.course_id:
                raise ValidationError({"activity_definition": "The activity must belong to the flow's course."})


_LEGACY_MEDIA_KINDS = frozenset({"image", "video", "url", "iframe"})


def _validate_legacy_media(kind: str, content: dict) -> dict:
    if kind not in _LEGACY_MEDIA_KINDS or not isinstance(content, dict):
        return content
    if content.get("media_disabled") is True:
        return content
    from liveclassroom.registry import activity_registry

    media_type = "iframe" if kind in {"url", "iframe"} else kind
    payload = {**content, "media_type": content.get("media_type", media_type)}
    return activity_registry.get("liveclassroom.media").validate(payload)


@receiver(pre_save, sender=FlowItem)
def validate_legacy_flow_item_media(sender, instance, **kwargs):
    """Apply current media policy to compatibility FlowItem writes."""
    try:
        instance.content = _validate_legacy_media(instance.kind, instance.content)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError({"content": str(exc)}) from exc


@receiver(pre_save, sender=FlowStep)
def validate_legacy_flow_step_media(sender, instance, **kwargs):
    """Apply current media policy to untyped compatibility FlowStep writes."""
    try:
        instance.content = _validate_legacy_media(instance.kind, instance.content)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError({"content": str(exc)}) from exc
