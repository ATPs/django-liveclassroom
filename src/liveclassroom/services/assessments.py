"""Validated authoring commands for fixed-question assessment drafts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from decimal import Decimal, DecimalException
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction

from liveclassroom.models import (
    ActivityDefinition,
    ActivityDefinitionRevision,
    AssessmentDefinition,
    AssessmentItem,
    Course,
)
from liveclassroom.registry import activity_registry
from liveclassroom.release_policy import normalize_release_policy

from .assessment_timing import TIMING_FIELDS, normalize_timing_settings
from .classroom import ClassroomError
from .permissions import can_author_course, can_teach, can_use_activity_definition

MAX_ITEMS = 500
MAX_TITLE_LENGTH = 200
MAX_INSTRUCTIONS_LENGTH = 20_000
MAX_POINTS = Decimal("1000")
DEFAULT_POINTS = Decimal("1")
SUPPORTED_SETTINGS = frozenset({"max_attempts", "pass_percent", "audience", "release_policy"}) | TIMING_FIELDS
AUDIENCES = frozenset({"authenticated_link", "class"})


def _text(value: Any, field: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ClassroomError(f"{field} must be text.")
    value = value.strip()
    if required and not value:
        raise ClassroomError(f"{field} is required.")
    if len(value) > maximum:
        raise ClassroomError(f"{field} is too long.")
    return value


def _owner(actor, assessment: AssessmentDefinition) -> None:
    if not can_teach(actor) or (
        assessment.owner_id != actor.pk and not getattr(actor, "is_superuser", False)
    ):
        raise ClassroomError("You do not have permission to edit this assessment.")


def _course(actor, value: Any) -> Course | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ClassroomError("course_id must be a positive integer.")
    try:
        course = Course.objects.get(pk=value)
    except Course.DoesNotExist as exc:
        raise ClassroomError("Course not found.") from exc
    if not can_author_course(actor, course):
        raise ClassroomError("You do not have permission to use this course.")
    return course


def _decimal(value: Any, field: str, *, minimum: Decimal, maximum: Decimal) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ClassroomError(f"{field} must be a finite number.")
    try:
        result = Decimal(str(value).strip())
    except (DecimalException, ValueError) as exc:
        raise ClassroomError(f"{field} must be a finite number.") from exc
    if not result.is_finite() or result < minimum or result > maximum:
        raise ClassroomError(f"{field} must be between {minimum} and {maximum}.")
    # AssessmentItem uses six fractional places. Rejecting excess precision
    # avoids silently changing the teacher's configured points on save.
    if -result.as_tuple().exponent > 6:
        raise ClassroomError(f"{field} has too many decimal places.")
    return result


def _plain_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _settings(value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ClassroomError("settings must be an object.")
    unknown = set(value) - SUPPORTED_SETTINGS
    if unknown:
        raise ClassroomError(f"Unsupported assessment settings: {', '.join(sorted(map(str, unknown)))}.")

    # Task 21 deliberately exposes only one-at-a-time or unlimited drafts;
    # later preset/exam tasks can extend this validator without allowing
    # arbitrary JSON to become a public contract.
    max_attempts = value.get("max_attempts", 1)
    if max_attempts is not None and (isinstance(max_attempts, bool) or max_attempts != 1):
        raise ClassroomError("max_attempts must be 1 or null.")
    result: dict[str, Any] = {"max_attempts": max_attempts}

    if "pass_percent" in value:
        pass_percent = value["pass_percent"]
        if pass_percent is None:
            result["pass_percent"] = None
        else:
            result["pass_percent"] = _plain_decimal(
                _decimal(pass_percent, "pass_percent", minimum=Decimal("0"), maximum=Decimal("100"))
            )

    if "audience" in value:
        audience = value["audience"]
        if not isinstance(audience, str) or audience not in AUDIENCES:
            raise ClassroomError("audience must be authenticated_link or class.")
        result["audience"] = audience
    timing = normalize_timing_settings({key: value[key] for key in TIMING_FIELDS if key in value})
    result.update(timing)
    if "release_policy" in value:
        result["release_policy"] = normalize_release_policy(
            value["release_policy"], closes_at=result.get("closes_at")
        )
    return result


def _revision_for(actor, raw_revision_id: Any, raw_definition_id: Any = None) -> ActivityDefinitionRevision:
    if raw_revision_id is None:
        if raw_definition_id is None:
            raise ClassroomError("Each assessment item needs a revision_id.")
        if isinstance(raw_definition_id, bool) or not isinstance(raw_definition_id, int) or raw_definition_id <= 0:
            raise ClassroomError("definition_id must be a positive integer.")
        try:
            definition = ActivityDefinition.objects.get(pk=raw_definition_id)
        except ActivityDefinition.DoesNotExist as exc:
            raise ClassroomError("Question definition not found.") from exc
        revision = definition.current_revision
        if revision is None:
            raise ClassroomError("Question definition has no revision.")
    else:
        if isinstance(raw_revision_id, bool) or not isinstance(raw_revision_id, int) or raw_revision_id <= 0:
            raise ClassroomError("revision_id must be a positive integer.")
        try:
            revision = ActivityDefinitionRevision.objects.select_related("definition", "asset").get(
                pk=raw_revision_id
            )
        except ActivityDefinitionRevision.DoesNotExist as exc:
            raise ClassroomError("Question revision not found.") from exc
        if raw_definition_id is not None and revision.definition_id != raw_definition_id:
            raise ClassroomError("The revision does not belong to the selected definition.")

    definition = revision.definition
    if not can_use_activity_definition(actor, definition):
        raise ClassroomError("You do not have permission to use this question revision.")
    try:
        activity_type = activity_registry.get(definition.type_key)
        activity_type.validate(deepcopy(revision.payload))
    except (KeyError, TypeError, ValueError) as exc:
        raise ClassroomError("This question revision is no longer supported.") from exc
    if not (activity_type.capabilities & frozenset({"correctness", "manual"})):
        raise ClassroomError("Only objectively graded or manually graded questions may be assessed.")

    # A revision's asset is part of the pinned content. Repeat the check here
    # even though normal authoring validates it, because old/direct ORM rows
    # must not smuggle a foreign asset into a new assessment.
    asset = revision.asset or definition.asset
    if asset is not None and not (
        asset.owner_id == actor.pk
        or asset.owner_id == definition.owner_id
        or getattr(actor, "is_superuser", False)
    ):
        raise ClassroomError("You do not have permission to retain this question asset.")
    return revision


def _item_row(actor, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ClassroomError("Each assessment item must be an object.")
    allowed = {
        "key",
        "points",
        "revision_id",
        "question_revision_id",
        "activity_revision_id",
        "definition_revision_id",
        "definition_id",
    }
    if set(value) - allowed:
        raise ClassroomError("Unsupported assessment item fields.")
    revision_values = [
        value.get(name)
        for name in ("revision_id", "question_revision_id", "activity_revision_id", "definition_revision_id")
        if name in value
    ]
    if len(set(map(str, revision_values))) > 1:
        raise ClassroomError("An assessment item may specify only one revision.")
    revision_id = revision_values[0] if revision_values else None
    revision = _revision_for(actor, revision_id, value.get("definition_id"))
    raw_key = value.get("key")
    if raw_key is None:
        key = uuid4()
    else:
        try:
            key = UUID(str(raw_key))
        except (ValueError, AttributeError) as exc:
            raise ClassroomError("Assessment item key must be a UUID.") from exc
    if "points" in value:
        points = _decimal(value["points"], "points", minimum=Decimal("0.000001"), maximum=MAX_POINTS)
    else:
        metadata = revision.metadata if isinstance(revision.metadata, dict) else {}
        points = _decimal(
            metadata.get("default_points", DEFAULT_POINTS),
            "points",
            minimum=Decimal("0.000001"),
            maximum=MAX_POINTS,
        )
    return {"key": key, "revision": revision, "points": points}


def _item_rows(actor, values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise ClassroomError("items must be a list.")
    if len(values) > MAX_ITEMS:
        raise ClassroomError(f"An assessment may contain at most {MAX_ITEMS} items.")
    rows = [_item_row(actor, value) for value in values]
    keys = [row["key"] for row in rows]
    if len(set(keys)) != len(keys):
        raise ClassroomError("Each assessment item key must be unique.")
    return rows


def _write_items(assessment: AssessmentDefinition, rows: Sequence[dict[str, Any]]) -> None:
    assessment.items.all().delete()
    AssessmentItem.objects.bulk_create(
        [
            AssessmentItem(
                assessment=assessment,
                key=row["key"],
                position=position,
                question_revision=row["revision"],
                points=row["points"],
            )
            for position, row in enumerate(rows, 1)
        ]
    )


def _course_value(data: Mapping[str, Any]) -> Any:
    if "course_id" in data and "class_id" in data and data["course_id"] != data["class_id"]:
        raise ClassroomError("course_id and class_id must refer to the same class.")
    return data.get("course_id", data.get("class_id"))


@transaction.atomic
def create_assessment(*, actor, data: Mapping[str, Any]) -> AssessmentDefinition:
    if not can_teach(actor) or not isinstance(data, Mapping):
        raise ClassroomError("An authenticated teacher is required to create an assessment.")
    allowed = {"title", "instructions", "course_id", "class_id", "settings", "items", "sections"}
    if set(data) - allowed:
        raise ClassroomError("Unsupported assessment fields.")
    course = _course(actor, _course_value(data))
    settings = _settings(data.get("settings"))
    rows = _item_rows(actor, data.get("items", []))
    assessment = AssessmentDefinition.objects.create(
        owner=actor,
        title=_text(data.get("title"), "title", MAX_TITLE_LENGTH, required=True),
        instructions=_text(data.get("instructions", ""), "instructions", MAX_INSTRUCTIONS_LENGTH),
        course=course,
        settings=settings,
    )
    _write_items(assessment, rows)
    from .assessment_sections import ensure_default_sections, set_sections

    if "sections" in data:
        set_sections(actor=actor, assessment=assessment, sections=data["sections"])
    else:
        ensure_default_sections(assessment)
    return assessment


def _expected_version(assessment: AssessmentDefinition, expected_version: Any) -> None:
    if (
        isinstance(expected_version, bool)
        or not isinstance(expected_version, int)
        or expected_version != assessment.version
    ):
        raise ClassroomError("The assessment changed; refresh before saving.")


@transaction.atomic
def update_assessment(
    *, actor, assessment: AssessmentDefinition, expected_version: int, data: Mapping[str, Any]
) -> AssessmentDefinition:
    _owner(actor, assessment)
    if not isinstance(data, Mapping) or not data:
        raise ClassroomError("Assessment changes are required.")
    allowed = {"title", "instructions", "course_id", "class_id", "settings", "sections"}
    if set(data) - allowed:
        raise ClassroomError("Unsupported assessment fields.")
    locked = AssessmentDefinition.objects.select_for_update().get(pk=assessment.pk)
    _expected_version(locked, expected_version)
    if "title" in data:
        locked.title = _text(data["title"], "title", MAX_TITLE_LENGTH, required=True)
    if "instructions" in data:
        locked.instructions = _text(data["instructions"], "instructions", MAX_INSTRUCTIONS_LENGTH)
    if "course_id" in data or "class_id" in data:
        locked.course = _course(actor, _course_value(data))
    if "settings" in data:
        locked.settings = _settings(data["settings"])
    if "sections" in data:
        from .assessment_sections import _write_sections, normalize_sections

        _write_sections(locked, normalize_sections(actor=actor, assessment=locked, sections=data["sections"]))
    locked.version += 1
    locked.save()
    return locked


@transaction.atomic
def replace_items(
    *, actor, assessment: AssessmentDefinition, expected_version: int, items: Sequence
) -> AssessmentDefinition:
    _owner(actor, assessment)
    locked = AssessmentDefinition.objects.select_for_update().get(pk=assessment.pk)
    _expected_version(locked, expected_version)
    rows = _item_rows(actor, items)
    _write_items(locked, rows)
    from .assessment_sections import _write_sections, default_sections

    # Replacing the fixed item list is the legacy authoring operation.  Keep
    # its established ordering and give it the compatibility default section.
    _write_sections(locked, default_sections(locked))
    locked.version += 1
    locked.save(update_fields=["version", "updated_at"])
    return locked


@transaction.atomic
def copy_assessment(*, actor, assessment: AssessmentDefinition, title: str | None = None) -> AssessmentDefinition:
    _owner(actor, assessment)
    source = AssessmentDefinition.objects.prefetch_related("items__question_revision").get(pk=assessment.pk)
    copied = AssessmentDefinition.objects.create(
        owner=actor,
        title=_text(title if title is not None else f"{source.title} (Copy)", "title", MAX_TITLE_LENGTH, required=True),
        instructions=source.instructions,
        course=source.course if source.course_id and can_author_course(actor, source.course) else None,
        settings=deepcopy(source.settings),
    )
    AssessmentItem.objects.bulk_create(
        [
            AssessmentItem(
                assessment=copied,
                key=uuid4(),
                position=item.position,
                question_revision=item.question_revision,
                points=item.points,
            )
            for item in source.items.all()
        ]
    )
    from .assessment_sections import _write_sections, default_sections, sections_payload

    source_sections = sections_payload(source)
    if source_sections and any(entry["kind"] == "pool" for section in source_sections for entry in section["entries"]):
        old_to_new = {
            str(source_item.key): copied_item
            for source_item, copied_item in zip(source.items.all(), copied.items.all())
        }
        copied_sections = []
        for section in source_sections:
            entries = []
            for entry in section["entries"]:
                if entry["kind"] == "fixed":
                    new_item = old_to_new.get(entry["item_key"])
                    if new_item is None:
                        continue
                    entries.append(
                        {
                            "key": entry["key"],
                            "position": entry["position"],
                            "kind": "fixed",
                            "item_key": str(new_item.key),
                        }
                    )
                else:
                    entries.append(entry)
            copied_sections.append(
                {
                    "key": section["key"],
                    "title": section["title"],
                    "position": section["position"],
                    "entries": entries,
                }
            )
        from .assessment_sections import normalize_sections

        _write_sections(copied, normalize_sections(actor=actor, assessment=copied, sections=copied_sections))
    else:
        _write_sections(copied, default_sections(copied))
    return copied


def item_payload(item: AssessmentItem, *, include_revision: bool = True) -> dict[str, Any]:
    revision = item.question_revision
    payload = {
        "key": str(item.key),
        "position": item.position,
        "points": _plain_decimal(item.points),
        "question_revision_id": revision.id,
        "definition_id": revision.definition_id,
        "type_key": revision.definition.type_key,
        "schema_version": revision.schema_version,
    }
    if include_revision:
        payload["definition"] = deepcopy(revision.payload)
        payload["metadata"] = deepcopy(revision.metadata)
    return payload


def assessment_payload(assessment: AssessmentDefinition, *, include_revision: bool = True) -> dict[str, Any]:
    items = [item_payload(item, include_revision=include_revision) for item in assessment.items.all()]
    total = sum((item.points for item in assessment.items.all()), Decimal("0"))
    from .assessment_sections import sections_payload

    return {
        "id": assessment.id,
        "title": assessment.title,
        "instructions": assessment.instructions,
        "course_id": assessment.course_id,
        "version": assessment.version,
        "settings": deepcopy(assessment.settings),
        "sections": sections_payload(assessment, include_private=include_revision),
        "items": items,
        "total_points": _plain_decimal(total),
        "updated_at": assessment.updated_at.isoformat(),
    }
