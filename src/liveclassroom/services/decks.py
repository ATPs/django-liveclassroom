"""Atomic authoring commands for native slide-list decks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

from django.db import transaction

from liveclassroom.models import ClassroomAsset, Course, Deck, DeckSlide, DeckSlideAsset

from .classroom import ClassroomError
from .permissions import can_author_course, can_teach

MAX_SLIDES = 500
MAX_MARKDOWN_LENGTH = 200_000
MAX_NOTES_LENGTH = 20_000
THEME_MAX_LENGTH = 80


def _text(value, field, maximum, *, required=False):
    if not isinstance(value, str):
        raise ClassroomError(f"{field} must be text.")
    value = value.strip()
    if required and not value:
        raise ClassroomError(f"{field} is required.")
    if len(value) > maximum:
        raise ClassroomError(f"{field} is too long.")
    return value


def _owner(actor, deck):
    if not can_teach(actor) or (deck.owner_id != actor.pk and not getattr(actor, "is_superuser", False)):
        raise ClassroomError("You do not have permission to edit this deck.")


def _course(actor, value):
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


def _asset_ids(actor, values):
    if not isinstance(values, list) or len(values) != len(set(map(str, values))):
        raise ClassroomError("asset_ids must be a unique list.")
    assets = []
    for raw in values:
        try:
            asset = ClassroomAsset.objects.get(public_id=UUID(str(raw)))
        except (ValueError, ClassroomAsset.DoesNotExist) as exc:
            raise ClassroomError("Referenced asset not found.") from exc
        if asset.owner_id != actor.pk and not getattr(actor, "is_superuser", False):
            raise ClassroomError("You do not have permission to use this asset.")
        assets.append(asset)
    return assets


def _slides(actor, values):
    if not isinstance(values, list) or len(values) > MAX_SLIDES:
        raise ClassroomError(f"slides must contain at most {MAX_SLIDES} entries.")
    result = []
    keys = set()
    for position, value in enumerate(values, 1):
        if not isinstance(value, Mapping) or set(value) - {"key", "markdown", "notes", "asset_ids"}:
            raise ClassroomError("Invalid slide fields.")
        raw_key = value.get("key")
        if raw_key is None:
            key = uuid4()
        else:
            try:
                key = UUID(str(raw_key))
            except ValueError as exc:
                raise ClassroomError("Slide key must be a UUID.") from exc
        if key in keys:
            raise ClassroomError("Each slide key must be unique.")
        keys.add(key)
        result.append(
            {
                "key": key,
                "position": position,
                "markdown": _text(value.get("markdown", ""), "slide markdown", MAX_MARKDOWN_LENGTH),
                "notes": _text(value.get("notes", ""), "slide notes", MAX_NOTES_LENGTH),
                "assets": _asset_ids(actor, value.get("asset_ids", [])),
            }
        )
    return result


def _expected(deck, expected_version):
    if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version != deck.version:
        raise ClassroomError("The deck changed; refresh before saving.")


def _write_slides(deck, data):
    deck.slides.all().delete()
    for row in data:
        slide = DeckSlide.objects.create(
            deck=deck,
            key=row["key"],
            position=row["position"],
            markdown=row["markdown"],
            notes=row["notes"],
        )
        DeckSlideAsset.objects.bulk_create([DeckSlideAsset(slide=slide, asset=asset) for asset in row["assets"]])


@transaction.atomic
def create_deck(*, actor, data: Mapping) -> Deck:
    if not can_teach(actor) or not isinstance(data, Mapping) or set(data) - {"title", "course_id", "theme", "slides"}:
        raise ClassroomError("Invalid deck fields.")
    deck = Deck.objects.create(
        owner=actor,
        title=_text(data.get("title"), "title", 200, required=True),
        course=_course(actor, data.get("course_id")),
        theme=_text(data.get("theme", "default"), "theme", THEME_MAX_LENGTH, required=True),
    )
    _write_slides(deck, _slides(actor, data.get("slides", [])))
    return deck


@transaction.atomic
def update_deck(*, actor, deck: Deck, expected_version: int, data: Mapping) -> Deck:
    _owner(actor, deck)
    if not isinstance(data, Mapping) or not data or set(data) - {"title", "course_id", "theme"}:
        raise ClassroomError("Invalid deck fields.")
    deck = Deck.objects.select_for_update().get(pk=deck.pk)
    _expected(deck, expected_version)
    if "title" in data:
        deck.title = _text(data["title"], "title", 200, required=True)
    if "course_id" in data:
        deck.course = _course(actor, data["course_id"])
    if "theme" in data:
        deck.theme = _text(data["theme"], "theme", THEME_MAX_LENGTH, required=True)
    deck.version += 1
    deck.save()
    return deck


@transaction.atomic
def replace_deck_slides(*, actor, deck: Deck, expected_version: int, slides: Sequence) -> Deck:
    _owner(actor, deck)
    deck = Deck.objects.select_for_update().get(pk=deck.pk)
    _expected(deck, expected_version)
    _write_slides(deck, _slides(actor, slides))
    deck.version += 1
    deck.save()
    return deck


@transaction.atomic
def copy_deck(*, actor, deck: Deck, title: str | None = None) -> Deck:
    _owner(actor, deck)
    copied = Deck.objects.create(
        owner=actor,
        course=deck.course if deck.course_id and can_author_course(actor, deck.course) else None,
        title=_text(title if title is not None else f"{deck.title} (Copy)", "title", 200, required=True),
        theme=deck.theme,
    )
    rows = []
    for slide in deck.slides.prefetch_related("assets").all():
        rows.append(
            {
                "key": uuid4(),
                "position": slide.position,
                "markdown": slide.markdown,
                "notes": slide.notes,
                "assets": list(slide.assets.all()),
            }
        )
    _write_slides(copied, rows)
    return copied


def deck_payload(deck: Deck, *, include_notes=True):
    slides = []
    for slide in deck.slides.prefetch_related("assets").all():
        row = {
            "key": str(slide.key),
            "position": slide.position,
            "markdown": slide.markdown,
            "asset_ids": [str(asset.public_id) for asset in slide.assets.all()],
        }
        if include_notes:
            row["notes"] = slide.notes
        slides.append(row)
    return {
        "id": deck.id,
        "title": deck.title,
        "course_id": deck.course_id,
        "theme": deck.theme,
        "version": deck.version,
        "slides": slides,
    }
