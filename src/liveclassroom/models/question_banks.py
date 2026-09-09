"""Owner-scoped reusable question-bank models."""

from django.conf import settings
from django.db import models


class QuestionBank(models.Model):
    """A lightweight library grouping existing activity definitions."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="liveclassroom_question_banks",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    course = models.ForeignKey(
        "liveclassroom.Course",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="question_banks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        indexes = [models.Index(fields=["owner", "updated_at"])]

    def __str__(self) -> str:
        return self.title


class QuestionBankItem(models.Model):
    """One reusable definition in a bank; membership never owns the definition."""

    bank = models.ForeignKey(QuestionBank, on_delete=models.CASCADE, related_name="items")
    definition = models.ForeignKey(
        "liveclassroom.ActivityDefinition",
        on_delete=models.PROTECT,
        related_name="question_bank_items",
    )
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("position", "id")
        constraints = [models.UniqueConstraint(fields=["bank", "definition"], name="lc_question_bank_item_once")]

    def __str__(self) -> str:
        return f"{self.bank}: {self.definition}"
