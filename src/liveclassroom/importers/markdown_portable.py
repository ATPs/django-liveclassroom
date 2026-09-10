"""Translate teacher Markdown/YAML documents into the portable v1 envelope.

VaultPub owns Markdown frontmatter and slide segmentation.  This module only
adapts those public results to the package's existing portable-content
validator; it never renders Markdown or reads a path from the submitted
document.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

from liveclassroom.registry import activity_registry
from liveclassroom.services.portable_content import (
    FORMAT,
    VERSION,
    PortableContentError,
    validate_portable,
)

try:  # VaultPub remains an optional package dependency.
    from vaultpub.core.frontmatter import parse_frontmatter as _vaultpub_frontmatter
    from vaultpub.core.render.slides import (
        READING_THEMES,
        SLIDE_SPLIT_POLICIES,
    )
    from vaultpub.core.render.slides import (
        segment_slides as _vaultpub_segment_slides,
    )
    from vaultpub.core.render.slides import (
        slide_options as _vaultpub_slide_options,
    )
except ImportError as _vaultpub_import_error:  # pragma: no cover - optional dependency check
    _vaultpub_frontmatter = None
    _vaultpub_segment_slides = None
    _vaultpub_slide_options = None
    SLIDE_SPLIT_POLICIES = frozenset()
    READING_THEMES = frozenset()
else:
    _vaultpub_import_error = None


MAX_SOURCE_BYTES = 2_000_000
MAX_DOCUMENT_ITEMS = 500
SUPPORTED_SUFFIXES = frozenset({".md", ".yaml", ".yml"})
SUPPORTED_KINDS = frozenset({"question", "deck", "lesson", "assessment"})
_FRONTMATTER_KEYS = frozenset(
    {
        "kind",
        "key",
        "title",
        "description",
        "metadata",
        "settings",
        "assets",
        "theme",
        "slide",
        "split",
        "slides",
        "type",
        "type_key",
        "definition",
        "prompt",
        "question",
        "markdown",
        "options",
        "choices",
        "answer",
        "correct_answer",
        "tolerance",
        "partial_credit",
        "case_sensitive",
        "explanation",
        "instructions",
        "items",
        "activities",
        "sections",
        "steps",
    }
)
_SLIDE_KEYS = frozenset(
    {
        "theme",
        "transition",
        "controls",
        "progress",
        "slideNumber",
        "center",
        "width",
        "height",
        "hash",
        "split",
        "codeWrap",
    }
)
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*(?:<(?P<bracket>[^>]+)>|(?P<plain>[^\s)]+))(?:\s+[^)]*)?\s*\)")
_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(\s*(?:<(?P<bracket>[^>]+)>|(?P<plain>[^\s)]+))(?:\s+[^)]*)?\s*\)")
_OBSIDIAN_IMAGE_RE = re.compile(r"!\[\[(?P<embed>[^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_HTML_URL_RE = re.compile(r"(?:src|href)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


class MarkdownPortableError(ValueError):
    """A submitted Markdown/YAML document cannot be imported safely."""


@dataclass(frozen=True)
class ImportErrorDetail:
    path: str
    code: str
    message: str
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {"path": self.path, "code": self.code, "message": self.message}
        if self.line is not None:
            result["line"] = self.line
        return result


@dataclass(frozen=True)
class ImportDraft:
    """A nonpersistent import result, retaining source only for commit recheck."""

    filename: str
    fingerprint: str
    payload: dict[str, Any] | None
    errors: tuple[ImportErrorDetail, ...] = ()
    content: str = field(default="", repr=False)

    @property
    def valid(self) -> bool:
        return not self.errors and self.payload is not None

    @property
    def kind(self) -> str | None:
        if self.payload is None:
            return None
        for collection, kind in (
            ("activities", "question"),
            ("decks", "deck"),
            ("flows", "lesson"),
            ("assessments", "assessment"),
        ):
            if self.payload.get(collection):
                return kind
        return None

    @property
    def source_hash(self) -> str:
        return self.fingerprint

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "fingerprint": self.fingerprint,
            "filename": self.filename,
            "kind": self.kind,
            "draft": deepcopy(self.payload),
            "errors": [error.as_dict() for error in self.errors],
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]


class _StrictSafeLoader(yaml.SafeLoader):
    """PyYAML safe loader that rejects duplicate mapping keys."""

    def construct_mapping(self, node, deep: bool = False):  # type: ignore[no-untyped-def]
        if not isinstance(node, yaml.MappingNode):
            return super().construct_mapping(node, deep=deep)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "mapping keys must be scalar values",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _yaml_mapping(source: str) -> tuple[dict[str, Any] | None, yaml.YAMLError | None]:
    try:
        value = yaml.load(source, Loader=_StrictSafeLoader)
    except yaml.YAMLError as exc:
        return None, exc
    if not isinstance(value, dict):
        return None, yaml.YAMLError("document must be a YAML mapping")
    return value, None


def _fingerprint(filename: str, content: str) -> str:
    return hashlib.sha256(filename.encode("utf-8") + b"\0" + content.encode("utf-8")).hexdigest()


def _error(path: str, code: str, message: str, line: int | None = None) -> ImportErrorDetail:
    return ImportErrorDetail(path=path, code=code, message=message, line=line)


def _yaml_error(error: yaml.YAMLError, path: str) -> ImportErrorDetail:
    mark = getattr(error, "problem_mark", None) or getattr(error, "context_mark", None)
    line = getattr(mark, "line", None)
    problem = getattr(error, "problem", None) or str(error).splitlines()[0]
    return _error(path, "invalid_yaml", f"Invalid YAML: {problem}.", line + 1 if line is not None else None)


def _filename(filename: Any) -> tuple[str | None, ImportErrorDetail | None]:
    if not isinstance(filename, str) or not filename.strip():
        return None, _error("filename", "invalid_filename", "Filename is required.")
    value = filename.strip()
    if "\x00" in value or "\\" in value or "/" in value:
        return None, _error("filename", "unsafe_path", "Filename must be a direct document name.")
    suffix = PurePosixPath(value).suffix.casefold()
    if suffix not in SUPPORTED_SUFFIXES:
        return None, _error("filename", "unsupported_format", "Only .md, .yaml, and .yml imports are supported.")
    return value, None


def _source(content: Any) -> tuple[str | None, ImportErrorDetail | None]:
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError:
            return None, _error("content", "invalid_utf8", "Content must be valid UTF-8.")
    if not isinstance(content, str):
        return None, _error("content", "invalid_content", "Content must be text.")
    if "\x00" in content:
        return None, _error("content", "invalid_content", "Content must not contain NUL characters.")
    if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
        return None, _error("content", "content_too_large", "Content exceeds the 2 MiB import limit.")
    return content, None


def _frontmatter(content: str) -> tuple[dict[str, Any], str, int, list[ImportErrorDetail]]:
    """Call VaultPub's public parser, then apply strict import diagnostics."""
    errors: list[ImportErrorDetail] = []
    if _vaultpub_frontmatter is None:
        errors.append(
            _error(
                "document",
                "vaultpub_unavailable",
                "VaultPub frontmatter parsing is unavailable; install a compatible VaultPub package.",
            )
        )
        return {}, content, 0, errors
    try:
        _vaultpub_frontmatter(content)
    except Exception:
        errors.append(_error("document", "vaultpub_unavailable", "VaultPub frontmatter parsing is unavailable."))
        return {}, content, 0, errors
    if not content.startswith("---") or not content.splitlines()[0].strip() == "---":
        return {}, content, 0, errors
    lines = content.splitlines()
    closing = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if closing is None:
        errors.append(_error("frontmatter", "invalid_yaml", "Frontmatter is missing its closing --- marker.", 1))
        return {}, content, 0, errors
    parsed, yaml_error = _yaml_mapping("\n".join(lines[1:closing]))
    if yaml_error is not None:
        errors.append(_yaml_error(yaml_error, "frontmatter"))
        parsed = {}
    body_start = closing + 1
    return parsed or {}, "\n".join(lines[body_start:]), body_start, errors


def _check_fields(mapping: Mapping[str, Any], *, path: str) -> list[ImportErrorDetail]:
    return [
        _error(f"{path}.{key}", "unknown_field", "This field is not supported for import.")
        for key in mapping
        if key not in _FRONTMATTER_KEYS
    ]


def _kind(mapping: Mapping[str, Any], *, path: str = "frontmatter") -> tuple[str | None, list[ImportErrorDetail]]:
    raw = mapping.get("kind")
    if not isinstance(raw, str) or not raw.strip():
        return None, [_error(f"{path}.kind", "missing_kind", "Document kind is required.")]
    value = raw.strip().casefold()
    if value not in SUPPORTED_KINDS:
        return None, [_error(f"{path}.kind", "unsupported_kind", "Kind must be question, deck, lesson, or assessment.")]
    return value, []


def _title(mapping: Mapping[str, Any], fallback: str, body: str = "") -> tuple[str, list[ImportErrorDetail]]:
    value = mapping.get("title")
    if value is None:
        for line in body.splitlines():
            match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if match:
                value = match.group(1)
                break
    if value is None:
        value = fallback
    if not isinstance(value, str) or not value.strip():
        return "", [_error("title", "invalid_type", "Title must be non-empty text.")]
    value = value.strip()
    if len(value) > 200:
        return "", [_error("title", "too_long", "Title is too long.")]
    return value, []


def _type_key(mapping: Mapping[str, Any], *, path: str) -> tuple[str | None, list[ImportErrorDetail]]:
    raw_key = mapping.get("type_key")
    raw_type = mapping.get("type")
    if raw_key is not None and raw_type is not None:
        key_from_type = str(raw_type).strip()
        if not key_from_type.startswith("liveclassroom."):
            key_from_type = f"liveclassroom.{key_from_type}"
        if raw_key != key_from_type:
            return None, [_error(path, "conflicting_type", "type and type_key must match.")]
    raw = raw_key if raw_key is not None else raw_type or "markdown"
    if not isinstance(raw, str) or not raw.strip():
        return None, [_error(path, "invalid_type", "Question type must be text.")]
    value = raw.strip()
    if "." not in value:
        value = f"liveclassroom.{value}"
    try:
        activity_registry.get(value)
    except KeyError:
        return None, [_error(path, "unknown_activity_type", "Question type is not registered.")]
    return value, []


def _definition(mapping: Mapping[str, Any], body: str, type_key: str) -> tuple[dict[str, Any], list[ImportErrorDetail]]:
    raw = mapping.get("definition", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        return {}, [_error("definition", "invalid_type", "definition must be an object.")]
    result = deepcopy(dict(raw))
    for key in (
        "prompt",
        "question",
        "markdown",
        "options",
        "choices",
        "answer",
        "correct_answer",
        "tolerance",
        "partial_credit",
        "case_sensitive",
        "explanation",
    ):
        if key in mapping and key not in result:
            result[key] = deepcopy(mapping[key])
    if type_key == "liveclassroom.markdown":
        if "markdown" not in result:
            result["markdown"] = body.strip()
    elif "prompt" not in result:
        result["prompt"] = str(mapping.get("question") or body).strip()
    return result, []


def _metadata(mapping: Mapping[str, Any]) -> tuple[dict[str, Any], list[ImportErrorDetail]]:
    value = mapping.get("metadata", {})
    if not isinstance(value, Mapping):
        return {}, [_error("metadata", "invalid_type", "metadata must be an object.")]
    return deepcopy(dict(value)), []


def _activity_row(
    mapping: Mapping[str, Any], body: str, *, key: str, title_fallback: str
) -> tuple[dict[str, Any] | None, list[ImportErrorDetail]]:
    type_key, errors = _type_key(mapping, path="type")
    if errors or type_key is None:
        return None, errors
    title, title_errors = _title(mapping, title_fallback, body)
    metadata, metadata_errors = _metadata(mapping)
    definition, definition_errors = _definition(mapping, body, type_key)
    errors.extend(title_errors)
    errors.extend(metadata_errors)
    errors.extend(definition_errors)
    if errors:
        return None, errors
    return {
        "key": key,
        "type_key": type_key,
        "schema_version": VERSION,
        "title": title,
        "definition": definition,
        "metadata": metadata,
    }, []


def _strict_url(raw: str, *, path: str, line: int | None = None) -> tuple[str | None, ImportErrorDetail | None]:
    value = raw.strip().strip("<>")
    if value.startswith("asset:"):
        alias = value[6:].strip()
        if not alias:
            return None, _error(path, "invalid_resource", "Asset reference is empty.", line)
        return alias, None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value) or value.startswith("//"):
        return None, _error(path, "unsafe_url", "External and scheme URLs are not allowed.", line)
    if value.startswith("/") or "\\" in value:
        return None, _error(path, "unsafe_path", "Absolute and backslash paths are not allowed.", line)
    value = value.split("#", 1)[0].split("?", 1)[0]
    while value.startswith("./"):
        value = value[2:]
    parts = value.split("/")
    if len(parts) != 1 or not value or any(part in {".", ".."} for part in parts):
        return None, _error(path, "unsafe_path", "Resource paths must be direct siblings without traversal.", line)
    return value, None


def _resource_references(markdown: str, *, path: str) -> tuple[list[str], list[ImportErrorDetail]]:
    refs: list[str] = []
    errors: list[ImportErrorDetail] = []
    in_fence = False
    fence_character = ""
    fence_length = 0
    for line_number, line in enumerate(markdown.splitlines(), 1):
        fence = _FENCE_RE.match(line)
        if fence:
            token = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_character = token[0]
                fence_length = len(token)
            elif token[0] == fence_character and len(token) >= fence_length:
                in_fence = False
                fence_character = ""
                fence_length = 0
            continue
        if in_fence:
            continue
        matches = [
            *[(m.group("bracket") or m.group("plain")) for m in _IMAGE_RE.finditer(line)],
            *[(m.group("bracket") or m.group("plain")) for m in _LINK_RE.finditer(line)],
            *[m.group("embed").strip() for m in _OBSIDIAN_IMAGE_RE.finditer(line)],
            *[m.group(1) for m in _HTML_URL_RE.finditer(line)],
        ]
        for raw in matches:
            reference, error = _strict_url(raw, path=path, line=line_number)
            if error is not None:
                errors.append(error)
            elif reference is not None:
                refs.append(reference)
    if in_fence:
        errors.append(_error(path, "invalid_fence", "Code fence is missing its closing separator."))
    return refs, errors


def _asset_rows(value: Any) -> tuple[list[dict[str, Any]], list[ImportErrorDetail]]:
    if value is None:
        return [], []
    if not isinstance(value, list):
        return [], [_error("assets", "invalid_type", "assets must be a list of portable asset objects.")]
    rows = deepcopy(value)
    payload = {"format": FORMAT, "version": VERSION, "assets": rows}
    try:
        normalized = validate_portable(payload).payload["assets"]
    except PortableContentError as exc:
        return [], [_error("assets", "invalid_asset", str(exc))]
    return normalized, []


def _attach_resources(
    payload: dict[str, Any], raw_markdown: Sequence[tuple[str, str]], assets: list[dict[str, Any]]
) -> list[ImportErrorDetail]:
    aliases: dict[str, str] = {}
    for asset in assets:
        key = asset["key"]
        aliases[key] = key
        aliases[asset["filename"]] = key
    used: set[str] = set()
    errors: list[ImportErrorDetail] = []
    for markdown, path in raw_markdown:
        refs, ref_errors = _resource_references(markdown, path=path)
        errors.extend(ref_errors)
        for ref in refs:
            key = aliases.get(ref)
            if key is None:
                errors.append(_error(path, "missing_resource", f"Referenced resource {ref!r} is not supplied."))
            else:
                used.add(key)
    for collection in ("activities", "decks", "assessments", "flows"):
        for row in payload.get(collection, []):
            definition = row.get("definition") if isinstance(row, Mapping) else None
            if isinstance(definition, Mapping):
                key = definition.get("asset_key") or row.get("asset_key")
                if isinstance(key, str):
                    used.add(key)
    for deck in payload.get("decks", []):
        for slide in deck.get("slides", []):
            for key in slide.get("asset_keys", []):
                if isinstance(key, str):
                    used.add(key)
    for asset in assets:
        if asset["key"] not in used:
            errors.append(
                _error(
                    f"assets.{asset['key']}", "unreferenced_resource", "Resource is not referenced by imported content."
                )
            )
    for row in payload.get("decks", []):
        for slide in row.get("slides", []):
            refs, _ = _resource_references(slide["markdown"], path=f"decks.{row['key']}.slides.{slide['position']}")
            slide["asset_keys"] = [aliases[ref] for ref in refs if ref in aliases]
    return errors


def _base() -> dict[str, Any]:
    return {
        "format": FORMAT,
        "version": VERSION,
        "activities": [],
        "decks": [],
        "assessments": [],
        "banks": [],
        "flows": [],
        "assets": [],
    }


def _deck(
    mapping: Mapping[str, Any], body: str, fallback: str
) -> tuple[dict[str, Any] | None, list[ImportErrorDetail]]:
    title, errors = _title(mapping, fallback, body)
    theme = mapping.get("theme")
    slide_options = mapping.get("slide")
    if slide_options is not None and not isinstance(slide_options, Mapping):
        errors.append(_error("slide", "invalid_type", "slide must be an object."))
        slide_options = {}
    if isinstance(slide_options, Mapping):
        errors.extend(_check_fields(slide_options, path="slide"))
        nested_theme = slide_options.get("theme")
        if theme is not None and nested_theme is not None and theme != nested_theme:
            errors.append(_error("theme", "conflicting_value", "theme and slide.theme must match."))
        theme = nested_theme if nested_theme is not None else theme
    if theme is None:
        theme = "default"
    if not isinstance(theme, str) or theme not in {"default", "light", "dark"}:
        errors.append(_error("theme", "invalid_value", "theme must be default, light, or dark."))
        theme = "default"
    split = mapping.get("split")
    if isinstance(slide_options, Mapping) and slide_options.get("split") is not None:
        nested_split = slide_options["split"]
        if split is not None and split != nested_split:
            errors.append(_error("split", "conflicting_value", "split and slide.split must match."))
        split = nested_split
    if split is None:
        split = "auto"
    if not isinstance(split, str) or split not in SLIDE_SPLIT_POLICIES:
        errors.append(_error("split", "invalid_value", "split must be a supported VaultPub policy."))
        split = "auto"
    slides: list[dict[str, Any]] = []
    raw_slides = mapping.get("slides")
    if isinstance(raw_slides, list):
        for position, row in enumerate(raw_slides, 1):
            if not isinstance(row, Mapping):
                errors.append(_error(f"slides.{position}", "invalid_type", "Slide must be an object."))
                continue
            markdown = row.get("markdown", "")
            notes = row.get("notes", "")
            if not isinstance(markdown, str) or not isinstance(notes, str):
                errors.append(_error(f"slides.{position}", "invalid_type", "Slide markdown and notes must be text."))
                continue
            slides.append(
                {
                    "key": str(row.get("key", f"slide-{position}")),
                    "position": position,
                    "markdown": markdown.strip(),
                    "notes": notes.strip(),
                    "asset_keys": list(row.get("asset_keys", [])),
                }
            )
    else:
        if _vaultpub_segment_slides is None or _vaultpub_slide_options is None:
            errors.append(
                _error(
                    "document",
                    "vaultpub_unavailable",
                    "VaultPub slide segmentation is unavailable; install a compatible VaultPub package.",
                )
            )
        else:
            try:
                # Calling slide_options also records that VaultPub owns the
                # allowlisted presentation configuration.
                _vaultpub_slide_options(dict(mapping))
                segmented = _vaultpub_segment_slides(
                    (f"---\n{yaml.safe_dump(dict(mapping), sort_keys=False)}---\n\n" if mapping else "") + body,
                    split,
                )
                for position, fragment in enumerate(segmented.fragments, 1):
                    markdown = fragment.strip()
                    slides.append(
                        {
                            "key": f"slide-{position}",
                            "position": position,
                            "markdown": markdown,
                            "notes": "",
                            "asset_keys": [],
                        }
                    )
            except Exception as exc:
                errors.append(
                    _error(
                        "slides", "invalid_markdown", f"VaultPub could not segment slides: {exc.__class__.__name__}."
                    )
                )
    if not slides:
        errors.append(_error("slides", "empty", "Deck must contain at least one slide."))
    if len(slides) > MAX_DOCUMENT_ITEMS:
        errors.append(_error("slides", "too_many", f"Deck may contain at most {MAX_DOCUMENT_ITEMS} slides."))
    if errors:
        return None, errors
    return {"key": str(mapping.get("key", "deck-1")), "title": title, "theme": theme, "slides": slides}, []


def _question(
    mapping: Mapping[str, Any], body: str, fallback: str
) -> tuple[dict[str, Any] | None, list[ImportErrorDetail]]:
    row, errors = _activity_row(mapping, body, key=str(mapping.get("key", "activity-1")), title_fallback=fallback)
    return row, errors


def _lesson(
    mapping: Mapping[str, Any], body: str, fallback: str
) -> tuple[dict[str, Any] | None, list[ImportErrorDetail]]:
    # Existing lesson syntax includes :::quiz blocks; delegate its parsing so
    # this adapter does not become a second lesson Markdown engine.
    from .markdown import ImportError as LegacyImportError
    from .markdown import parse_markdown

    try:
        parsed = parse_markdown(
            "---\n" + yaml.safe_dump(dict(mapping), sort_keys=False) + "---\n\n" + body,
            fallback_slug=fallback,
        )
    except LegacyImportError as exc:
        return None, [_error("document", "invalid_lesson", str(exc))]
    activities: list[dict[str, Any]] = []
    steps: list[str] = []
    errors: list[ImportErrorDetail] = []
    for position, item in enumerate(parsed.items, 1):
        row = {
            "key": f"activity-{position}",
            "type_key": item.type_key,
            "schema_version": VERSION,
            "title": item.title or "Markdown",
            "definition": deepcopy(item.content),
            "metadata": deepcopy(item.metadata),
        }
        try:
            validate_portable({**_base(), "activities": [row]})
        except PortableContentError as exc:
            errors.append(_error(f"items.{position}", "invalid_definition", str(exc)))
        activities.append(row)
        steps.append(row["key"])
    if errors:
        return None, errors
    return {
        "key": f"lesson-{parsed.slug}",
        "title": parsed.title,
        "description": parsed.description,
        "steps": steps,
    }, activities


def _assessment(
    mapping: Mapping[str, Any], body: str, fallback: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[ImportErrorDetail]]:
    title, errors = _title(mapping, fallback, body)
    instructions = mapping.get("instructions", body.strip())
    if not isinstance(instructions, str):
        errors.append(_error("instructions", "invalid_type", "instructions must be text."))
        instructions = ""
    settings = mapping.get("settings", {})
    if not isinstance(settings, Mapping):
        errors.append(_error("settings", "invalid_type", "settings must be an object."))
        settings = {}
    activities = []
    activity_by_key: set[str] = set()
    for position, raw in enumerate(mapping.get("activities", []), 1):
        if not isinstance(raw, Mapping):
            errors.append(_error(f"activities.{position}", "invalid_type", "Activity must be an object."))
            continue
        key = str(raw.get("key", f"activity-{position}"))
        activity, activity_errors = _activity_row(
            raw, str(raw.get("prompt", "")), key=key, title_fallback=f"Question {position}"
        )
        if activity_errors:
            errors.extend(_error(f"activities.{position}.{e.path}", e.code, e.message, e.line) for e in activity_errors)
        elif activity is not None:
            activities.append(activity)
            activity_by_key.add(key)
    items: list[dict[str, Any]] = []
    for position, raw in enumerate(mapping.get("items", []), 1):
        if not isinstance(raw, Mapping):
            errors.append(_error(f"items.{position}", "invalid_type", "Assessment item must be an object."))
            continue
        item_key = str(raw.get("key", f"item-{position}"))
        activity_key = raw.get("activity_key")
        if activity_key is None and (
            raw.get("definition") is not None or raw.get("type") is not None or raw.get("type_key") is not None
        ):
            activity_key = str(raw.get("activity_key", f"activity-item-{position}"))
            activity, activity_errors = _activity_row(
                raw, str(raw.get("prompt", "")), key=activity_key, title_fallback=f"Question {position}"
            )
            errors.extend(_error(f"items.{position}.{e.path}", e.code, e.message, e.line) for e in activity_errors)
            if activity is not None:
                activities.append(activity)
                activity_by_key.add(activity_key)
        if not isinstance(activity_key, str) or not activity_key.strip():
            errors.append(
                _error(f"items.{position}.activity_key", "missing_reference", "Assessment item needs an activity_key.")
            )
            continue
        points = raw.get("points", "1")
        items.append({"key": item_key, "activity_key": activity_key.strip(), "points": points})
    result = {
        "key": str(mapping.get("key", "assessment-1")),
        "title": title,
        "instructions": instructions,
        "items": items,
        "settings": deepcopy(dict(settings)),
    }
    if "sections" in mapping:
        result["sections"] = deepcopy(mapping["sections"])
    return result, activities, errors


def _parse_document(filename: str, content: str) -> tuple[dict[str, Any] | None, list[ImportErrorDetail]]:
    suffix = PurePosixPath(filename).suffix.casefold()
    if suffix == ".md":
        frontmatter, body, _body_start, errors = _frontmatter(content)
        errors.extend(_check_fields(frontmatter, path="frontmatter"))
        kind, kind_errors = _kind(frontmatter)
        errors.extend(kind_errors)
        if errors:
            return None, errors
        assets, asset_errors = _asset_rows(frontmatter.get("assets"))
        errors.extend(asset_errors)
        if kind == "deck":
            deck, kind_errors = _deck(frontmatter, body, PurePosixPath(filename).stem)
            errors.extend(kind_errors)
            payload = _base()
            if deck is not None:
                payload["decks"] = [deck]
        elif kind == "question":
            row, kind_errors = _question(frontmatter, body, PurePosixPath(filename).stem)
            errors.extend(kind_errors)
            payload = _base()
            if row is not None:
                payload["activities"] = [row]
        elif kind == "lesson":
            lesson, lesson_activities = _lesson(frontmatter, body, PurePosixPath(filename).stem)
            if lesson is None:
                errors.extend(lesson_activities)
                payload = _base()
            else:
                payload = _base()
                payload["flows"] = [lesson]
                payload["activities"] = lesson_activities
        else:
            assessment, assessment_activities, kind_errors = _assessment(
                frontmatter, body, PurePosixPath(filename).stem
            )
            errors.extend(kind_errors)
            payload = _base()
            if assessment is not None:
                payload["assessments"] = [assessment]
                payload["activities"] = assessment_activities
        payload["assets"] = assets
        markdown_rows = []
        for deck in payload.get("decks", []):
            markdown_rows.extend(
                (slide.get("markdown", ""), f"decks.{deck['key']}.slides.{slide['position']}")
                for slide in deck["slides"]
            )
        for activity in payload.get("activities", []):
            definition = activity.get("definition", {})
            if isinstance(definition, Mapping):
                for key in ("markdown", "prompt", "stem_markdown"):
                    if isinstance(definition.get(key), str):
                        markdown_rows.append((definition[key], f"activities.{activity['key']}.definition.{key}"))
        errors.extend(_attach_resources(payload, markdown_rows, assets))
    else:
        mapping, yaml_error = _yaml_mapping(content)
        if yaml_error is not None:
            return None, [_yaml_error(yaml_error, "document")]
        assert mapping is not None
        errors = _check_fields(mapping, path="document")
        kind, kind_errors = _kind(mapping, path="document")
        errors.extend(kind_errors)
        assets, asset_errors = _asset_rows(mapping.get("assets"))
        errors.extend(asset_errors)
        if errors:
            return None, errors
        payload = _base()
        if kind == "question":
            row, kind_errors = _question(mapping, "", PurePosixPath(filename).stem)
            errors.extend(kind_errors)
            if row is not None:
                payload["activities"] = [row]
        elif kind == "deck":
            deck, kind_errors = _deck(mapping, "", PurePosixPath(filename).stem)
            errors.extend(kind_errors)
            if deck is not None:
                payload["decks"] = [deck]
        elif kind == "lesson":
            steps = mapping.get("steps", [])
            if not isinstance(steps, list):
                errors.append(_error("steps", "invalid_type", "steps must be a list."))
            payload["flows"] = [
                {
                    "key": str(mapping.get("key", "lesson-1")),
                    "title": str(mapping.get("title", PurePosixPath(filename).stem)),
                    "description": str(mapping.get("description", "")),
                    "steps": deepcopy(steps),
                }
            ]
        else:
            assessment, assessment_activities, kind_errors = _assessment(mapping, "", PurePosixPath(filename).stem)
            errors.extend(kind_errors)
            if assessment is not None:
                payload["assessments"] = [assessment]
                payload["activities"] = assessment_activities
        payload["assets"] = assets
        markdown_rows = []
        for deck in payload.get("decks", []):
            markdown_rows.extend(
                (slide.get("markdown", ""), f"decks.{deck['key']}.slides.{slide['position']}")
                for slide in deck["slides"]
            )
        errors.extend(_attach_resources(payload, markdown_rows, assets))
    if errors:
        return None, errors
    try:
        return validate_portable(payload).to_dict(), []
    except PortableContentError as exc:
        return None, [_error("document", "invalid_portable", str(exc))]


def parse_markdown_import(*, actor: Any, filename: Any, content: Any) -> ImportDraft:
    """Parse one teacher document without writing to the database."""
    # Importing is an authoring operation; actor policy is checked here and
    # again by the portable importer at commit time.
    from liveclassroom.services.permissions import can_teach

    normalized_filename, filename_error = _filename(filename)
    normalized_content, content_error = _source(content)
    if normalized_filename is None or normalized_content is None:
        return ImportDraft(
            filename=str(filename or ""),
            fingerprint=_fingerprint(str(filename or ""), str(content or "")),
            payload=None,
            errors=tuple(error for error in (filename_error, content_error) if error is not None),
            content=normalized_content or "",
        )
    if not can_teach(actor):
        return ImportDraft(
            filename=normalized_filename,
            fingerprint=_fingerprint(normalized_filename, normalized_content),
            payload=None,
            errors=(
                _error("document", "permission_denied", "An authenticated teacher is required to import content."),
            ),
            content=normalized_content,
        )
    payload, errors = _parse_document(normalized_filename, normalized_content)
    return ImportDraft(
        filename=normalized_filename,
        fingerprint=_fingerprint(normalized_filename, normalized_content),
        payload=payload,
        errors=tuple(errors),
        content=normalized_content,
    )


__all__ = ["ImportDraft", "ImportErrorDetail", "MarkdownPortableError", "parse_markdown_import"]
