"""Portable, owner-scoped JSON content bundles.

The portable format deliberately contains definitions rather than database
identifiers.  This module is kept independent of the HTTP adapters so that
Markdown/YAML importers and host applications can use the same validator.  A
bundle is validated completely before an import starts, and imports create a
new owner-owned graph in one transaction.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from liveclassroom.models import (
    ActivityDefinition,
    ActivityDefinitionRevision,
    AssessmentDefinition,
    AssessmentSectionEntry,
    ClassroomAsset,
    Deck,
    Flow,
    QuestionBank,
    QuestionBankItem,
)
from liveclassroom.registry import activity_registry

from .assessments import _settings as normalize_assessment_settings
from .assessments import create_assessment
from .assets import create_uploaded_asset, discard_uploaded_asset, open_asset
from .classroom import ClassroomError
from .decks import create_deck
from .flows import add_flow_step, create_flow
from .permissions import can_edit_flow, can_read_asset, can_teach, can_use_activity_definition
from .question_banks import normalize_bank_filters
from .question_metadata import validate_question_metadata

FORMAT = "liveclassroom.portable"
VERSION = 1
MAX_ITEMS = 500
MAX_TEXT_BYTES = 200_000
MAX_NOTES_BYTES = 20_000
MAX_ASSET_BYTES = 10 * 1024 * 1024
MAX_BUNDLE_ASSET_BYTES = 50 * 1024 * 1024

_TOP_LEVEL = frozenset({"format", "version", "activities", "decks", "assessments", "banks", "flows", "assets"})
_COLLECTIONS = ("activities", "decks", "assessments", "banks", "flows", "assets")
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_SENSITIVE_KEYS = frozenset(
    {
        "session",
        "sessions",
        "participant",
        "participants",
        "submission",
        "submissions",
        "attempt",
        "attempts",
        "student_answer",
        "student_answers",
        "answer_submission",
        "runtime",
        "runtime_state",
        "grade",
        "grades",
        "grade_release",
        "release_state",
        "released",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
        "share_token",
        "server_path",
        "source_path",
        "filesystem_path",
    }
)


class PortableContentError(ValueError):
    """A user-correctable portable-content validation or import error."""


class PortablePermissionError(PortableContentError):
    """The actor cannot read or create the requested content."""


@dataclass(frozen=True)
class PortableBundle:
    """Validated canonical representation of one portable document."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.payload)

    def __getitem__(self, key: str) -> Any:
        return self.payload[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)

    @property
    def activities(self) -> list[dict[str, Any]]:
        return self.payload["activities"]

    @property
    def decks(self) -> list[dict[str, Any]]:
        return self.payload["decks"]

    @property
    def assessments(self) -> list[dict[str, Any]]:
        return self.payload["assessments"]

    @property
    def banks(self) -> list[dict[str, Any]]:
        return self.payload["banks"]

    @property
    def flows(self) -> list[dict[str, Any]]:
        return self.payload["flows"]

    @property
    def assets(self) -> list[dict[str, Any]]:
        return self.payload["assets"]


@dataclass
class ImportResult:
    """Objects created by an atomic import, grouped by portable type."""

    activities: list[ActivityDefinition]
    decks: list[Deck]
    assessments: list[AssessmentDefinition]
    banks: list[QuestionBank]
    flows: list[Flow]
    assets: list[ClassroomAsset]

    @property
    def all_objects(self) -> list[Any]:
        return [*self.activities, *self.decks, *self.assessments, *self.banks, *self.flows, *self.assets]

    @property
    def objects(self) -> list[dict[str, Any]]:
        """Small JSON-safe summaries used by HTTP adapters."""
        return [
            {"kind": kind, "id": obj.pk, "title": getattr(obj, "title", getattr(obj, "original_name", ""))}
            for kind, values in (
                ("activity", self.activities),
                ("deck", self.decks),
                ("assessment", self.assessments),
                ("bank", self.banks),
                ("flow", self.flows),
                ("asset", self.assets),
            )
            for obj in values
        ]


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, (str, bytes, bytearray)):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise PortableContentError("Portable content must be valid JSON.") from exc
    if not isinstance(value, Mapping):
        raise PortableContentError("Portable content must be a JSON object.")
    return dict(value)


def _check_sensitive(value: Any, *, path: str = "bundle") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise PortableContentError(f"{path} contains a non-finite number.")
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            if not isinstance(raw_key, str):
                raise PortableContentError(f"{path} contains a non-text field name.")
            if raw_key.casefold() in _SENSITIVE_KEYS:
                raise PortableContentError(f"{path}.{raw_key} is not portable content.")
            _check_sensitive(nested, path=f"{path}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _check_sensitive(nested, path=f"{path}[{index}]")


def _fields(row: Any, allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise PortableContentError(f"{label} must be an object.")
    unknown = set(row) - allowed
    if unknown:
        names = ", ".join(sorted(map(str, unknown)))
        raise PortableContentError(f"{label} contains unsupported fields: {names}.")
    return dict(row)


def _key(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _KEY_RE.fullmatch(value):
        raise PortableContentError(f"{label} must be a short local key.")
    return value


def _text(value: Any, label: str, *, required: bool = False, maximum: int = MAX_TEXT_BYTES) -> str:
    if not isinstance(value, str):
        raise PortableContentError(f"{label} must be text.")
    if "\x00" in value:
        raise PortableContentError(f"{label} contains a NUL character.")
    if required and not value.strip():
        raise PortableContentError(f"{label} is required.")
    if len(value.encode("utf-8")) > maximum:
        raise PortableContentError(f"{label} is too large.")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PortableContentError(f"{label} must be a positive integer.")
    return value


def _decimal_string(value: Any, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise PortableContentError(f"{label} must be a finite number.")
    try:
        result = Decimal(str(value).strip())
    except (DecimalException, ValueError) as exc:
        raise PortableContentError(f"{label} must be a finite number.") from exc
    if not result.is_finite() or result < 0:
        raise PortableContentError(f"{label} must be a finite nonnegative number.")
    if result.as_tuple().exponent < -6:
        raise PortableContentError(f"{label} has too many decimal places.")
    return format(result.normalize(), "f")


def _positive_decimal_string(value: Any, label: str) -> str:
    result = _decimal_string(value, label)
    if Decimal(result) <= 0:
        raise PortableContentError(f"{label} must be greater than zero.")
    return result


def _unique_keys(rows: Sequence[Mapping[str, Any]], label: str) -> None:
    keys = [_key(row.get("key"), f"{label} key") for row in rows]
    if len(keys) != len(set(keys)):
        raise PortableContentError(f"Duplicate {label} key.")


def _asset_row(row: Any, index: int) -> dict[str, Any]:
    row = _fields(
        row,
        {"key", "filename", "content_type", "sha256", "encoding", "data", "provider", "fingerprint"},
        f"asset {index}",
    )
    key = _key(row.get("key"), f"asset {index} key")
    filename = _text(row.get("filename"), f"asset {index} filename", required=True, maximum=255)
    if Path(filename).name != filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise PortableContentError(f"asset {index} filename must be a plain filename.")
    content_type = _text(
        row.get("content_type", "application/octet-stream"), f"asset {index} content_type", maximum=100
    )
    sha256 = row.get("sha256")
    if "provider" in row or "fingerprint" in row:
        provider = row.get("provider")
        fingerprint = row.get("fingerprint")
        if (
            not isinstance(provider, str)
            or not provider.strip()
            or not isinstance(fingerprint, str)
            or not fingerprint.strip()
        ):
            raise PortableContentError(f"asset {index} provider reference is invalid.")
        if "data" in row or "encoding" in row:
            raise PortableContentError(f"asset {index} cannot contain both bytes and a provider reference.")
        result = {
            "key": key,
            "filename": filename,
            "content_type": content_type,
            "provider": provider.strip(),
            "fingerprint": fingerprint.strip(),
        }
        if sha256 is not None:
            if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
                raise PortableContentError(f"asset {index} sha256 must be a 64-character hex digest.")
            result["sha256"] = sha256.lower()
        return result
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise PortableContentError(f"asset {index} sha256 must be a 64-character hex digest.")
    if row.get("encoding", "base64") != "base64" or not isinstance(row.get("data"), str):
        raise PortableContentError(f"asset {index} data must be base64 text.")
    try:
        raw = base64.b64decode(row["data"].encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise PortableContentError(f"asset {index} data is not valid base64.") from exc
    if not raw or len(raw) > MAX_ASSET_BYTES:
        raise PortableContentError(f"asset {index} exceeds the 10 MiB limit or is empty.")
    if hashlib.sha256(raw).hexdigest() != sha256.lower():
        raise PortableContentError(f"asset {index} sha256 does not match its bytes.")
    return {
        "key": key,
        "filename": filename,
        "content_type": content_type,
        "sha256": sha256.lower(),
        "encoding": "base64",
        "data": row["data"],
    }


def _activity_row(row: Any, index: int) -> dict[str, Any]:
    row = _fields(
        row,
        {"key", "type_key", "schema_version", "title", "definition", "metadata", "asset_key"},
        f"activity {index}",
    )
    key = _key(row.get("key"), f"activity {index} key")
    type_key = row.get("type_key")
    if not isinstance(type_key, str) or not type_key.strip() or "." not in type_key:
        raise PortableContentError(f"activity {index} type_key is invalid.")
    type_key = type_key.strip()
    if row.get("schema_version") != VERSION:
        raise PortableContentError(f"activity {index} schema_version is unsupported.")
    title = _text(row.get("title"), f"activity {index} title", required=True, maximum=200)
    definition = row.get("definition")
    if not isinstance(definition, Mapping):
        raise PortableContentError(f"activity {index} definition must be an object.")
    definition = deepcopy(dict(definition))
    metadata = row.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise PortableContentError(f"activity {index} metadata must be an object.")
    try:
        activity_type = activity_registry.get(type_key)
        probe = deepcopy(definition)
        asset_key = row.get("asset_key", definition.get("asset_key"))
        if type_key == "liveclassroom.file" and asset_key is not None:
            probe["asset_id"] = str(UUID(int=0))
            probe.pop("asset_key", None)
        activity_type.validate(probe)
        normalized_metadata = validate_question_metadata(dict(metadata))
    except (KeyError, TypeError, ValueError) as exc:
        raise PortableContentError(f"activity {index} is not a valid registered definition: {exc}") from exc
    asset_key = row.get("asset_key", definition.get("asset_key"))
    if asset_key is not None:
        asset_key = _key(asset_key, f"activity {index} asset_key")
    if "asset_key" in definition and definition["asset_key"] != asset_key:
        raise PortableContentError(f"activity {index} has conflicting asset references.")
    if type_key == "liveclassroom.file" and asset_key is None:
        raise PortableContentError(f"activity {index} file content needs an asset_key.")
    if type_key != "liveclassroom.file" and asset_key is not None:
        raise PortableContentError(f"activity {index} may not reference an asset.")
    definition.pop("asset_key", None)
    return {
        "key": key,
        "type_key": type_key.strip(),
        "schema_version": VERSION,
        "title": title,
        "definition": definition,
        "metadata": normalized_metadata,
        **({"asset_key": asset_key} if asset_key is not None else {}),
    }


def _slide_row(row: Any, index: int) -> dict[str, Any]:
    row = _fields(row, {"key", "position", "markdown", "notes", "asset_keys"}, f"slide {index}")
    result = {
        "key": _key(row.get("key", f"slide-{index}"), f"slide {index} key"),
        "position": _positive_int(row.get("position"), f"slide {index} position"),
        "markdown": _text(row.get("markdown"), f"slide {index} markdown"),
        "notes": _text(row.get("notes", ""), f"slide {index} notes", maximum=MAX_NOTES_BYTES),
    }
    asset_keys = row.get("asset_keys", [])
    if not isinstance(asset_keys, list) or any(not isinstance(key, str) for key in asset_keys):
        raise PortableContentError(f"slide {index} asset_keys must be a list of keys.")
    if len(asset_keys) != len(set(asset_keys)):
        raise PortableContentError(f"slide {index} asset_keys must be unique.")
    result["asset_keys"] = [_key(key, f"slide {index} asset key") for key in asset_keys]
    return result


def _deck_row(row: Any, index: int) -> dict[str, Any]:
    row = _fields(row, {"key", "title", "theme", "slides"}, f"deck {index}")
    slides = row.get("slides")
    if not isinstance(slides, list) or not slides or len(slides) > MAX_ITEMS:
        raise PortableContentError(f"deck {index} must contain between one and {MAX_ITEMS} slides.")
    result = {
        "key": _key(row.get("key", f"deck-{index}"), f"deck {index} key"),
        "title": _text(row.get("title"), f"deck {index} title", required=True, maximum=200),
        "theme": _text(row.get("theme", "default"), f"deck {index} theme", required=True, maximum=80),
        "slides": [_slide_row(item, position) for position, item in enumerate(slides, 1)],
    }
    _unique_keys(result["slides"], f"deck {index} slide")
    positions = [slide["position"] for slide in result["slides"]]
    if sorted(positions) != list(range(1, len(positions) + 1)):
        raise PortableContentError(f"deck {index} slide positions must be contiguous.")
    result["slides"].sort(key=lambda item: (item["position"], item["key"]))
    return result


def _assessment_row(row: Any, index: int) -> dict[str, Any]:
    row = _fields(row, {"key", "title", "instructions", "items", "settings", "sections"}, f"assessment {index}")
    raw_items = row.get("items", [])
    if not isinstance(raw_items, list) or len(raw_items) > MAX_ITEMS:
        raise PortableContentError(f"assessment {index} items must be a list of at most {MAX_ITEMS}.")
    items = []
    for position, item in enumerate(raw_items, 1):
        item = _fields(item, {"key", "activity_key", "points"}, f"assessment {index} item {position}")
        items.append(
            {
                "key": _key(item.get("key", f"item-{position}"), f"assessment {index} item {position} key"),
                "activity_key": _key(item.get("activity_key"), f"assessment {index} item {position} activity_key"),
                "points": _positive_decimal_string(
                    item.get("points", "1"), f"assessment {index} item {position} points"
                ),
            }
        )
    _unique_keys(items, f"assessment {index} item")
    settings = row.get("settings", {})
    if not isinstance(settings, Mapping):
        raise PortableContentError(f"assessment {index} settings must be an object.")
    result = {
        "key": _key(row.get("key"), f"assessment {index} key"),
        "title": _text(row.get("title"), f"assessment {index} title", required=True, maximum=200),
        "instructions": _text(row.get("instructions", ""), f"assessment {index} instructions"),
        "items": items,
        "settings": deepcopy(dict(settings)),
    }
    if "sections" in row:
        sections = row["sections"]
        if not isinstance(sections, list) or not sections or len(sections) > MAX_ITEMS:
            raise PortableContentError(f"assessment {index} sections must be a list.")
        normalized_sections = []
        for section_index, section in enumerate(sections, 1):
            section = _fields(
                section, {"key", "title", "position", "entries"}, f"assessment {index} section {section_index}"
            )
            entries = section.get("entries", [])
            if not isinstance(entries, list) or len(entries) > MAX_ITEMS:
                raise PortableContentError(f"assessment {index} section {section_index} entries must be a list.")
            normalized_entries = []
            for entry_index, entry in enumerate(entries, 1):
                entry = _fields(
                    entry,
                    {
                        "key",
                        "position",
                        "kind",
                        "item_key",
                        "bank_key",
                        "filters",
                        "sample_size",
                        "points",
                        "shuffle_options",
                    },
                    f"assessment {index} section {section_index} entry {entry_index}",
                )
                kind = entry.get("kind")
                if kind not in {"fixed", "pool"}:
                    raise PortableContentError("Assessment section entry kind must be fixed or pool.")
                normalized = {
                    "key": _key(entry.get("key"), "section entry key"),
                    "position": _positive_int(entry.get("position"), "section entry position"),
                    "kind": kind,
                }
                if kind == "fixed":
                    normalized["item_key"] = _key(entry.get("item_key"), "fixed section item_key")
                else:
                    normalized["bank_key"] = _key(entry.get("bank_key"), "pool section bank_key")
                    filters = entry.get("filters", {})
                    if not isinstance(filters, Mapping):
                        raise PortableContentError("Pool filters must be an object.")
                    try:
                        normalized["filters"] = normalize_bank_filters(filters)
                    except ClassroomError as exc:
                        raise PortableContentError(f"Pool filters are invalid: {exc}") from exc
                    if entry.get("sample_size") is not None:
                        sample_size = _positive_int(entry["sample_size"], "pool sample_size")
                        if sample_size > MAX_ITEMS:
                            raise PortableContentError("pool sample_size is too large.")
                        normalized["sample_size"] = sample_size
                    if entry.get("points") is not None:
                        normalized["points"] = _positive_decimal_string(entry["points"], "pool points")
                    normalized["shuffle_options"] = entry.get("shuffle_options", False)
                    if not isinstance(normalized["shuffle_options"], bool):
                        raise PortableContentError("pool shuffle_options must be boolean.")
                normalized_entries.append(normalized)
            _unique_keys(normalized_entries, "section entry")
            positions = [entry["position"] for entry in normalized_entries]
            if sorted(positions) != list(range(1, len(positions) + 1)):
                raise PortableContentError("Assessment section entry positions must be contiguous.")
            normalized_entries.sort(key=lambda item: (item["position"], item["key"]))
            normalized_sections.append(
                {
                    "key": _key(section.get("key"), "assessment section key"),
                    "title": _text(section.get("title"), "assessment section title", required=True, maximum=200),
                    "position": _positive_int(section.get("position"), "assessment section position"),
                    "entries": normalized_entries,
                }
            )
        _unique_keys(normalized_sections, "assessment section")
        positions = [section["position"] for section in normalized_sections]
        if sorted(positions) != list(range(1, len(positions) + 1)):
            raise PortableContentError("Assessment section positions must be contiguous.")
        normalized_sections.sort(key=lambda item: (item["position"], item["key"]))
        result["sections"] = normalized_sections
    try:
        result["settings"] = normalize_assessment_settings(dict(settings))
    except (ClassroomError, TypeError, ValueError) as exc:
        raise PortableContentError(f"assessment {index} settings are invalid: {exc}") from exc
    return result


def _bank_row(row: Any, index: int) -> dict[str, Any]:
    row = _fields(row, {"key", "title", "description", "question_keys"}, f"bank {index}")
    question_keys = row.get("question_keys", [])
    if not isinstance(question_keys, list):
        raise PortableContentError(f"bank {index} question_keys must be a list.")
    normalized = [_key(key, f"bank {index} question key") for key in question_keys]
    if len(normalized) != len(set(normalized)):
        raise PortableContentError(f"bank {index} question_keys must be unique.")
    return {
        "key": _key(row.get("key"), f"bank {index} key"),
        "title": _text(row.get("title"), f"bank {index} title", required=True, maximum=200),
        "description": _text(row.get("description", ""), f"bank {index} description"),
        "question_keys": normalized,
    }


def _flow_row(row: Any, index: int) -> dict[str, Any]:
    row = _fields(row, {"key", "title", "description", "steps"}, f"flow {index}")
    steps = row.get("steps", [])
    if not isinstance(steps, list) or len(steps) > MAX_ITEMS:
        raise PortableContentError(f"flow {index} steps must be a list.")
    normalized_steps = []
    for step_index, step in enumerate(steps, 1):
        if isinstance(step, str):
            normalized_steps.append(_key(step, f"flow {index} step {step_index}"))
            continue
        step = _fields(step, {"key", "position", "activity_key"}, f"flow {index} step {step_index}")
        normalized_steps.append(
            {
                "key": _key(step.get("key"), f"flow {index} step key"),
                "position": _positive_int(step.get("position"), f"flow {index} step position"),
                "activity_key": _key(step.get("activity_key"), f"flow {index} step activity_key"),
            }
        )
    if normalized_steps and all(isinstance(step, Mapping) for step in normalized_steps):
        positions = [step["position"] for step in normalized_steps]
        if sorted(positions) != list(range(1, len(positions) + 1)):
            raise PortableContentError(f"flow {index} step positions must be contiguous.")
        normalized_steps.sort(key=lambda item: (item["position"], item["key"]))
        keys = [step["key"] for step in normalized_steps]
        if len(keys) != len(set(keys)):
            raise PortableContentError(f"flow {index} step keys must be unique.")
    return {
        "key": _key(row.get("key"), f"flow {index} key"),
        "title": _text(row.get("title"), f"flow {index} title", required=True, maximum=200),
        "description": _text(row.get("description", ""), f"flow {index} description"),
        "steps": normalized_steps,
    }


def validate_portable(payload: Any) -> PortableBundle:
    """Validate and canonicalize a portable envelope without database writes."""
    source = _json_object(payload)
    unknown = set(source) - _TOP_LEVEL
    if unknown:
        raise PortableContentError(f"Unsupported portable fields: {', '.join(sorted(map(str, unknown)))}.")
    if source.get("format") != FORMAT or source.get("version") != VERSION:
        raise PortableContentError("Unsupported portable format or version.")
    _check_sensitive(source)
    normalized: dict[str, Any] = {"format": FORMAT, "version": VERSION}
    rows: dict[str, list[dict[str, Any]]] = {}
    for collection in _COLLECTIONS:
        value = source.get(collection, [])
        if not isinstance(value, list) or len(value) > MAX_ITEMS:
            raise PortableContentError(f"{collection} must be a list of at most {MAX_ITEMS} entries.")
        rows[collection] = value
    normalized["assets"] = [_asset_row(row, index) for index, row in enumerate(rows["assets"], 1)]
    _unique_keys(normalized["assets"], "asset")
    total = 0
    for asset in normalized["assets"]:
        if "data" in asset:
            total += len(base64.b64decode(asset["data"]))
    if total > MAX_BUNDLE_ASSET_BYTES:
        raise PortableContentError("Portable assets exceed the 50 MiB bundle limit.")
    normalized["activities"] = [_activity_row(row, index) for index, row in enumerate(rows["activities"], 1)]
    _unique_keys(normalized["activities"], "activity")
    normalized["decks"] = [_deck_row(row, index) for index, row in enumerate(rows["decks"], 1)]
    _unique_keys(normalized["decks"], "deck")
    normalized["assessments"] = [_assessment_row(row, index) for index, row in enumerate(rows["assessments"], 1)]
    _unique_keys(normalized["assessments"], "assessment")
    normalized["banks"] = [_bank_row(row, index) for index, row in enumerate(rows["banks"], 1)]
    _unique_keys(normalized["banks"], "bank")
    normalized["flows"] = [_flow_row(row, index) for index, row in enumerate(rows["flows"], 1)]
    _unique_keys(normalized["flows"], "flow")
    top_level_keys = [row["key"] for collection in _COLLECTIONS for row in normalized[collection]]
    if len(top_level_keys) != len(set(top_level_keys)):
        raise PortableContentError("Duplicate local key across portable objects.")

    activity_keys = {row["key"] for row in normalized["activities"]}
    asset_keys = {row["key"] for row in normalized["assets"]}
    bank_keys = {row["key"] for row in normalized["banks"]}
    item_keys: set[str] = set()
    for activity in normalized["activities"]:
        if activity.get("asset_key") not in (None, *asset_keys):
            raise PortableContentError(f"Activity {activity['key']} references a missing asset.")
    for deck in normalized["decks"]:
        for slide in deck["slides"]:
            missing = set(slide["asset_keys"]) - asset_keys
            if missing:
                raise PortableContentError(f"Slide {slide['key']} references a missing asset.")
    for assessment in normalized["assessments"]:
        for item in assessment["items"]:
            if item["activity_key"] not in activity_keys:
                raise PortableContentError(f"Assessment item {item['key']} references a missing activity.")
            if item["key"] in item_keys:
                raise PortableContentError(f"Duplicate assessment item key {item['key']}.")
            item_keys.add(item["key"])
        for section in assessment.get("sections", []):
            for entry in section["entries"]:
                if entry["kind"] == "fixed" and entry["item_key"] not in {item["key"] for item in assessment["items"]}:
                    raise PortableContentError(f"Section entry {entry['key']} references a missing item.")
                if entry["kind"] == "pool" and entry["bank_key"] not in bank_keys:
                    raise PortableContentError(f"Section entry {entry['key']} references a missing bank.")
    for bank in normalized["banks"]:
        missing = set(bank["question_keys"]) - activity_keys
        if missing:
            raise PortableContentError(f"Bank {bank['key']} references a missing activity.")
    for flow in normalized["flows"]:
        for step in flow["steps"]:
            key = step if isinstance(step, str) else step["activity_key"]
            if key not in activity_keys:
                raise PortableContentError(f"Flow {flow['key']} references a missing activity.")
    # A canonical sort makes JSON dumps deterministic while preserving explicit
    # source ordering inside decks, assessments, pools and flows.
    for collection in _COLLECTIONS:
        normalized[collection].sort(key=lambda row: row["key"])
    return PortableBundle(normalized)


def _require_teacher(actor) -> None:
    if not can_teach(actor):
        raise PortablePermissionError("An authenticated teacher is required for portable content.")


def _validate_provider_definition(actor: Any, definition: Mapping[str, Any]) -> None:
    """Reauthorize an optional provider-backed activity at use time.

    Activity definitions store a safe URL/provider pair rather than a live
    provider object.  If a host has configured such a provider, ask it to
    validate the exact reference before exporting or importing the definition.
    Plain local activities do not import the optional provider registry.
    """
    provider_key = definition.get("provider")
    if provider_key is None:
        return
    if not isinstance(provider_key, str) or not provider_key.strip():
        raise PortablePermissionError("The provider-backed activity is unavailable or unauthorized.")
    try:
        from liveclassroom.providers import ContentReference, content_providers

        provider = content_providers().get(provider_key.strip())
        raw_reference = definition.get("reference")
        if isinstance(raw_reference, Mapping):
            reference = ContentReference(
                provider_key.strip(),
                str(raw_reference.get("kind", "")),
                dict(raw_reference.get("value", {})),
            )
        elif isinstance(definition.get("url"), str):
            reference = provider.parse_reference(definition["url"])
        else:
            raise ValueError("a provider reference or URL is required")
        provider.validate_reference(reference)
    except Exception as exc:
        # Provider implementations intentionally own their detailed policy;
        # portable errors expose only a stable, path-free message.
        raise PortablePermissionError("The provider-backed activity is unavailable or unauthorized.") from exc


def _owned(actor, obj: Any, *, flow: bool = False) -> None:
    _require_teacher(actor)
    if flow:
        allowed = can_edit_flow(actor, obj)
    else:
        allowed = obj.owner_id == actor.pk or getattr(actor, "is_superuser", False)
    if not allowed:
        raise PortablePermissionError("You do not have permission to export this content.")


class _ExportContext:
    def __init__(self, actor):
        self.actor = actor
        self.activities: list[dict[str, Any]] = []
        self.decks: list[dict[str, Any]] = []
        self.assessments: list[dict[str, Any]] = []
        self.banks: list[dict[str, Any]] = []
        self.flows: list[dict[str, Any]] = []
        self.assets: list[dict[str, Any]] = []
        self.activity_keys: dict[tuple[int, int], str] = {}
        self.bank_keys: dict[int, str] = {}
        self.asset_keys: dict[int, str] = {}
        self.item_keys: dict[int, str] = {}

    def add_asset(self, asset: ClassroomAsset | None) -> str | None:
        if asset is None:
            return None
        if asset.pk in self.asset_keys:
            return self.asset_keys[asset.pk]
        if not can_read_asset(self.actor, asset):
            raise PortablePermissionError("You do not have permission to export this asset.")
        try:
            handle, size = open_asset(asset)
            try:
                raw = handle.read()
            finally:
                handle.close()
        except ClassroomError as exc:
            raise PortableContentError(str(exc)) from exc
        if size > MAX_ASSET_BYTES or len(raw) > MAX_ASSET_BYTES:
            raise PortableContentError("Referenced asset exceeds the 10 MiB portable limit.")
        key = f"asset-{len(self.assets) + 1}"
        self.asset_keys[asset.pk] = key
        self.assets.append(
            {
                "key": key,
                "filename": Path(asset.original_name).name,
                "content_type": asset.content_type,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "encoding": "base64",
                "data": base64.b64encode(raw).decode("ascii"),
            }
        )
        return key

    def add_activity(
        self, definition: ActivityDefinition | None = None, revision: ActivityDefinitionRevision | None = None
    ) -> str:
        source = definition or (revision.definition if revision is not None else None)
        if source is None:
            raise PortableContentError("An activity source is required.")
        revision = revision or source.current_revision
        if revision is None:
            raise PortableContentError("The activity has no immutable revision to export.")
        source_key = (source.pk, revision.pk)
        if source_key in self.activity_keys:
            return self.activity_keys[source_key]
        if not can_use_activity_definition(self.actor, source):
            raise PortablePermissionError("You do not have permission to export this activity.")
        type_key = source.type_key
        definition_payload = deepcopy(revision.payload)
        _validate_provider_definition(self.actor, definition_payload)
        asset = revision.asset or source.asset
        asset_key = self.add_asset(asset)
        if asset_key is not None:
            definition_payload.pop("asset_id", None)
            definition_payload["asset_key"] = asset_key
        metadata = deepcopy(revision.metadata if isinstance(revision.metadata, dict) else source.metadata)
        key = f"activity-{len(self.activities) + 1}"
        self.activity_keys[source_key] = key
        self.activities.append(
            {
                "key": key,
                "type_key": type_key,
                "schema_version": revision.schema_version,
                "title": source.title,
                "definition": definition_payload,
                "metadata": metadata,
                **({"asset_key": asset_key} if asset_key is not None else {}),
            }
        )
        return key

    def add_bank(self, bank: QuestionBank) -> str:
        _owned(self.actor, bank)
        if bank.pk in self.bank_keys:
            return self.bank_keys[bank.pk]
        key = f"bank-{len(self.banks) + 1}"
        self.bank_keys[bank.pk] = key
        memberships = list(bank.items.select_related("definition").order_by("position", "id"))
        question_keys = [self.add_activity(item.definition) for item in memberships]
        self.banks.append(
            {"key": key, "title": bank.title, "description": bank.description, "question_keys": question_keys}
        )
        return key

    def add_deck(self, deck: Deck) -> None:
        _owned(self.actor, deck)
        slides = []
        for slide in deck.slides.prefetch_related("assets").order_by("position", "id"):
            slides.append(
                {
                    "key": f"slide-{slide.key}",
                    "position": slide.position,
                    "markdown": slide.markdown,
                    "notes": slide.notes,
                    "asset_keys": [key for asset in slide.assets.all() if (key := self.add_asset(asset))],
                }
            )
        self.decks.append(
            {"key": f"deck-{len(self.decks) + 1}", "title": deck.title, "theme": deck.theme, "slides": slides}
        )

    def add_assessment(self, assessment: AssessmentDefinition) -> None:
        _owned(self.actor, assessment)
        item_rows = []
        for item in assessment.items.select_related("question_revision__definition").order_by("position", "id"):
            activity_key = self.add_activity(revision=item.question_revision)
            item_key = f"item-{len(self.item_keys) + 1}"
            self.item_keys[item.pk] = item_key
            item_rows.append(
                {"key": item_key, "activity_key": activity_key, "points": format(item.points.normalize(), "f")}
            )
        result = {
            "key": f"assessment-{len(self.assessments) + 1}",
            "title": assessment.title,
            "instructions": assessment.instructions,
            "items": item_rows,
            "settings": deepcopy(assessment.settings if isinstance(assessment.settings, dict) else {}),
        }
        sections = []
        for section in assessment.sections.prefetch_related("entries__item", "entries__bank").order_by(
            "position", "id"
        ):
            entries = []
            for entry in section.entries.order_by("position", "id"):
                row = {"key": f"entry-{entry.key}", "position": entry.position, "kind": entry.kind}
                if entry.kind == AssessmentSectionEntry.Kind.FIXED and entry.item_id in self.item_keys:
                    row["item_key"] = self.item_keys[entry.item_id]
                elif entry.kind == AssessmentSectionEntry.Kind.POOL and entry.bank_id:
                    row.update(
                        {
                            "bank_key": self.add_bank(entry.bank),
                            "filters": deepcopy(entry.filters),
                            "sample_size": entry.sample_size,
                            "points": format(entry.points.normalize(), "f") if entry.points is not None else None,
                            "shuffle_options": entry.shuffle_options,
                        }
                    )
                else:
                    continue
                entries.append(row)
            sections.append(
                {
                    "key": f"section-{section.key}",
                    "title": section.title,
                    "position": section.position,
                    "entries": entries,
                }
            )
        if sections:
            result["sections"] = sections
        self.assessments.append(result)

    def add_flow(self, flow: Flow) -> None:
        _owned(self.actor, flow, flow=True)
        steps = []
        for step in flow.steps.select_related("activity_definition").order_by("position", "id"):
            steps.append(self.add_activity(step.activity_definition))
        self.flows.append(
            {"key": f"flow-{len(self.flows) + 1}", "title": flow.title, "description": flow.description, "steps": steps}
        )


def export_portable(*, actor, kind: str, object_id: Any) -> dict[str, Any]:
    """Export one exact owner-visible object and its reusable dependency graph."""
    _require_teacher(actor)
    if not isinstance(kind, str) or not kind.strip():
        raise PortableContentError("A portable object kind is required.")
    kind = {"question": "activity", "lesson": "flow", "course": "flow"}.get(
        kind.casefold().strip(), kind.casefold().strip()
    )
    try:
        object_id = int(object_id)
    except (TypeError, ValueError) as exc:
        raise PortableContentError("object_id must be a positive integer.") from exc
    if object_id <= 0:
        raise PortableContentError("object_id must be a positive integer.")
    models = {
        "activity": ActivityDefinition,
        "bank": QuestionBank,
        "deck": Deck,
        "assessment": AssessmentDefinition,
        "flow": Flow,
    }
    model = models.get(kind)
    if model is None:
        raise PortableContentError("Unsupported portable object kind.")
    try:
        obj = model.objects.get(pk=object_id)
    except model.DoesNotExist as exc:
        raise PortableContentError("Portable object not found.") from exc
    context = _ExportContext(actor)
    if kind == "activity":
        _owned(actor, obj)
        context.add_activity(obj)
    elif kind == "bank":
        context.add_bank(obj)
    elif kind == "deck":
        context.add_deck(obj)
    elif kind == "assessment":
        context.add_assessment(obj)
    else:
        context.add_flow(obj)
    payload = {
        "format": FORMAT,
        "version": VERSION,
        "activities": context.activities,
        "decks": context.decks,
        "assessments": context.assessments,
        "banks": context.banks,
        "flows": context.flows,
        "assets": context.assets,
    }
    return validate_portable(payload).to_dict()


def _asset_import(actor, row: Mapping[str, Any]) -> ClassroomAsset:
    if "provider" in row:
        raise PortableContentError("Provider asset references require a host asset adapter.")
    raw = base64.b64decode(row["data"].encode("ascii"), validate=True)
    uploaded = SimpleUploadedFile(row["filename"], raw, content_type=row["content_type"])
    return create_uploaded_asset(owner=actor, uploaded_file=uploaded)


@transaction.atomic
def import_portable(*, actor, payload: Any, mode: str = "copy") -> ImportResult:
    """Validate and atomically copy a complete portable graph to ``actor``."""
    _require_teacher(actor)
    if mode != "copy":
        raise PortableContentError("Only copy mode is supported.")
    bundle = validate_portable(payload)
    created_assets: list[ClassroomAsset] = []
    try:
        assets: dict[str, ClassroomAsset] = {}
        for row in bundle.payload["assets"]:
            asset = _asset_import(actor, row)
            created_assets.append(asset)
            assets[row["key"]] = asset

        activities: dict[str, ActivityDefinition] = {}
        for row in bundle.payload["activities"]:
            definition = deepcopy(row["definition"])
            _validate_provider_definition(actor, definition)
            asset = assets.get(row.get("asset_key"))
            if row["type_key"] == "liveclassroom.file":
                if asset is None:
                    raise PortableContentError(f"Activity {row['key']} has no imported asset.")
                definition["asset_id"] = str(asset.public_id)
            activity = ActivityDefinition.objects.create(
                owner=actor,
                title=row["title"],
                type_key=row["type_key"],
                schema_version=row["schema_version"],
                definition=definition,
                metadata=deepcopy(row["metadata"]),
                asset=asset,
                status=ActivityDefinition.Status.READY,
            )
            # The post_save signal creates the first immutable revision.  Keep
            # the imported schema/version and metadata synchronized when the
            # model was created through a direct ORM path.
            activity.refresh_from_db()
            activities[row["key"]] = activity

        banks: dict[str, QuestionBank] = {}
        for row in bundle.payload["banks"]:
            bank = QuestionBank.objects.create(owner=actor, title=row["title"], description=row["description"])
            for position, activity_key in enumerate(row["question_keys"], 1):
                definition = activities[activity_key]
                QuestionBankItem.objects.create(bank=bank, definition=definition, position=position)
            banks[row["key"]] = bank

        decks: list[Deck] = []
        for row in bundle.payload["decks"]:
            deck = create_deck(
                actor=actor,
                data={
                    "title": row["title"],
                    "theme": row["theme"],
                    "slides": [
                        {
                            "markdown": slide["markdown"],
                            "notes": slide["notes"],
                            "asset_ids": [str(assets[key].public_id) for key in slide["asset_keys"]],
                        }
                        for slide in row["slides"]
                    ],
                },
            )
            decks.append(deck)

        assessments: list[AssessmentDefinition] = []
        for row in bundle.payload["assessments"]:
            item_key_to_uuid = {item["key"]: str(uuid4()) for item in row["items"]}
            assessment_data = {
                "title": row["title"],
                "instructions": row["instructions"],
                "settings": row["settings"],
                "items": [
                    {
                        "key": item_key_to_uuid[item["key"]],
                        "revision_id": activities[item["activity_key"]].current_revision_id,
                        "points": item["points"],
                    }
                    for item in row["items"]
                ],
            }
            if "sections" in row:
                assessment_data["sections"] = []
                for section in row["sections"]:
                    entries = []
                    for entry in section["entries"]:
                        item = {
                            "key": str(uuid4()),
                            "position": entry["position"],
                            "kind": entry["kind"],
                        }
                        if entry["kind"] == "fixed":
                            item["item_key"] = item_key_to_uuid[entry["item_key"]]
                        else:
                            item.update(
                                {
                                    "bank_id": banks[entry["bank_key"]].pk,
                                    "filters": entry.get("filters", {}),
                                    "sample_size": entry.get("sample_size"),
                                    "points": entry.get("points"),
                                    "shuffle_options": entry.get("shuffle_options", False),
                                }
                            )
                        entries.append(item)
                    assessment_data["sections"].append(
                        {
                            "key": str(uuid4()),
                            "title": section["title"],
                            "position": section["position"],
                            "entries": entries,
                        }
                    )
            assessments.append(create_assessment(actor=actor, data=assessment_data))

        flows: list[Flow] = []
        for row in bundle.payload["flows"]:
            flow = create_flow(title=row["title"], description=row["description"], creator=actor)
            for position, step in enumerate(row["steps"], 1):
                activity_key = step if isinstance(step, str) else step["activity_key"]
                add_flow_step(flow=flow, actor=actor, activity_definition=activities[activity_key], position=position)
            flows.append(flow)
        return ImportResult(
            activities=list(activities.values()),
            decks=decks,
            assessments=assessments,
            banks=list(banks.values()),
            flows=flows,
            assets=created_assets,
        )
    except Exception:
        for asset in created_assets:
            try:
                discard_uploaded_asset(asset)
            except Exception:
                pass
        raise


__all__ = [
    "FORMAT",
    "VERSION",
    "ImportResult",
    "PortableBundle",
    "PortableContentError",
    "PortablePermissionError",
    "export_portable",
    "import_portable",
    "validate_portable",
]
