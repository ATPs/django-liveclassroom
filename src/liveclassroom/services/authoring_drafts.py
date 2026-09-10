"""Validation and acceptance for private AI authored teaching drafts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from liveclassroom.models import (
    ActivityDefinition,
    ActivityDefinitionRevision,
    AssessmentDefinition,
    AuthoringAttachment,
    AuthoringDraft,
    Deck,
)
from liveclassroom.registry import activity_registry

from .assessments import _item_rows, _settings
from .classroom import ClassroomError
from .decks import _slides, deck_theme
from .definitions import create_activity_definition, revise_activity_definition
from .permissions import can_teach
from .portable_content import FORMAT, VERSION, PortableContentError, validate_portable


class AuthoringDraftError(ClassroomError):
    """A safe, user-facing draft validation or state error."""


ARTIFACT_TYPES = frozenset(AuthoringDraft.ArtifactType.values)
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "password",
        "provider_reasoning",
        "raw_retry_diagnostics",
        "reasoning",
        "secret",
        "token",
    }
)


def _require_teacher(actor) -> None:
    if not can_teach(actor):
        raise AuthoringDraftError("An authenticated teacher is required.")


def _text(value: Any, field: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise AuthoringDraftError(f"{field} must be text.")
    result = value.strip()
    if required and not result:
        raise AuthoringDraftError(f"{field} is required.")
    if len(result) > maximum:
        raise AuthoringDraftError(f"{field} is too long.")
    return result


def _course_id(value: Any, *, actor, checker) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AuthoringDraftError("course_id must be a positive integer.")
    checker(actor, value)
    return value


def _strip_secret_keys(value: Any) -> None:
    """Reject provider credentials/reasoning anywhere in generated JSON."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in _SECRET_KEYS:
                raise AuthoringDraftError("The draft contains a forbidden private field.")
            _strip_secret_keys(child)
    elif isinstance(value, list):
        for child in value:
            _strip_secret_keys(child)


def _question_payload(*, actor, payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"title", "type_key", "definition", "metadata", "course_id"}
    if set(payload) - allowed:
        raise AuthoringDraftError("Unsupported question draft fields.")
    title = _text(payload.get("title"), "title", 200, required=True)
    type_key = _text(payload.get("type_key"), "type_key", 100, required=True)
    if "." not in type_key:
        type_key = f"liveclassroom.{type_key}"
    definition = payload.get("definition")
    if not isinstance(definition, dict):
        raise AuthoringDraftError("definition must be an object.")
    if "asset_id" in definition or type_key == "liveclassroom.file":
        raise AuthoringDraftError("AI drafts cannot create file activities.")
    try:
        normalized_definition = activity_registry.get(type_key).validate(deepcopy(definition))
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthoringDraftError("The generated question is not supported.") from exc
    metadata = payload.get("metadata", {})
    try:
        from .question_metadata import validate_question_metadata

        normalized_metadata = validate_question_metadata(metadata)
    except (TypeError, ValueError) as exc:
        raise AuthoringDraftError(str(exc)) from exc
    course_id = _course_id(payload.get("course_id"), actor=actor, checker=_check_course)
    return {
        "title": title,
        "type_key": type_key,
        "definition": normalized_definition,
        "metadata": normalized_metadata,
        **({"course_id": course_id} if course_id is not None else {}),
    }


def _check_course(actor, course_id: int) -> None:
    # The builder owns the actual course lookup and permission vocabulary.
    from liveclassroom.models import Course

    from .permissions import can_author_course

    course = Course.objects.filter(pk=course_id).first()
    if course is None or not can_author_course(actor, course):
        raise AuthoringDraftError("You do not have permission to use this course.")


def _deck_payload(*, actor, payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"title", "theme", "slides", "course_id"}
    if set(payload) - allowed:
        raise AuthoringDraftError("Unsupported deck draft fields.")
    title = _text(payload.get("title"), "title", 200, required=True)
    try:
        theme = deck_theme(_text(payload.get("theme", "default"), "theme", 80, required=True))
        course_id = _course_id(payload.get("course_id"), actor=actor, checker=_check_course)
        rows = _slides(actor, payload.get("slides", []))
    except ClassroomError as exc:
        raise AuthoringDraftError(str(exc)) from exc
    slides = []
    for row in rows:
        slides.append(
            {
                "key": str(row["key"]),
                "markdown": row["markdown"],
                "notes": row["notes"],
                "asset_ids": [str(asset.public_id) for asset in row["assets"]],
            }
        )
    return {
        "title": title,
        "theme": theme,
        "slides": slides,
        **({"course_id": course_id} if course_id is not None else {}),
    }


def _assessment_payload(*, actor, payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"title", "instructions", "items", "settings", "course_id"}
    if set(payload) - allowed:
        raise AuthoringDraftError("Unsupported assessment draft fields.")
    title = _text(payload.get("title"), "title", 200, required=True)
    instructions = _text(payload.get("instructions", ""), "instructions", 20_000)
    try:
        course_id = _course_id(payload.get("course_id"), actor=actor, checker=_check_course)
        settings = _settings(payload.get("settings", {}))
        rows = _item_rows(actor, payload.get("items", []))
    except ClassroomError as exc:
        raise AuthoringDraftError(str(exc)) from exc
    items = [
        {
            "key": str(row["key"]),
            "revision_id": row["revision"].pk,
            "points": format(Decimal(row["points"]).normalize(), "f"),
        }
        for row in rows
    ]
    return {
        "title": title,
        "instructions": instructions,
        "items": items,
        "settings": settings,
        **({"course_id": course_id} if course_id is not None else {}),
    }


def _validate_portable_adapter(*, actor, artifact_type: str, payload: Mapping[str, Any]) -> None:
    """Run accepted AI structures through the task 42 portable validator."""
    if artifact_type == AuthoringDraft.ArtifactType.QUESTION:
        portable = {
            "format": FORMAT,
            "version": VERSION,
            "activities": [
                {
                    "key": "activity-1",
                    "type_key": payload["type_key"],
                    "schema_version": 1,
                    "title": payload["title"],
                    "definition": payload["definition"],
                    "metadata": payload.get("metadata", {}),
                }
            ]
        }
    elif artifact_type == AuthoringDraft.ArtifactType.DECK:
        if not payload["slides"]:
            raise AuthoringDraftError("A generated deck needs at least one slide.")
        if any(row.get("asset_ids") for row in payload["slides"]):
            raise AuthoringDraftError("Generated deck assets must be added explicitly after review.")
        portable = {
            "format": FORMAT,
            "version": VERSION,
            "decks": [
                {
                    "key": "deck-1",
                    "title": payload["title"],
                    "theme": payload["theme"],
                    "slides": [
                        {
                            "key": f"slide-{index}",
                            "position": index,
                            "markdown": row["markdown"],
                            "notes": row["notes"],
                            "asset_keys": [],
                        }
                        for index, row in enumerate(payload["slides"], 1)
                    ],
                }
            ]
        }
    else:
        revisions = {}
        for item in payload["items"]:
            revision = ActivityDefinitionRevision.objects.select_related("definition").filter(
                pk=item["revision_id"]
            ).first()
            if revision is None:
                raise AuthoringDraftError("An assessment question revision is unavailable.")
            revisions[item["revision_id"]] = revision
        revision_keys = {revision_id: f"activity-{index}" for index, revision_id in enumerate(revisions, 1)}
        activities = [
            {
                "key": revision_keys[revision.pk],
                "type_key": revision.definition.type_key,
                "schema_version": 1,
                "title": revision.definition.title,
                "definition": revision.payload,
                "metadata": revision.metadata,
            }
            for revision in revisions.values()
        ]
        portable = {
            "format": FORMAT,
            "version": VERSION,
            "activities": activities,
            "assessments": [
                {
                    "key": "assessment-1",
                    "title": payload["title"],
                    "instructions": payload["instructions"],
                    "settings": payload["settings"],
                    "items": [
                        {
                            "key": item["key"],
                            "activity_key": revision_keys[item["revision_id"]],
                            "points": item["points"],
                        }
                        for item in payload["items"]
                    ],
                }
            ],
        }
    try:
        validate_portable(portable)
    except PortableContentError as exc:
        raise AuthoringDraftError(f"The generated {artifact_type} is not portable: {exc}") from exc


def validate_draft(*, actor, artifact_type: str, payload: Any) -> dict[str, Any]:
    """Validate and normalize an AI proposal without writing any object."""
    _require_teacher(actor)
    if artifact_type not in ARTIFACT_TYPES:
        raise AuthoringDraftError("Unsupported authoring draft type.")
    if not isinstance(payload, Mapping):
        raise AuthoringDraftError("Draft payload must be an object.")
    _strip_secret_keys(payload)
    if artifact_type == AuthoringDraft.ArtifactType.QUESTION:
        normalized = _question_payload(actor=actor, payload=payload)
    elif artifact_type == AuthoringDraft.ArtifactType.DECK:
        normalized = _deck_payload(actor=actor, payload=payload)
    else:
        normalized = _assessment_payload(actor=actor, payload=payload)
    _validate_portable_adapter(actor=actor, artifact_type=artifact_type, payload=normalized)
    return normalized


def _attachment_object(attachment, *, actor, request=None):
    from .authoring import _normalize_attachment, _stored_attachment_payload

    if isinstance(attachment, AuthoringAttachment):
        row = attachment
    elif isinstance(attachment, Mapping):
        normalized = _normalize_attachment(attachment, actor=actor, request=request)
        row = AuthoringAttachment(**normalized)
    else:
        raise AuthoringDraftError("Each authoring attachment must be an object.")
    try:
        return _stored_attachment_payload(row, actor=actor, request=request)
    except ClassroomError as exc:
        raise AuthoringDraftError(str(exc)) from exc


def build_authoring_context(
    *, actor, attachments: Iterable[AuthoringAttachment | Mapping[str, Any]], request=None
) -> dict[str, Any]:
    """Reauthorize exact selected sources and return minimal transient context."""
    _require_teacher(actor)
    rows = [_attachment_object(attachment, actor=actor, request=request) for attachment in attachments]
    return {"version": 1, "attachments": rows}


def _accepted_object(draft: AuthoringDraft):
    models = {
        "question": ActivityDefinition,
        "deck": Deck,
        "assessment": AssessmentDefinition,
    }
    model = models.get(draft.accepted_object_type)
    if model is None or draft.accepted_object_id is None:
        raise AuthoringDraftError("The accepted draft result is unavailable.")
    try:
        return model.objects.get(pk=draft.accepted_object_id)
    except model.DoesNotExist as exc:
        raise AuthoringDraftError("The accepted draft result is unavailable.") from exc


def _target_for(draft: AuthoringDraft, model):
    if not draft.target_type or draft.target_id is None:
        return None
    if draft.target_type != draft.artifact_type:
        raise AuthoringDraftError("The selected draft target has a different type.")
    try:
        target = model.objects.select_for_update().get(pk=draft.target_id)
    except model.DoesNotExist as exc:
        raise AuthoringDraftError("The selected draft target is unavailable.") from exc
    if target.owner_id != draft.owner_id:
        raise AuthoringDraftError("The selected draft target is not owned by you.")
    return target


def _accept_question(*, actor, draft, payload):
    from liveclassroom.models import Course

    target = _target_for(draft, ActivityDefinition)
    if target is None:
        course = Course.objects.filter(pk=payload.get("course_id")).first() if payload.get("course_id") else None
        return create_activity_definition(
            owner=actor,
            title=payload["title"],
            type_key=payload["type_key"],
            definition=payload["definition"],
            metadata=payload.get("metadata"),
            course=course,
            change_note="Accepted AI authoring draft",
        )
    current = target.current_revision.revision if target.current_revision_id else 0
    if draft.expected_version is not None and current != draft.expected_version:
        raise AuthoringDraftError("The question changed; refresh before saving.")
    revise_activity_definition(
        activity=target,
        definition=payload["definition"],
        metadata=payload.get("metadata"),
        actor=actor,
        change_note="Accepted AI authoring draft",
    )
    target.title = payload["title"]
    target.save(update_fields=["title", "updated_at"])
    return target


def _accept_deck(*, actor, draft, payload):
    from .decks import create_deck, replace_deck_slides, update_deck

    target = _target_for(draft, Deck)
    if target is None:
        return create_deck(actor=actor, data=payload)
    expected = draft.expected_version if draft.expected_version is not None else target.version
    if target.version != expected:
        raise AuthoringDraftError("The deck changed; refresh before saving.")
    changes = {key: payload[key] for key in ("title", "course_id", "theme") if key in payload}
    if changes:
        target = update_deck(actor=actor, deck=target, expected_version=expected, data=changes)
        expected = target.version
    return replace_deck_slides(actor=actor, deck=target, expected_version=expected, slides=payload["slides"])


def _accept_assessment(*, actor, draft, payload):
    from .assessments import create_assessment, replace_items, update_assessment

    target = _target_for(draft, AssessmentDefinition)
    if target is None:
        return create_assessment(actor=actor, data=payload)
    expected = draft.expected_version if draft.expected_version is not None else target.version
    if target.version != expected:
        raise AuthoringDraftError("The assessment changed; refresh before saving.")
    changes = {
        key: payload[key]
        for key in ("title", "instructions", "course_id", "settings")
        if key in payload
    }
    if changes:
        target = update_assessment(actor=actor, assessment=target, expected_version=expected, data=changes)
        expected = target.version
    return replace_items(actor=actor, assessment=target, expected_version=expected, items=payload["items"])


@transaction.atomic
def accept_authoring_draft(*, actor, draft: AuthoringDraft):
    """Accept once, creating or updating only an explicitly selected object."""
    _require_teacher(actor)
    locked = AuthoringDraft.objects.select_for_update().get(pk=draft.pk)
    if locked.owner_id != actor.pk:
        raise AuthoringDraftError("You do not have permission to accept this draft.")
    if locked.status == AuthoringDraft.Status.ACCEPTED:
        return _accepted_object(locked)
    if locked.status == AuthoringDraft.Status.REJECTED:
        raise AuthoringDraftError("A rejected draft cannot be accepted.")
    payload = validate_draft(actor=actor, artifact_type=locked.artifact_type, payload=locked.payload)
    if locked.artifact_type == AuthoringDraft.ArtifactType.QUESTION:
        result = _accept_question(actor=actor, draft=locked, payload=payload)
    elif locked.artifact_type == AuthoringDraft.ArtifactType.DECK:
        result = _accept_deck(actor=actor, draft=locked, payload=payload)
    else:
        result = _accept_assessment(actor=actor, draft=locked, payload=payload)
    locked.payload = payload
    locked.status = AuthoringDraft.Status.ACCEPTED
    locked.accepted_by = actor
    locked.accepted_at = timezone.now()
    locked.accepted_object_type = locked.artifact_type
    locked.accepted_object_id = result.pk
    locked.save(
        update_fields=[
            "payload",
            "status",
            "accepted_by",
            "accepted_at",
            "accepted_object_type",
            "accepted_object_id",
        ]
    )
    return result


@transaction.atomic
def reject_authoring_draft(*, actor, draft: AuthoringDraft) -> AuthoringDraft:
    _require_teacher(actor)
    locked = AuthoringDraft.objects.select_for_update().get(pk=draft.pk)
    if locked.owner_id != actor.pk:
        raise AuthoringDraftError("You do not have permission to reject this draft.")
    if locked.status == AuthoringDraft.Status.ACCEPTED:
        raise AuthoringDraftError("An accepted draft cannot be rejected.")
    if locked.status == AuthoringDraft.Status.PROPOSED:
        locked.status = AuthoringDraft.Status.REJECTED
        locked.rejected_at = timezone.now()
        locked.save(update_fields=["status", "rejected_at"])
    return locked


def draft_payload(draft: AuthoringDraft) -> dict[str, Any]:
    """Serialize only safe draft metadata for the private teacher owner."""
    return {
        "id": draft.id,
        "thread_id": draft.thread_id,
        "message_id": draft.message_id,
        "artifact_type": draft.artifact_type,
        "payload": draft.payload,
        "source_fingerprints": list(draft.source_fingerprints or []),
        "status": draft.status,
        "accepted_object_type": draft.accepted_object_type,
        "accepted_object_id": draft.accepted_object_id,
        "target_type": draft.target_type,
        "target_id": draft.target_id,
        "expected_version": draft.expected_version,
        "created_at": draft.created_at,
        "accepted_at": draft.accepted_at,
        "rejected_at": draft.rejected_at,
    }


def parse_draft_envelope(*, content: str, artifact_type: str) -> tuple[dict[str, Any], list[str]]:
    """Parse the strict backend envelope without accepting free-form prose."""
    try:
        envelope = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AuthoringDraftError("The AI backend returned an invalid draft envelope.") from exc
    if not isinstance(envelope, Mapping) or set(envelope) - {"artifact_type", "payload", "source_fingerprints"}:
        raise AuthoringDraftError("The AI backend returned an invalid draft envelope.")
    if envelope.get("artifact_type") != artifact_type or not isinstance(envelope.get("payload"), Mapping):
        raise AuthoringDraftError("The AI backend returned an invalid draft envelope.")
    fingerprints = envelope.get("source_fingerprints", [])
    if not isinstance(fingerprints, list) or len(fingerprints) > 50:
        raise AuthoringDraftError("The AI backend returned invalid source fingerprints.")
    if any(not isinstance(item, str) or not item or len(item) > 128 for item in fingerprints):
        raise AuthoringDraftError("The AI backend returned invalid source fingerprints.")
    return dict(envelope["payload"]), list(dict.fromkeys(fingerprints))
