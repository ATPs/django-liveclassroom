"""Validated assessment sections and immutable question-pool definitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction

from liveclassroom.models import (
    AssessmentDefinition,
    AssessmentItem,
    AssessmentSection,
    AssessmentSectionEntry,
    QuestionBank,
)

from .assessments import MAX_POINTS, _decimal, _owner
from .classroom import ClassroomError
from .question_banks import normalize_bank_filters

MAX_SECTIONS = 100
MAX_ENTRIES = 500
MAX_SAMPLE_SIZE = 500


def _uuid(value: Any, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ClassroomError(f"{field} must be a UUID.") from exc


def _text(value: Any, field: str, *, required: bool = False, maximum: int = 200) -> str:
    if not isinstance(value, str):
        raise ClassroomError(f"{field} must be text.")
    value = value.strip()
    if required and not value:
        raise ClassroomError(f"{field} is required.")
    if len(value) > maximum:
        raise ClassroomError(f"{field} is too long.")
    return value


def _position(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ClassroomError(f"{field} must be a positive integer.")
    return value


def _kind(value: Any, row: Mapping[str, Any]) -> str:
    result = value if value is not None else row.get("type", row.get("entry_type"))
    if result is None:
        result = "pool" if any(key in row for key in ("bank_id", "question_bank_id")) else "fixed"
    if not isinstance(result, str) or result.casefold() not in {"fixed", "item", "pool", "bank"}:
        raise ClassroomError("Each section entry must be fixed or pool.")
    return "pool" if result.casefold() in {"pool", "bank"} else "fixed"


def _bank(actor, value: Any) -> QuestionBank:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ClassroomError("bank_id must be a positive integer.")
    try:
        bank = QuestionBank.objects.get(pk=value)
    except QuestionBank.DoesNotExist as exc:
        raise ClassroomError("Question bank not found.") from exc
    if bank.owner_id != actor.pk and not getattr(actor, "is_superuser", False):
        raise ClassroomError("You do not have permission to use this question bank.")
    return bank


def _sample_size(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > MAX_SAMPLE_SIZE:
        raise ClassroomError(f"sample_size must be a positive integer at most {MAX_SAMPLE_SIZE}.")
    return value


def _points(value: Any) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, "points", minimum=Decimal("0.000001"), maximum=MAX_POINTS)


def _item_for_reference(
    row: Mapping[str, Any], assessment: AssessmentDefinition, items: dict[str, AssessmentItem]
) -> AssessmentItem:
    """Resolve both the stable item key and the authoring convenience ID."""
    if "item_id" in row or "assessment_item_id" in row:
        value = row.get("item_id", row.get("assessment_item_id"))
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ClassroomError("item_id must be a positive integer.")
        try:
            return assessment.items.get(pk=value)
        except AssessmentItem.DoesNotExist as exc:
            raise ClassroomError("The fixed item does not belong to this assessment.") from exc
    reference = row.get("item_key", row.get("assessment_item_key"))
    if reference is None:
        raise ClassroomError("A fixed section entry needs item_key.")
    item = items.get(str(_uuid(reference, "item_key")))
    if item is None:
        raise ClassroomError("The fixed item does not belong to this assessment.")
    return item


def _allowed(row: Mapping[str, Any], kind: str) -> None:
    common = {"key", "position", "kind", "type", "entry_type"}
    if kind == "fixed":
        allowed = common | {
            "item_key",
            "assessment_item_key",
            "item_id",
            "assessment_item_id",
            "shuffle_options",
        }
    else:
        allowed = common | {
            "bank_id",
            "question_bank_id",
            "filters",
            "sample_size",
            "points",
            "shuffle_options",
        }
    if set(row) - allowed:
        raise ClassroomError("Unsupported section entry fields.")


def _entry_rows(actor, assessment: AssessmentDefinition, section: Mapping[str, Any], items: dict[str, AssessmentItem]):
    values = section.get("entries", [])
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise ClassroomError("Section entries must be a list.")
    if len(values) > MAX_ENTRIES:
        raise ClassroomError(f"An assessment may contain at most {MAX_ENTRIES} section entries.")
    rows = []
    seen_keys: set[UUID] = set()
    seen_items: set[int] = set()
    for index, raw in enumerate(values, 1):
        if not isinstance(raw, Mapping):
            raise ClassroomError("Each section entry must be an object.")
        kind = _kind(raw.get("kind"), raw)
        _allowed(raw, kind)
        key = _uuid(raw.get("key", uuid4()), "Section entry key")
        if key in seen_keys:
            raise ClassroomError("Each section entry key must be unique.")
        seen_keys.add(key)
        row: dict[str, Any] = {
            "key": key,
            "position": _position(raw.get("position"), "position") or index,
            "kind": kind,
        }
        if kind == "fixed":
            item = _item_for_reference(raw, assessment, items)
            if item.pk in seen_items:
                raise ClassroomError("A fixed assessment item cannot appear twice in a section.")
            seen_items.add(item.pk)
            row["item"] = item
            shuffle = raw.get("shuffle_options", False)
            if not isinstance(shuffle, bool):
                raise ClassroomError("shuffle_options must be a boolean.")
            row["shuffle_options"] = shuffle
            rows.append(row)
            continue
        bank_value = raw.get("bank_id", raw.get("question_bank_id"))
        if bank_value is None:
            raise ClassroomError("A pool entry needs bank_id.")
        row["bank"] = _bank(actor, bank_value)
        try:
            row["filters"] = normalize_bank_filters(raw.get("filters", {}))
        except ClassroomError:
            raise
        row["sample_size"] = _sample_size(raw.get("sample_size"))
        row["points"] = _points(raw.get("points"))
        shuffle = raw.get("shuffle_options", False)
        if not isinstance(shuffle, bool):
            raise ClassroomError("shuffle_options must be a boolean.")
        row["shuffle_options"] = shuffle
        rows.append(row)
    return rows, seen_items


def normalize_sections(*, actor, assessment: AssessmentDefinition, sections: Any) -> list[dict[str, Any]]:
    """Validate a draft section payload without writing any rows."""
    if not isinstance(sections, Sequence) or isinstance(sections, (str, bytes, bytearray)):
        raise ClassroomError("sections must be a list.")
    if len(sections) < 1 or len(sections) > MAX_SECTIONS:
        raise ClassroomError(f"An assessment must have between 1 and {MAX_SECTIONS} sections.")
    items = {str(item.key): item for item in assessment.items.all()}
    normalized = []
    represented: set[int] = set()
    seen_section_keys: set[UUID] = set()
    for index, raw in enumerate(sections, 1):
        if not isinstance(raw, Mapping):
            raise ClassroomError("Each section must be an object.")
        allowed = {"key", "title", "position", "entries", "shuffle_questions"}
        if set(raw) - allowed:
            raise ClassroomError("Unsupported section fields.")
        key = _uuid(raw.get("key", uuid4()), "Section key")
        if key in seen_section_keys:
            raise ClassroomError("Each section key must be unique.")
        seen_section_keys.add(key)
        title = _text(raw.get("title", f"Section {index}"), "title", required=True)
        shuffle_questions = raw.get("shuffle_questions", False)
        if not isinstance(shuffle_questions, bool):
            raise ClassroomError("shuffle_questions must be a boolean.")
        entries, fixed = _entry_rows(actor, assessment, raw, items)
        overlap = represented & fixed
        if overlap:
            raise ClassroomError("A fixed assessment item cannot appear in multiple sections.")
        represented.update(fixed)
        normalized.append(
            {
                "key": key,
                "position": _position(raw.get("position"), "position") or index,
                "title": title,
                "shuffle_questions": shuffle_questions,
                "entries": entries,
            }
        )
    all_item_ids = {item.pk for item in items.values()}
    represented_item_ids = {
        entry["item"].pk
        for section in normalized
        for entry in section["entries"]
        if entry["kind"] == "fixed"
    }
    if all_item_ids - represented_item_ids:
        raise ClassroomError("Every fixed assessment item must belong to a section.")
    return normalized


def default_sections(assessment: AssessmentDefinition) -> list[dict[str, Any]]:
    """Return the compatibility section for a fixed-question assessment."""
    entries = [
        {
            "key": uuid4(),
            "position": item.position,
            "kind": AssessmentSectionEntry.Kind.FIXED,
            "item": item,
        }
        for item in assessment.items.all().order_by("position", "id")
    ]
    return [
        {
            "key": uuid4(),
            "position": 1,
            "title": "Section 1",
            "shuffle_questions": False,
            "entries": entries,
        }
    ]


def _write_sections(assessment: AssessmentDefinition, sections: Sequence[Mapping[str, Any]]) -> None:
    assessment.sections.all().delete()
    section_rows = []
    for section in sections:
        section_rows.append(
            AssessmentSection(
                assessment=assessment,
                key=section["key"],
                title=section["title"],
                position=section["position"],
                shuffle_questions=section.get("shuffle_questions", False),
            )
        )
    AssessmentSection.objects.bulk_create(section_rows)
    by_key = {row.key: row for row in AssessmentSection.objects.filter(assessment=assessment)}
    entries = []
    for section in sections:
        section_row = by_key[section["key"]]
        for item in section["entries"]:
            entries.append(
                AssessmentSectionEntry(
                    section=section_row,
                    key=item["key"],
                    position=item["position"],
                    kind=item["kind"],
                    item=item.get("item"),
                    bank=item.get("bank"),
                    filters=deepcopy(item.get("filters", {})),
                    sample_size=item.get("sample_size"),
                    points=item.get("points"),
                    shuffle_options=item.get("shuffle_options", False),
                )
            )
    AssessmentSectionEntry.objects.bulk_create(entries)


@transaction.atomic
def set_sections(*, actor, assessment: AssessmentDefinition, sections: Any) -> AssessmentDefinition:
    """Replace section definitions as part of a caller's existing transaction."""
    _owner(actor, assessment)
    locked = AssessmentDefinition.objects.select_for_update().get(pk=assessment.pk)
    normalized = normalize_sections(actor=actor, assessment=locked, sections=sections)
    _write_sections(locked, normalized)
    return locked


@transaction.atomic
def replace_sections(
    *, actor, assessment: AssessmentDefinition, expected_version: int, sections: Any
) -> AssessmentDefinition:
    _owner(actor, assessment)
    locked = AssessmentDefinition.objects.select_for_update().get(pk=assessment.pk)
    if (
        isinstance(expected_version, bool)
        or not isinstance(expected_version, int)
        or expected_version != locked.version
    ):
        raise ClassroomError("The assessment changed; refresh before saving.")
    normalized = normalize_sections(actor=actor, assessment=locked, sections=sections)
    _write_sections(locked, normalized)
    locked.version += 1
    locked.save(update_fields=["version", "updated_at"])
    return locked


def section_payload(section: AssessmentSection, *, include_private: bool = True) -> dict[str, Any]:
    entries = []
    for entry in section.entries.select_related("item__question_revision__definition", "bank").all():
        payload = {
            "key": str(entry.key),
            "position": entry.position,
            "kind": entry.kind,
        }
        if entry.kind == AssessmentSectionEntry.Kind.FIXED:
            payload["item_key"] = str(entry.item.key)
            payload["item_id"] = entry.item_id
            if include_private:
                payload["shuffle_options"] = entry.shuffle_options
        elif include_private:
            payload.update(
                {
                    "bank_id": entry.bank_id,
                    "filters": deepcopy(entry.filters),
                    "sample_size": entry.sample_size,
                    "points": format(entry.points.normalize(), "f") if entry.points is not None else None,
                    "shuffle_options": entry.shuffle_options,
                }
            )
        entries.append(payload)
    return {
        "key": str(section.key),
        "title": section.title,
        "position": section.position,
        "shuffle_questions": section.shuffle_questions,
        "entries": entries,
    }


def sections_payload(assessment: AssessmentDefinition, *, include_private: bool = True) -> list[dict[str, Any]]:
    sections = assessment.sections.all().prefetch_related(
        "entries__item__question_revision__definition", "entries__bank"
    )
    return [section_payload(section, include_private=include_private) for section in sections]


def ensure_default_sections(assessment: AssessmentDefinition) -> None:
    """Backfill a compatibility section for direct or legacy draft writes."""
    if not assessment.sections.exists():
        _write_sections(assessment, default_sections(assessment))
