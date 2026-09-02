import secrets
import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .content import Flow, FlowItem
from .course import Course


def make_join_code() -> str:
    """Return a human-enterable code; uniqueness is enforced by the database."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


class LiveSession(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        WAITING = "waiting", "Waiting"
        LIVE = "live", "Live"
        PAUSED = "paused", "Paused"
        ENDED = "ended", "Ended"

    class Mode(models.TextChoices):
        TEACHER_PACED = "teacher_paced", "Teacher paced"
        STUDENT_PACED = "student_paced", "Student paced"
        EXAM = "exam", "Exam"

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="live_sessions")
    flow = models.ForeignKey(Flow, on_delete=models.PROTECT, related_name="live_sessions")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="liveclassroom_sessions_hosted",
    )
    join_code = models.CharField(max_length=12, unique=True, default=make_join_code)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.TEACHER_PACED)
    current_item = models.ForeignKey(
        FlowItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_in_sessions",
    )
    state_version = models.PositiveBigIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if self.flow_id and self.course_id and self.flow.course_id != self.course_id:
            raise ValidationError({"flow": "The selected flow must belong to the selected course."})
        if self.current_item_id and self.flow_id and self.current_item.flow_id != self.flow_id:
            raise ValidationError({"current_item": "The item must belong to the selected flow."})

    def __str__(self) -> str:
        return f"{self.course} ({self.join_code})"


class Participant(models.Model):
    class Role(models.TextChoices):
        TEACHER = "teacher", "Teacher"
        ASSISTANT = "assistant", "Assistant"
        STUDENT = "student", "Student"

    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="liveclassroom_participations",
    )
    guest_id = models.CharField(max_length=128, blank=True)
    display_name = models.CharField(max_length=100)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STUDENT)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "user"],
                condition=models.Q(user__isnull=False),
                name="lc_one_user_participant_per_session",
            ),
            models.UniqueConstraint(
                fields=["session", "guest_id"],
                condition=~models.Q(guest_id=""),
                name="lc_one_guest_participant_per_session",
            ),
        ]

    def clean(self) -> None:
        if not self.user_id and not self.guest_id:
            raise ValidationError("A participant needs an account or a guest identity.")

    def __str__(self) -> str:
        return self.display_name


class LiveActivity(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        REVEALED = "revealed", "Revealed"

    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name="activities")
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=16)
    source_item = models.ForeignKey(
        FlowItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="live_activities",
    )
    definition_snapshot = models.JSONField(default=dict)
    state = models.CharField(max_length=16, choices=State.choices, default=State.OPEN)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    revealed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "sequence"], name="lc_activity_sequence")]
        ordering = ["session", "sequence"]

    def __str__(self) -> str:
        return f"{self.session}: activity {self.sequence}"


class SessionEvent(models.Model):
    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name="events")
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liveclassroom_events",
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "sequence"], name="lc_event_sequence")]
        ordering = ["session", "sequence"]

    def __str__(self) -> str:
        return f"{self.session}: {self.event_type}"
