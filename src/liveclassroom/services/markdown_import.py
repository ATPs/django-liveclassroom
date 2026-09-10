"""Preview and atomically commit portable Markdown/YAML imports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db import transaction

from liveclassroom.models import (
    ActivityDefinition,
    AssessmentDefinition,
    AuthoringCommandReceipt,
    ClassroomAsset,
    Deck,
    Flow,
    QuestionBank,
)
from liveclassroom.services.portable_content import ImportResult, PortableContentError, import_portable

from ..importers.markdown_portable import ImportDraft, ImportErrorDetail, parse_markdown_import


class MarkdownImportError(PortableContentError):
    """A preview cannot be committed as submitted."""


def preview_markdown_import(*, actor: Any, filename: Any, content: Any) -> ImportDraft:
    """Return a nonpersistent, owner-scoped draft and source fingerprint."""
    return parse_markdown_import(actor=actor, filename=filename, content=content)


def _draft_values(
    draft: ImportDraft | Mapping[str, Any],
    *,
    filename: Any = None,
    content: Any = None,
    draft_fingerprint: str | None = None,
) -> tuple[str, str, str]:
    if isinstance(draft, ImportDraft):
        source_name = draft.filename
        source_content = draft.content
        expected = draft.fingerprint
    elif isinstance(draft, Mapping):
        source_name = draft.get("filename", filename)
        source_content = draft.get("content", content)
        expected = draft.get("fingerprint", draft_fingerprint)
    else:
        raise MarkdownImportError("A Markdown import draft is required.")
    if not isinstance(source_name, str) or not isinstance(source_content, (str, bytes)):
        raise MarkdownImportError("The draft must retain its original filename and content.")
    if not isinstance(expected, str) or not expected:
        raise MarkdownImportError("The draft fingerprint is required.")
    if isinstance(source_content, bytes):
        try:
            source_content = source_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MarkdownImportError("The draft content must be valid UTF-8.") from exc
    return source_name, source_content, expected


def _result_from_receipt(actor: Any, response: Mapping[str, Any]) -> ImportResult:
    objects = response.get("objects") if isinstance(response, Mapping) else None
    if not isinstance(objects, list):
        raise MarkdownImportError("The saved import receipt is invalid.")
    models = {
        "activity": (ActivityDefinition, "activities"),
        "deck": (Deck, "decks"),
        "assessment": (AssessmentDefinition, "assessments"),
        "bank": (QuestionBank, "banks"),
        "flow": (Flow, "flows"),
        "asset": (ClassroomAsset, "assets"),
    }
    grouped: dict[str, list[Any]] = {name: [] for _, name in models.values()}
    for row in objects:
        if not isinstance(row, Mapping) or row.get("kind") not in models:
            raise MarkdownImportError("The saved import receipt is invalid.")
        model, group = models[row["kind"]]
        try:
            obj = model.objects.get(pk=row["id"], owner_id=actor.pk)
        except model.DoesNotExist as exc:
            raise MarkdownImportError("The saved import result is no longer available.") from exc
        grouped[group].append(obj)
    return ImportResult(
        activities=grouped["activities"],
        decks=grouped["decks"],
        assessments=grouped["assessments"],
        banks=grouped["banks"],
        flows=grouped["flows"],
        assets=grouped["assets"],
    )


def _draft_error(draft: ImportDraft) -> MarkdownImportError:
    if not draft.errors:
        return MarkdownImportError("The import preview is invalid.")
    first: ImportErrorDetail = draft.errors[0]
    location = f" at {first.path}"
    if first.line is not None:
        location += f" line {first.line}"
    return MarkdownImportError(f"{first.message}{location}.")


def commit_markdown_import(
    *,
    actor: Any,
    draft: ImportDraft | Mapping[str, Any],
    idempotency_key: str | None = None,
    filename: Any = None,
    content: Any = None,
    draft_fingerprint: str | None = None,
) -> ImportResult:
    """Revalidate and atomically copy one previewed document through task 42."""
    source_name, source_content, expected = _draft_values(
        draft,
        filename=filename,
        content=content,
        draft_fingerprint=draft_fingerprint,
    )
    fresh = parse_markdown_import(actor=actor, filename=source_name, content=source_content)
    if fresh.fingerprint != expected:
        raise MarkdownImportError("The source changed after preview; request a new preview.")
    if not fresh.valid:
        raise _draft_error(fresh)
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
            raise MarkdownImportError("idempotency_key must be non-empty text of at most 160 characters.")
        idempotency_key = idempotency_key.strip()

    def _copy() -> ImportResult:
        result = import_portable(actor=actor, payload=fresh.payload)
        if idempotency_key:
            AuthoringCommandReceipt.objects.create(
                owner=actor,
                idempotency_key=idempotency_key,
                command_type="markdown.import",
                request_hash=fresh.fingerprint,
                response={"objects": result.objects},
                status_code=201,
            )
        return result

    if not idempotency_key:
        return _copy()
    with transaction.atomic():
        receipt = (
            AuthoringCommandReceipt.objects.select_for_update()
            .filter(owner=actor, idempotency_key=idempotency_key)
            .first()
        )
        if receipt is not None:
            if receipt.command_type != "markdown.import" or receipt.request_hash != fresh.fingerprint:
                raise MarkdownImportError("This idempotency key was already used with different input.")
            return _result_from_receipt(actor, receipt.response)
        return _copy()


__all__ = ["MarkdownImportError", "commit_markdown_import", "preview_markdown_import"]
