import secrets
import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .content import Flow, FlowItem, FlowStep
from .course import Course


def make_join_code() -> str:
    """Return a human-enterable code; uniqueness is enforced by the database."""
    from liveclassroom.conf import join_code_length

    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(join_code_length()))


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

    class AccessMode(models.TextChoices):
        GUEST = "guest", "Guest link"
        AUTHENTICATED = "authenticated", "Authenticated users"
        BOTH = "both", "Guest link and authenticated users"

    class AdmissionMode(models.TextChoices):
        OPEN = "open", "Open"
        WAITING_ROOM = "waiting_room", "Waiting room"
        ROSTER = "roster", "Roster only"

    title = models.CharField(max_length=200, default="Live classroom")
    course = models.ForeignKey(Course, null=True, blank=True, on_delete=models.SET_NULL, related_name="live_sessions")
    flow = models.ForeignKey(Flow, null=True, blank=True, on_delete=models.SET_NULL, related_name="live_sessions")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="liveclassroom_sessions_hosted",
    )
    join_code = models.CharField(max_length=12, unique=True, default=make_join_code)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.TEACHER_PACED)
    access_mode = models.CharField(max_length=20, choices=AccessMode.choices, default=AccessMode.GUEST)
    admission_mode = models.CharField(max_length=20, choices=AdmissionMode.choices, default=AdmissionMode.OPEN)
    chat_enabled = models.BooleanField(default=False)
    current_item = models.ForeignKey(
        FlowItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_in_sessions",
    )
    current_step = models.ForeignKey(
        FlowStep,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_in_sessions",
    )
    state_version = models.PositiveBigIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if self.flow_id and self.course_id and self.flow.course_id and self.flow.course_id != self.course_id:
            raise ValidationError({"flow": "The selected flow must belong to the selected course."})
        if self.current_item_id and self.flow_id and self.current_item.flow_id != self.flow_id:
            raise ValidationError({"current_item": "The item must belong to the selected flow."})
        if self.current_step_id and self.flow_id and self.current_step.flow_id != self.flow_id:
            raise ValidationError({"current_step": "The step must belong to the selected flow."})

    def __str__(self) -> str:
        return f"{self.title} ({self.join_code})"

    @property
    def owner(self):
        """Product vocabulary alias retained alongside the original teacher field."""
        return self.teacher


class Participant(models.Model):
    class Role(models.TextChoices):
        TEACHER = "teacher", "Teacher"
        ASSISTANT = "assistant", "Assistant"
        STUDENT = "student", "Student"

    class AdmissionState(models.TextChoices):
        PENDING = "pending", "Pending"
        ADMITTED = "admitted", "Admitted"
        REJECTED = "rejected", "Rejected"
        REMOVED = "removed", "Removed"

    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liveclassroom_participations",
    )
    guest_id = models.CharField(max_length=128, blank=True)
    display_name = models.CharField(max_length=100)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STUDENT)
    admission_state = models.CharField(max_length=16, choices=AdmissionState.choices, default=AdmissionState.ADMITTED)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    connected_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)

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


class ParticipantConnection(models.Model):
    """One active or historical WebSocket connection for a participant.

    The participant timestamps remain a compact attendance summary.  This
    table is the authority for whether another tab or device is still online.
    """

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="connections")
    connection_id = models.CharField(max_length=255, unique=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["participant", "disconnected_at"], name="liveclassro_partici_19bd82_idx")]
        ordering = ["participant", "connected_at"]


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
    source_step = models.ForeignKey(
        FlowStep,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="live_activities",
    )
    definition_snapshot = models.JSONField(default=dict)
    current_revision = models.ForeignKey(
        "ActivityRunRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for_activities",
    )
    reviewable = models.BooleanField(default=False)
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
    participant = models.ForeignKey(
        Participant,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="session_events",
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "sequence"], name="lc_event_sequence")]
        ordering = ["session", "sequence"]

    def __str__(self) -> str:
        return f"{self.session}: {self.event_type}"


class ActivityRunRevision(models.Model):
    """Immutable snapshot of the definition used by a launched activity."""

    activity = models.ForeignKey(LiveActivity, on_delete=models.CASCADE, related_name="revisions")
    revision = models.PositiveIntegerField()
    definition_snapshot = models.JSONField(default=dict)
    source_revision = models.ForeignKey(
        "liveclassroom.ActivityDefinitionRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activity_runs",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liveclassroom_activity_run_revisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["activity", "revision"]
        constraints = [models.UniqueConstraint(fields=["activity", "revision"], name="lc_activity_run_revision_once")]


class SessionStaff(models.Model):
    class Role(models.TextChoices):
        COHOST = "cohost", "Co-host"
        ASSISTANT = "assistant", "Assistant"
        OBSERVER = "observer", "Observer"

    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name="staff")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="liveclassroom_staff_assignments",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "user"], name="lc_session_staff_once")]
        ordering = ["session", "user"]


class SessionChannelState(models.Model):
    class Channel(models.TextChoices):
        DISPLAY = "display", "Classroom display"
        PARTICIPANTS = "participants", "Participants"

    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name="channel_states")
    channel = models.CharField(max_length=16, choices=Channel.choices)
    current_activity = models.ForeignKey(
        LiveActivity,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="channel_states",
    )
    current_revision = models.ForeignKey(
        ActivityRunRevision,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="channel_states",
    )
    version = models.PositiveBigIntegerField(default=0)
    show_prompt = models.BooleanField(default=True)
    show_aggregate = models.BooleanField(default=False)
    show_answer = models.BooleanField(default=False)
    show_explanation = models.BooleanField(default=False)
    show_own_status = models.BooleanField(default=True)
    allow_review = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "channel"], name="lc_session_channel_once")]
        ordering = ["session", "channel"]


class SessionMessage(models.Model):
    """A named, public message in a classroom session."""

    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name="messages")
    participant = models.ForeignKey(
        Participant,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liveclassroom_messages",
    )
    display_name = models.CharField(max_length=100)
    body = models.TextField(max_length=4000)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]


class CommandReceipt(models.Model):
    """Persist the result of an externally retried mutation for idempotent replay."""

    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name="command_receipts")
    idempotency_key = models.CharField(max_length=160)
    command_type = models.CharField(max_length=80)
    request_hash = models.CharField(max_length=64, blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liveclassroom_command_receipts",
    )
    response = models.JSONField(default=dict)
    status_code = models.PositiveSmallIntegerField(default=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "idempotency_key"],
                name="lc_command_receipt_once",
            )
        ]
        ordering = ["session", "created_at", "id"]
