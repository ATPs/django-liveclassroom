from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver


class ActivityDefinition(models.Model):
    """A reusable, typed activity definition owned by a teacher."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready"
        ARCHIVED = "archived", "Archived"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="liveclassroom_activity_definitions",
    )
    course = models.ForeignKey(
        "liveclassroom.Course",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activity_definitions",
    )
    type_key = models.CharField(max_length=100)
    schema_version = models.PositiveSmallIntegerField(default=1)
    title = models.CharField(max_length=200)
    definition = models.JSONField(default=dict)
    asset = models.ForeignKey(
        "liveclassroom.ClassroomAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="activity_definitions",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    current_revision = models.ForeignKey(
        "liveclassroom.ActivityDefinitionRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for_definitions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "type_key"])]

    def __str__(self) -> str:
        return self.title


class ActivityDefinitionRevision(models.Model):
    """Immutable history for a reusable activity definition."""

    definition = models.ForeignKey(ActivityDefinition, on_delete=models.CASCADE, related_name="revisions")
    revision = models.PositiveIntegerField()
    schema_version = models.PositiveSmallIntegerField(default=1)
    payload = models.JSONField(default=dict)
    asset = models.ForeignKey(
        "liveclassroom.ClassroomAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="activity_definition_revisions",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="liveclassroom_activity_revisions",
    )
    change_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["definition", "revision"]
        constraints = [
            models.UniqueConstraint(fields=["definition", "revision"], name="lc_definition_revision_once"),
        ]

    def __str__(self) -> str:
        return f"{self.definition} r{self.revision}"

    @property
    def definition_snapshot(self):
        """Vocabulary shared with launched run revisions."""
        return self.payload


class AuthoringCommandReceipt(models.Model):
    """Persist an authoring mutation result for safe client retries."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="liveclassroom_authoring_command_receipts",
    )
    idempotency_key = models.CharField(max_length=160)
    command_type = models.CharField(max_length=80)
    request_hash = models.CharField(max_length=64, blank=True, default="")
    response = models.JSONField(default=dict)
    status_code = models.PositiveSmallIntegerField(default=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "idempotency_key"],
                name="lc_authoring_receipt_once",
            )
        ]
        ordering = ["owner", "created_at", "id"]


@receiver(pre_save, sender=ActivityDefinition)
def validate_activity_definition_before_save(sender, instance, **kwargs):
    """Keep direct ORM and admin writes behind the activity registry policy."""
    try:
        from liveclassroom.registry import activity_registry

        instance.definition = activity_registry.get(instance.type_key).validate(instance.definition)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError({"definition": str(exc)}) from exc


@receiver(post_save, sender=ActivityDefinition)
def create_initial_activity_revision(sender, instance, created, **kwargs):
    """Keep direct ORM creation as safe as the service-based authoring path."""
    if created and not instance.current_revision_id:
        revision = ActivityDefinitionRevision.objects.create(
            definition=instance,
            revision=1,
            schema_version=instance.schema_version,
            payload=instance.definition,
            asset=instance.asset,
            changed_by=instance.owner,
        )
        sender.objects.filter(pk=instance.pk, current_revision__isnull=True).update(current_revision=revision)
