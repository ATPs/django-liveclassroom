"""Concrete per-attempt assignment from an immutable assessment-run manifest."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from random import SystemRandom
from typing import Any
from uuid import UUID, uuid4

from liveclassroom.models import AssessmentAttempt, AssessmentAttemptItem, AssessmentRun

from .classroom import ClassroomError

_UNORDERED_CHOICE_TYPES = frozenset(
    {
        "single_choice",
        "multiple_choice",
        "true_false",
        "liveclassroom.single_choice",
        "liveclassroom.multiple_choice",
        "liveclassroom.true_false",
    }
)


def _item_key(value: Any) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ClassroomError("The published assessment assignment is invalid.") from exc


def _points(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:  # pragma: no cover - corrupt stored manifests
        raise ClassroomError("The published assessment assignment is invalid.") from exc
    if not result.is_finite() or result <= 0:
        raise ClassroomError("The published assessment assignment is invalid.")
    return result


def _ordered_sections(manifest: dict) -> list[dict]:
    sections = manifest.get("sections")
    if not isinstance(sections, list) or not sections:
        return [{"position": 1, "entries": [{"kind": "fixed", "item": item} for item in manifest.get("items", [])]}]
    output: list[dict] = []
    for section in sorted(sections, key=lambda row: row.get("position", 0) if isinstance(row, dict) else 0):
        if not isinstance(section, dict) or not isinstance(section.get("entries"), list):
            raise ClassroomError("The published assessment assignment is invalid.")
        section = deepcopy(section)
        section["entries"] = sorted(
            section["entries"], key=lambda row: row.get("position", 0) if isinstance(row, dict) else 0
        )
        if not all(isinstance(entry, dict) for entry in section["entries"]):
            raise ClassroomError("The published assessment assignment is invalid.")
        output.append(section)
    return output


def _maybe_shuffle_options(item: dict, *, enabled: bool, rng) -> dict:
    assigned = deepcopy(item)
    payload = assigned.get("payload")
    type_key = assigned.get("type_key")
    if not enabled or type_key not in _UNORDERED_CHOICE_TYPES or not isinstance(payload, dict):
        return assigned
    options = payload.get("options")
    if not isinstance(options, list) or not all(isinstance(option, dict) and option.get("id") for option in options):
        return assigned
    options = deepcopy(options)
    rng.shuffle(options)
    payload["options"] = options
    assigned["payload"] = payload
    assigned["option_order"] = [str(option["id"]) for option in options]
    return assigned


def assigned_item_manifests(*, run: AssessmentRun, rng=None) -> list[dict]:
    """Select frozen candidates once; never query a mutable question bank."""
    manifest = run.manifest if isinstance(run.manifest, dict) else {}
    rng = rng or SystemRandom()
    chosen: list[dict] = []
    for section in _ordered_sections(manifest):
        section_chosen: list[dict] = []
        for entry in section["entries"]:
            kind = entry.get("kind")
            if kind == "fixed":
                item = entry.get("item")
                if not isinstance(item, dict):
                    raise ClassroomError("The published assessment assignment is invalid.")
                selected = [deepcopy(item)]
                shuffle_options = entry.get("shuffle_options", False)
                if not isinstance(shuffle_options, bool):
                    raise ClassroomError("The published assessment assignment is invalid.")
            elif kind == "pool":
                candidates = entry.get("candidates")
                count = entry.get("sample_size")
                if (
                    not isinstance(candidates, list)
                    or isinstance(count, bool)
                    or not isinstance(count, int)
                    or count < 1
                    or count > len(candidates)
                    or not all(isinstance(candidate, dict) for candidate in candidates)
                ):
                    raise ClassroomError("The published assessment pool assignment is invalid.")
                selected = [deepcopy(candidate) for candidate in rng.sample(candidates, count)]
                shuffle_options = entry.get("shuffle_options", False)
                if not isinstance(shuffle_options, bool):
                    raise ClassroomError("The published assessment pool assignment is invalid.")
            else:
                raise ClassroomError("The published assessment assignment is invalid.")
            section_chosen.extend(
                _maybe_shuffle_options(item, enabled=shuffle_options, rng=rng) for item in selected
            )
        shuffle_questions = section.get("shuffle_questions", False)
        if not isinstance(shuffle_questions, bool):
            raise ClassroomError("The published assessment assignment is invalid.")
        if shuffle_questions:
            rng.shuffle(section_chosen)
        chosen.extend(section_chosen)
    if not chosen:
        raise ClassroomError("The published assessment has no usable questions.")
    return chosen


def assign_attempt_items(*, run: AssessmentRun, attempt: AssessmentAttempt, rng=None) -> list[AssessmentAttemptItem]:
    """Persist every retained assignment before the attempt is exposed."""
    if attempt.run_id != run.id or attempt.items.exists():
        raise ClassroomError("Assessment items are already assigned or invalid.")
    manifests = assigned_item_manifests(run=run, rng=rng)
    rows = []
    for position, item in enumerate(manifests, 1):
        rows.append(
            AssessmentAttemptItem(
                attempt=attempt,
                key=uuid4(),
                position=position,
                points=_points(item.get("points")),
                manifest=deepcopy(item),
            )
        )
    AssessmentAttemptItem.objects.bulk_create(rows)
    return rows
