"""Reusable lesson snapshots and independently editable classroom plans."""

import uuid

from django.conf import settings
from django.db import models


class FlowSnapshot(models.Model):
    flow = models.ForeignKey("liveclassroom.Flow", null=True, on_delete=models.SET_NULL, related_name="snapshots")
    title = models.CharField(max_length=200)
    manifest = models.JSONField(default=list)
    fingerprint = models.CharField(max_length=64)
    assets = models.ManyToManyField(
        "liveclassroom.ClassroomAsset", related_name="lesson_snapshots", blank=True, through="SnapshotAsset"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class FlowShare(models.Model):
    flow = models.ForeignKey("liveclassroom.Flow", on_delete=models.CASCADE, related_name="shares")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shared_lessons")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["flow", "user"], name="lc_flow_share_once")]


class SessionPlanStep(models.Model):
    session = models.ForeignKey("liveclassroom.LiveSession", on_delete=models.CASCADE, related_name="plan_steps")
    key = models.UUIDField(default=uuid.uuid4)
    position = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    asset = models.ForeignKey(
        "liveclassroom.ClassroomAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="session_plan_steps",
    )
    removed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [models.UniqueConstraint(fields=["session", "key"], name="lc_plan_step_key_once")]


class SnapshotAsset(models.Model):
    snapshot = models.ForeignKey(FlowSnapshot, on_delete=models.CASCADE)
    asset = models.ForeignKey("liveclassroom.ClassroomAsset", on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["snapshot", "asset"], name="lc_snapshot_asset_once")]
