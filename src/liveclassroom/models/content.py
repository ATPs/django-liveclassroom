from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .activity import ActivityDefinition
from .course import Course


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


class FlowStep(models.Model):
    """An ordered reusable activity in a prepared flow."""

    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name="steps")
    position = models.PositiveIntegerField()
    activity_definition = models.ForeignKey(
        ActivityDefinition,
        on_delete=models.PROTECT,
        related_name="flow_steps",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["flow", "position"]
        constraints = [models.UniqueConstraint(fields=["flow", "position"], name="lc_flow_step_position")]

    def __str__(self) -> str:
        return f"{self.flow} step {self.position}: {self.activity_definition}"

    def clean(self) -> None:
        if self.activity_definition_id and self.activity_definition.course_id:
            if self.flow_id and self.flow.course_id and self.activity_definition.course_id != self.flow.course_id:
                raise ValidationError({"activity_definition": "The activity must belong to the flow's course."})
