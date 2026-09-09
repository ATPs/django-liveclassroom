"""HTTP adapters for Markdown deck preview, import, and export."""

from __future__ import annotations

from uuid import UUID

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from .api import _authoring_replay, _body, _error, _record_authoring
from .importers.decks import DeckImportError, import_deck, preview_deck_import
from .models import ClassroomAsset, Deck
from .services.classroom import ClassroomError
from .services.deck_export import export_deck_markdown
from .services.decks import deck_payload
from .services.permissions import can_teach


def _access(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    return None


def _approved_assets(actor, value):
    """Resolve only owner-visible uploaded/server assets; no paths are opened."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise DeckImportError("assets must be a list of approved asset IDs.")
    assets = []
    for raw in value:
        try:
            asset_id = UUID(str(raw))
        except (TypeError, ValueError) as exc:
            raise DeckImportError("Each asset ID must be a UUID.") from exc
        asset = ClassroomAsset.objects.filter(public_id=asset_id).first()
        if asset is None:
            raise DeckImportError("One referenced asset was not found.")
        assets.append(asset)
    return assets


def _mutate(request, command_type: str, action):
    denied = _access(request)
    if denied is not None:
        return denied
    replay, key = _authoring_replay(request, command_type)
    if replay is not None:
        return replay
    try:
        response = action()
    except (DeckImportError, ClassroomError) as exc:
        response = _error(str(exc), 400)
    return _record_authoring(request, key, command_type, response)


@require_http_methods(["POST"])
def deck_import_preview(request):
    """Validate Markdown and return a draft with slide-specific errors."""
    denied = _access(request)
    if denied is not None:
        return denied
    try:
        body = _body(request)
        if set(body) - {"text", "markdown", "assets", "asset_ids"}:
            raise DeckImportError("Unsupported import preview fields.")
        text = body.get("text", body.get("markdown"))
        assets = _approved_assets(request.user, body.get("assets", body.get("asset_ids", [])))
        result = preview_deck_import(request.user, text, assets)
    except (DeckImportError, ClassroomError) as exc:
        return _error(str(exc), 400)
    return JsonResponse(result)


@require_http_methods(["POST"])
def deck_import(request):
    """Create a native deck only after a complete successful preview."""
    def action():
        body = _body(request)
        if set(body) - {"draft"}:
            raise DeckImportError("Import requires a validated draft.")
        deck = import_deck(request.user, body.get("draft"))
        return JsonResponse(deck_payload(deck), status=201)

    return _mutate(request, "deck.import", action)


@require_http_methods(["GET"])
def deck_export(request, deck_id: int):
    """Download owner-only Markdown; notes require an explicit query opt-in."""
    denied = _access(request)
    if denied is not None:
        return denied
    deck = get_object_or_404(Deck, pk=deck_id, owner=request.user)
    raw_include = request.GET.get("include_notes", "0").strip().lower()
    if raw_include not in {"0", "1", "false", "true"}:
        return _error("include_notes must be true or false.")
    try:
        markdown = export_deck_markdown(
            actor=request.user,
            deck=deck,
            include_notes=raw_include in {"1", "true"},
        )
    except ClassroomError as exc:
        return _error(str(exc), 400)
    response = HttpResponse(markdown, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="deck-{deck.id}.md"'
    response["Cache-Control"] = "private, no-store"
    return response
