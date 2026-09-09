"""Transactional owner-scoped question-bank commands and bounded search."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db import IntegrityError, transaction

from liveclassroom.models import ActivityDefinition, Course, QuestionBank, QuestionBankItem

from .classroom import ClassroomError
from .permissions import can_author_course, can_teach, can_use_activity_definition


def _text(value: Any, field: str, *, required: bool = False, maximum: int = 200) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ClassroomError(f"{field} must be text.")
    value = value.strip()
    if required and not value:
        raise ClassroomError(f"{field} is required.")
    if len(value) > maximum:
        raise ClassroomError(f"{field} is too long.")
    return value


def _owner(actor, bank: QuestionBank) -> None:
    if not can_teach(actor) or (bank.owner_id != actor.pk and not getattr(actor, "is_superuser", False)):
        raise ClassroomError("You do not have permission to manage this question bank.")


def _course(actor, course_id: Any) -> Course | None:
    if course_id is None:
        return None
    if isinstance(course_id, bool) or not isinstance(course_id, int) or course_id <= 0:
        raise ClassroomError("course_id must be a positive integer.")
    try:
        course = Course.objects.get(pk=course_id)
    except Course.DoesNotExist as exc:
        raise ClassroomError("Course not found.") from exc
    if not can_author_course(actor, course):
        raise ClassroomError("You do not have permission to use this course.")
    return course


@transaction.atomic
def create_question_bank(*, actor, data: Mapping[str, Any]) -> QuestionBank:
    if not can_teach(actor):
        raise ClassroomError("An authenticated teacher is required to create a question bank.")
    if not isinstance(data, Mapping) or set(data) - {"title", "description", "course_id"}:
        raise ClassroomError("Unsupported question bank fields.")
    return QuestionBank.objects.create(
        owner=actor,
        title=_text(data.get("title"), "title", required=True),
        description=_text(data.get("description", ""), "description", maximum=4000),
        course=_course(actor, data.get("course_id")),
    )


@transaction.atomic
def update_question_bank(*, actor, bank: QuestionBank, changes: Mapping[str, Any]) -> QuestionBank:
    _owner(actor, bank)
    if not isinstance(changes, Mapping) or not changes or set(changes) - {"title", "description", "course_id"}:
        raise ClassroomError("Unsupported question bank fields.")
    bank = QuestionBank.objects.select_for_update().get(pk=bank.pk)
    if "title" in changes:
        bank.title = _text(changes["title"], "title", required=True)
    if "description" in changes:
        bank.description = _text(changes["description"], "description", maximum=4000)
    if "course_id" in changes:
        bank.course = _course(actor, changes["course_id"])
    bank.save()
    return bank


@transaction.atomic
def delete_question_bank(*, actor, bank: QuestionBank) -> None:
    _owner(actor, bank)
    QuestionBank.objects.select_for_update().get(pk=bank.pk).delete()


@transaction.atomic
def add_question_to_bank(*, actor, bank: QuestionBank, definition: ActivityDefinition) -> QuestionBankItem:
    _owner(actor, bank)
    if not can_use_activity_definition(actor, definition):
        raise ClassroomError("You do not have permission to use this activity definition.")
    bank = QuestionBank.objects.select_for_update().get(pk=bank.pk)
    existing = QuestionBankItem.objects.filter(bank=bank, definition=definition).first()
    if existing is not None:
        return existing
    last_position = (
        QuestionBankItem.objects.filter(bank=bank).order_by("-position").values_list("position", flat=True).first()
    )
    position = (last_position or 0) + 1
    try:
        return QuestionBankItem.objects.create(bank=bank, definition=definition, position=position)
    except IntegrityError:
        return QuestionBankItem.objects.get(bank=bank, definition=definition)


@transaction.atomic
def remove_question_from_bank(*, actor, bank: QuestionBank, definition: ActivityDefinition) -> None:
    _owner(actor, bank)
    deleted, _ = QuestionBankItem.objects.filter(bank=bank, definition=definition).delete()
    if not deleted:
        raise ClassroomError("This question is not in the bank.")


def _matches(definition: ActivityDefinition, filters: Mapping[str, Any]) -> bool:
    metadata = definition.metadata if isinstance(definition.metadata, dict) else {}
    query = filters.get("q", "")
    if query:
        needle = query.casefold()
        prompt = definition.definition.get("prompt", "") if isinstance(definition.definition, dict) else ""
        haystack = " ".join((definition.title, str(prompt), str(metadata.get("topic", "")))).casefold()
        if needle not in haystack:
            return False
    for field in ("topic", "difficulty", "type_key"):
        wanted = filters.get(field)
        actual = definition.type_key if field == "type_key" else metadata.get(field)
        if wanted and (not isinstance(actual, str) or actual.casefold() != wanted.casefold()):
            return False
    tag = filters.get("tag")
    if tag:
        tags = metadata.get("tags", [])
        if not isinstance(tags, list) or tag.casefold() not in {str(item).casefold() for item in tags}:
            return False
    return True


def list_bank_questions(
    *, actor, bank: QuestionBank | None = None, filters: Mapping[str, Any] | None = None
) -> list[ActivityDefinition]:
    if not can_teach(actor):
        raise ClassroomError("An authenticated teacher is required to view question banks.")
    filters = filters or {}
    if not isinstance(filters, Mapping) or set(filters) - {"q", "topic", "tag", "difficulty", "type_key"}:
        raise ClassroomError("Unsupported search filters.")
    normalized = {key: _text(value, key, maximum=200) for key, value in filters.items() if value not in (None, "")}
    if bank is None:
        queryset = ActivityDefinition.objects.filter(owner=actor).order_by("-updated_at", "-id")
    else:
        _owner(actor, bank)
        queryset = ActivityDefinition.objects.filter(question_bank_items__bank=bank).order_by("-updated_at", "-id")
    return [definition for definition in queryset if _matches(definition, normalized)]
