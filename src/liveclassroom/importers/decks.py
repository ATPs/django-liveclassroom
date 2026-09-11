"""Validate Markdown deck input with VaultPub's public parser.

The importer intentionally delegates frontmatter parsing and slide boundary
discovery to VaultPub.  A portable teaching deck consists of one Markdown
document.  VaultPub's ``auto`` policy treats Markdown horizontal rules as
explicit boundaries while ignoring rules inside fenced code blocks and uses
headings when no explicit boundaries are present.

Private notes use a small, deliberately explicit convention which VaultPub
leaves as ordinary HTML comments::

    <!-- liveclassroom:notes -->
    Say this while presenting.
    <!-- /liveclassroom:notes -->

The markers are accepted only outside fenced code blocks.  The block is
removed from public slide Markdown and returned in the slide's ``notes``
field.  This keeps notes available for an intentional teacher export while
preventing them from entering the public VaultPub document.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml

from liveclassroom.models import ClassroomAsset
from liveclassroom.services.classroom import ClassroomError
from liveclassroom.services.permissions import can_teach

try:  # A normal package installation does not require the optional extra.
    from vaultpub.core.frontmatter import parse_frontmatter
    from vaultpub.core.render.slides import (
        READING_THEMES,
        SLIDE_SPLIT_POLICIES,
        segment_slides,
    )
except ImportError:  # pragma: no cover - exercised by optional dependency checks
    parse_frontmatter = None
    segment_slides = None
    READING_THEMES = frozenset()
    SLIDE_SPLIT_POLICIES = frozenset()


class DeckImportError(ValueError):
    """A deck cannot be safely normalized or imported."""


MAX_SOURCE_BYTES = 2_000_000
MAX_SLIDES = 500
MAX_TITLE_LENGTH = 200
MAX_THEME_LENGTH = 80
MAX_MARKDOWN_LENGTH = 200_000
MAX_NOTES_LENGTH = 20_000
DEFAULT_TITLE = "Imported deck"
DEFAULT_THEME = "default"
ALLOWED_THEMES = frozenset({DEFAULT_THEME, *READING_THEMES})

_OPEN_MARKERS = {
    "<!-- liveclassroom:notes -->",
    "<!-- speaker-notes -->",
}
_CLOSE_MARKERS = {
    "<!-- /liveclassroom:notes -->",
    "<!-- /speaker-notes -->",
}
_MARKDOWN_IMAGE = re.compile(
    r"!\[[^\]]*\]\(\s*(?:<(?P<bracket>[^>]+)>|(?P<plain>[^\s)]+))(?:\s+[^)]*)?\s*\)",
)
_OBSIDIAN_IMAGE = re.compile(r"!\[\[(?P<embed>[^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")


def _vaultpub_available() -> None:
    if parse_frontmatter is None or segment_slides is None:
        raise DeckImportError("VaultPub deck parsing is unavailable; install the optional vaultpub extra.")


def _text(value: Any, field: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise DeckImportError(f"{field} must be text.")
    value = value.strip()
    if required and not value:
        raise DeckImportError(f"{field} is required.")
    if len(value) > maximum:
        raise DeckImportError(f"{field} is too long.")
    return value


def _parse_frontmatter(source: str) -> tuple[dict[str, Any], str]:
    """Return VaultPub's parsed properties and body, with strict shape checks."""
    _vaultpub_available()
    # VaultPub deliberately treats malformed properties as absent for normal
    # note viewing.  Imports need an actionable error instead, so validate the
    # same opening/closing block before using VaultPub's parsed body.
    if source.startswith("---"):
        lines = source.splitlines()
        if lines and lines[0].strip() == "---":
            closing = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
            if closing is None:
                raise DeckImportError("Deck frontmatter is missing its closing --- marker.")
            try:
                strict = yaml.safe_load("\n".join(lines[1:closing])) or {}
            except yaml.YAMLError as exc:
                raise DeckImportError(f"Invalid deck frontmatter: {exc}") from exc
            if not isinstance(strict, dict):
                raise DeckImportError("Deck frontmatter must be a YAML mapping.")
    frontmatter, body, _ = parse_frontmatter(source)
    if not isinstance(frontmatter, dict):
        raise DeckImportError("Deck frontmatter must be a YAML mapping.")
    return frontmatter, body


def _theme(frontmatter: Mapping[str, Any]) -> str:
    raw_theme = frontmatter.get("theme")
    slide_options = frontmatter.get("slide")
    if slide_options is not None:
        if not isinstance(slide_options, Mapping):
            raise DeckImportError("slide frontmatter must be a mapping.")
        nested_theme = slide_options.get("theme")
        if raw_theme is not None and nested_theme is not None and raw_theme != nested_theme:
            raise DeckImportError("theme and slide.theme must match.")
        raw_theme = nested_theme if nested_theme is not None else raw_theme
    if raw_theme is None:
        return DEFAULT_THEME
    value = _text(raw_theme, "theme", MAX_THEME_LENGTH, required=True)
    # The native authoring service owns the persisted deck allowlist.  Read it
    # lazily so importing this optional parser never creates a module cycle.
    try:
        from liveclassroom.services.decks import DECK_THEME_KEYS

        allowed = frozenset(DECK_THEME_KEYS)
    except ImportError:  # pragma: no cover - only relevant to a partial install
        allowed = ALLOWED_THEMES
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise DeckImportError(f"Unsupported theme {value!r}; choose one of {choices}.")
    return value


def _split_policy(frontmatter: Mapping[str, Any]) -> str:
    raw = frontmatter.get("split")
    slide_options = frontmatter.get("slide")
    if isinstance(slide_options, Mapping) and slide_options.get("split") is not None:
        if raw is not None and raw != slide_options["split"]:
            raise DeckImportError("split and slide.split must match.")
        raw = slide_options["split"]
    if raw is None:
        return "auto"
    if not isinstance(raw, str) or raw not in SLIDE_SPLIT_POLICIES:
        raise DeckImportError("split must be a supported VaultPub slide split policy.")
    return raw


def _outside_fence_marker(line: str, marker: set[str]) -> bool:
    return line.strip() in marker


def _extract_notes(fragment: str) -> tuple[str, str, str | None]:
    """Remove one notes block outside fences and return public, notes, error."""
    lines = fragment.splitlines(keepends=True)
    in_fence = False
    fence = ""
    begin: int | None = None
    end: int | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        fence_match = re.match(r"(`{3,}|~{3,})", stripped)
        if fence_match:
            token = fence_match.group(1)
            if not in_fence:
                in_fence, fence = True, token[0]
            elif token[0] == fence:
                in_fence, fence = False, ""
            continue
        if in_fence:
            continue
        if begin is None and _outside_fence_marker(line, _OPEN_MARKERS):
            begin = index
            continue
        if begin is not None and _outside_fence_marker(line, _CLOSE_MARKERS):
            end = index
            break
    if begin is None:
        return fragment.strip(), "", None
    if end is None:
        return fragment.strip(), "", "Private notes marker is missing its closing marker."
    public = "".join(lines[:begin] + lines[end + 1 :]).strip()
    notes = "".join(lines[begin + 1 : end]).strip()
    # The exporter escapes only delimiter-looking note lines.  Reverse that
    # transport escape after the block has been located, leaving ordinary
    # backslashes untouched.
    notes = "\n".join(
        line[1:] if line.startswith("\\") and line[1:].strip() in _OPEN_MARKERS | _CLOSE_MARKERS else line
        for line in notes.splitlines()
    )
    if len(notes) > MAX_NOTES_LENGTH:
        return public, notes, "Private presenter notes are too long."
    return public, notes, None


def _asset_catalog(actor: Any, assets: Any) -> dict[str, ClassroomAsset]:
    """Normalize approved asset objects into safe reference aliases."""
    if assets is None:
        return {}
    values: list[Any]
    if isinstance(assets, Mapping):
        values = list(assets.items())
    elif isinstance(assets, Sequence) and not isinstance(assets, (str, bytes, bytearray)):
        values = list(assets)
    else:
        raise DeckImportError("assets must be a mapping or list of approved assets.")

    result: dict[str, ClassroomAsset] = {}
    for value in values:
        explicit_alias: Any = None
        candidate = value
        if isinstance(assets, Mapping):
            explicit_alias, candidate = value
        if isinstance(candidate, ClassroomAsset):
            asset = candidate
            aliases = [str(asset.public_id), asset.original_name]
        elif isinstance(candidate, Mapping):
            raw_asset = candidate.get("asset")
            asset = raw_asset if isinstance(raw_asset, ClassroomAsset) else None
            if asset is None:
                raw_id = candidate.get("id") or candidate.get("public_id")
                try:
                    asset = ClassroomAsset.objects.get(public_id=UUID(str(raw_id)))
                except (ValueError, TypeError, ClassroomAsset.DoesNotExist) as exc:
                    raise DeckImportError("Each asset reference must identify an approved asset.") from exc
            aliases = [str(asset.public_id), asset.original_name]
            for key in (candidate.get("name"), candidate.get("path"), candidate.get("reference")):
                if isinstance(key, str) and key.strip():
                    aliases.append(key.strip())
        else:
            try:
                asset = ClassroomAsset.objects.get(public_id=UUID(str(candidate)))
            except (ValueError, TypeError, ClassroomAsset.DoesNotExist) as exc:
                raise DeckImportError("Each asset reference must identify an approved asset.") from exc
            aliases = [str(asset.public_id), asset.original_name]
        if not can_teach(actor) or (asset.owner_id != actor.pk and not getattr(actor, "is_superuser", False)):
            raise DeckImportError("You do not have permission to use one of the referenced assets.")
        if explicit_alias is not None:
            aliases.append(str(explicit_alias))
        for alias in aliases:
            if alias and alias not in result:
                result[alias] = asset
    return result


def _reference_alias(raw: str) -> str:
    value = raw.strip().strip("<>")
    if value.startswith("asset:"):
        value = value[6:]
    if value.startswith("/"):
        # Same-origin API identifiers are accepted, but never fetched here.
        pieces = value.rstrip("/").split("/")
        uuid_part = next((part for part in reversed(pieces) if _UUID.fullmatch(part)), None)
        value = uuid_part or (pieces[-1] if pieces else "")
    if "?" in value or "#" in value:
        value = value.split("?", 1)[0].split("#", 1)[0]
    if "://" in value or value.startswith(("data:", "javascript:")):
        raise DeckImportError("External image URLs are not allowed in imported decks.")
    if not value or "\\" in value or any(part in {".", ".."} for part in value.split("/")):
        raise DeckImportError("Image asset references must be approved identifiers or filenames.")
    return value


def _references(markdown: str) -> list[str]:
    return [
        match.group("bracket") or match.group("plain")
        for match in _MARKDOWN_IMAGE.finditer(markdown)
    ] + [match.group("embed").strip() for match in _OBSIDIAN_IMAGE.finditer(markdown)]


def _slide_assets(actor: Any, markdown: str, catalog: Mapping[str, ClassroomAsset]) -> tuple[list[str], list[str]]:
    ids: list[str] = []
    errors: list[str] = []
    for raw in _references(markdown):
        try:
            alias = _reference_alias(raw)
        except DeckImportError as exc:
            errors.append(str(exc))
            continue
        asset = catalog.get(alias)
        if asset is None and _UUID.fullmatch(alias):
            asset = catalog.get(str(UUID(alias)))
        if asset is None:
            errors.append(f"Referenced asset {raw!r} is not in the approved asset list.")
            continue
        public_id = str(asset.public_id)
        if public_id not in ids:
            ids.append(public_id)
    return ids, errors


def _title(frontmatter: Mapping[str, Any], fragments: Sequence[str]) -> str:
    value = frontmatter.get("title")
    if value is not None:
        return _text(value, "title", MAX_TITLE_LENGTH, required=True)
    for fragment in fragments:
        for line in fragment.splitlines():
            match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if match:
                return _text(match.group(1), "title", MAX_TITLE_LENGTH, required=True)
    return DEFAULT_TITLE


def preview_deck_import(actor: Any, text: str, assets: Any = None) -> dict[str, Any]:
    """Normalize a Markdown deck without creating rows or files.

    The result is JSON-ready and has the shape ``{"draft": ..., "errors":
    [...], "valid": bool}``.  Errors use one-based ``slide`` numbers; a
    document-wide error uses ``slide: None``.
    """
    if not can_teach(actor):
        raise ClassroomError("An authenticated teacher is required to import a deck.")
    if not isinstance(text, str):
        raise DeckImportError("Deck Markdown must be text.")
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise DeckImportError("Deck Markdown is too large.")
    catalog = _asset_catalog(actor, assets)
    errors: list[dict[str, Any]] = []
    try:
        frontmatter, _body = _parse_frontmatter(text)
        theme = _theme(frontmatter)
        split = _split_policy(frontmatter)
        source_title = None
        _vaultpub_available()
        segmented = segment_slides(text, split)
        raw_fragments = list(segmented.fragments)
        if len(raw_fragments) > MAX_SLIDES:
            raise DeckImportError(f"A deck may contain at most {MAX_SLIDES} slides.")
        source_title = _title(frontmatter, raw_fragments)
    except (DeckImportError, KeyError, TypeError, ValueError) as exc:
        return {
            "draft": {"title": "", "theme": DEFAULT_THEME, "slides": []},
            "errors": [{"slide": None, "message": str(exc)}],
            "valid": False,
        }

    slides: list[dict[str, Any]] = []
    for position, fragment in enumerate(raw_fragments, 1):
        markdown, notes, note_error = _extract_notes(fragment)
        slide_errors: list[str] = []
        if note_error:
            slide_errors.append(note_error)
        if len(markdown) > MAX_MARKDOWN_LENGTH:
            slide_errors.append("Slide Markdown is too long.")
        if not markdown:
            slide_errors.append("Slide Markdown cannot be empty.")
        asset_ids, asset_errors = _slide_assets(actor, markdown, catalog)
        slide_errors.extend(asset_errors)
        for message in slide_errors:
            errors.append({"slide": position, "message": message})
        key = str(uuid5(NAMESPACE_URL, f"liveclassroom-deck:{position}:{markdown}"))
        slides.append(
            {
                "key": key,
                "position": position,
                "markdown": markdown,
                "notes": notes,
                "asset_ids": asset_ids,
            }
        )
    if not slides:
        errors.append({"slide": None, "message": "The deck contains no importable slides."})
    draft = {"title": source_title or "", "theme": theme, "slides": slides}
    return {"draft": draft, "errors": errors, "valid": not errors}


def _validated_draft(actor: Any, value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping) and "draft" in value:
        if value.get("errors"):
            raise DeckImportError("The deck preview contains validation errors.")
        value = value["draft"]
    if not isinstance(value, Mapping):
        raise DeckImportError("A validated deck draft must be an object.")
    if set(value) - {"title", "theme", "slides"}:
        raise DeckImportError("Unsupported deck draft fields.")
    title = _text(value.get("title"), "title", MAX_TITLE_LENGTH, required=True)
    theme = _theme(value)
    raw_slides = value.get("slides")
    if not isinstance(raw_slides, list) or not raw_slides or len(raw_slides) > MAX_SLIDES:
        raise DeckImportError("A deck must contain between one and 500 slides.")
    slides: list[dict[str, Any]] = []
    keys: set[UUID] = set()
    for position, row in enumerate(raw_slides, 1):
        if not isinstance(row, Mapping) or set(row) - {"key", "position", "markdown", "notes", "asset_ids"}:
            raise DeckImportError(f"Invalid fields in slide {position}.")
        try:
            key = UUID(str(row.get("key")))
        except (ValueError, TypeError, AttributeError) as exc:
            raise DeckImportError(f"Slide {position} key must be a UUID.") from exc
        if key in keys:
            raise DeckImportError("Each slide key must be unique.")
        keys.add(key)
        markdown = _text(row.get("markdown"), f"slide {position} markdown", MAX_MARKDOWN_LENGTH)
        notes = _text(row.get("notes", ""), f"slide {position} notes", MAX_NOTES_LENGTH)
        raw_assets = row.get("asset_ids", [])
        if not isinstance(raw_assets, list) or len(raw_assets) != len(set(map(str, raw_assets))):
            raise DeckImportError(f"Slide {position} asset_ids must be a unique list.")
        asset_ids: list[str] = []
        for raw_asset in raw_assets:
            try:
                asset_id = str(UUID(str(raw_asset)))
            except (ValueError, TypeError, AttributeError) as exc:
                raise DeckImportError(f"Slide {position} references an invalid asset.") from exc
            asset_ids.append(asset_id)
        slides.append(
            {
                "key": str(key),
                "position": position,
                "markdown": markdown,
                "notes": notes,
                "asset_ids": asset_ids,
            }
        )
    return {"title": title, "theme": theme, "slides": slides}


def import_deck(actor: Any, validated_draft: Mapping[str, Any]):
    """Atomically create an independent native deck from a validated draft."""
    if not can_teach(actor):
        raise ClassroomError("An authenticated teacher is required to import a deck.")
    draft = _validated_draft(actor, deepcopy(validated_draft))
    from liveclassroom.services.decks import create_deck

    # ``position`` is part of the portable preview contract, while the
    # authoring service derives it from list order and intentionally rejects a
    # caller supplied position.
    service_data = {
        **draft,
        "slides": [
            {key: slide[key] for key in ("key", "markdown", "notes", "asset_ids")}
            for slide in draft["slides"]
        ],
    }
    return create_deck(actor=actor, data=service_data)
