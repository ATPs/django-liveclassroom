"""Durable teacher-facing AI authoring records."""

from django.conf import settings
from django.db import models


class AuthoringThread(models.Model):
    """A private authoring conversation owned by one authenticated teacher."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="liveclassroom_authoring_threads",
    )
    title = models.CharField(max_length=200, default="New authoring conversation")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["owner", "updated_at"])]

    def __str__(self) -> str:
        return self.title


class AuthoringMessage(models.Model):
    """A persisted teacher prompt or final assistant response."""

    class Role(models.TextChoices):
        TEACHER = "teacher", "Teacher"
        ASSISTANT = "assistant", "Assistant"

    class Status(models.TextChoices):
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    thread = models.ForeignKey(AuthoringThread, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liveclassroom_authoring_messages",
    )
    content = models.TextField()
    model_identifier = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMPLETE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.thread}: {self.role}"


class AuthoringAttachment(models.Model):
    """A typed source reference attached to one teacher prompt.

    This deliberately has no copied source body. Provider references are
    re-authorized immediately before an AI backend is invoked.
    """

    class SourceType(models.TextChoices):
        ACTIVITY = "activity", "Activity"
        FLOW = "flow", "Flow"
        FLOW_STEP = "flow_step", "Flow step"
        PROVIDER = "provider", "Content provider"

    message = models.ForeignKey(AuthoringMessage, on_delete=models.CASCADE, related_name="attachments")
    source_type = models.CharField(max_length=32, choices=SourceType.choices)
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    provider = models.CharField(max_length=100, blank=True)
    reference = models.JSONField(default=dict, blank=True)
    source_fingerprint = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.source_type}:{self.source_id or self.provider}"


class AuthoringJob(models.Model):
    """Durable invocation state without credentials or provider diagnostics."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    thread = models.ForeignKey(AuthoringThread, on_delete=models.CASCADE, related_name="jobs")
    message = models.ForeignKey(AuthoringMessage, on_delete=models.CASCADE, related_name="jobs")
    assistant_message = models.ForeignKey(
        AuthoringMessage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="authoring_jobs_as_response",
    )
    backend_key = models.CharField(max_length=100)
    model_identifier = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    error_code = models.CharField(max_length=64, blank=True)
    attempt = models.PositiveSmallIntegerField(default=1)
    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.CharField(max_length=64, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-queued_at", "-id"]
        indexes = [models.Index(fields=["thread", "status"]), models.Index(fields=["status", "lease_expires_at"])]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.message_id and self.thread_id:
            message_thread_id = AuthoringMessage.objects.filter(pk=self.message_id).values_list(
                "thread_id", flat=True
            ).first()
            if message_thread_id is not None and message_thread_id != self.thread_id:
                raise ValidationError({"message": "The job message must belong to the job thread."})
        if self.assistant_message_id and self.thread_id:
            assistant_thread_id = AuthoringMessage.objects.filter(pk=self.assistant_message_id).values_list(
                "thread_id", flat=True
            ).first()
            if assistant_thread_id is not None and assistant_thread_id != self.thread_id:
                raise ValidationError({"assistant_message": "The assistant message must belong to the job thread."})

    def __str__(self) -> str:
        return f"{self.thread}: {self.status}"
