"""Private teacher-owned files used as classroom presentation content."""

from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models


def asset_upload_path(instance: ClassroomAsset, filename: str) -> str:
    """Keep uploaded presentation files outside any public media URL contract."""
    return f"liveclassroom/assets/{instance.public_id}/{Path(filename).name}"


class ClassroomAsset(models.Model):
    class Source(models.TextChoices):
        UPLOAD = "upload", "Upload"
        SERVER_PATH = "server_path", "Server path"

    class Kind(models.TextChoices):
        MARKDOWN = "markdown", "Markdown"
        PDF = "pdf", "PDF"
        PPTX = "pptx", "PowerPoint"
        VIDEO = "video", "Video"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="liveclassroom_assets",
    )
    source = models.CharField(max_length=16, choices=Source.choices)
    content_file = models.FileField(upload_to=asset_upload_path, blank=True)
    server_path = models.TextField(blank=True)
    original_name = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    content_type = models.CharField(max_length=100)
    byte_size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["owner", "created_at"])]

    def __str__(self) -> str:
        return self.original_name
