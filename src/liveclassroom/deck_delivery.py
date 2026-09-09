"""Authorized delivery adapters for immutable native deck snapshots."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_safe

from .integrations.vaultpub_documents import (
    VaultPubUnavailable,
    render_document,
    render_slides_payload,
    serve_document_resource,
)
from .models import DeckSnapshot, LiveSession, Participant
from .services.assets import open_asset
from .services.classroom import ClassroomError, can_view_session
from .services.deck_snapshots import deck_snapshot_notes_payload
from .services.decks import deck_markdown_document
from .services.presentation import (
    native_deck_entry,
    native_deck_presentation_payload,
)


def _participant_for_request(request, session: LiveSession):
    """Use the package's existing participant cookie/session identity boundary."""
    from .api import _participant_for_request

    return _participant_for_request(request, session)


def _authorized_snapshot(
    request, session_id: int, snapshot_id: int, *, channel: str
) -> tuple[LiveSession, DeckSnapshot, dict]:
    session = get_object_or_404(LiveSession, pk=session_id)
    if channel not in {"display", "participants"}:
        raise Http404
    if can_view_session(request.user, session):
        # Teachers may inspect either audience's currently presented snapshot.
        entry = native_deck_entry(session, channel)
    else:
        participant = _participant_for_request(request, session)
        if participant is None or participant.admission_state != Participant.AdmissionState.ADMITTED:
            raise Http404
        if session.status == LiveSession.Status.ENDED:
            raise Http404
        entry = native_deck_entry(session, "participants") if channel == "participants" else None
    if not entry or entry.get("snapshot_id") != snapshot_id:
        raise Http404
    snapshot = get_object_or_404(DeckSnapshot, pk=snapshot_id)
    return session, snapshot, entry


def _public_payload(request, session: LiveSession, snapshot: DeckSnapshot, entry: dict) -> dict:
    payload = native_deck_presentation_payload(snapshot, entry)
    session_id = session.pk
    payload.update(
        {
            "payload_url": reverse("liveclassroom:api-v1-session-deck-payload", args=[session_id, snapshot.pk]),
            "slides_url": reverse("liveclassroom:api-v1-session-deck-slides", args=[session_id, snapshot.pk]),
            "resource_url_template": reverse(
                "liveclassroom:api-v1-session-deck-resource", args=[session_id, snapshot.pk, "__resource__"]
            ).replace("__resource__", "{resource_path}"),
        }
    )
    return payload


def _manifest_markdown(snapshot: DeckSnapshot) -> str:
    slides = snapshot.public_manifest if isinstance(snapshot.public_manifest, list) else []
    parts = [item.get("markdown", "") for item in slides if isinstance(item, dict)]
    return deck_markdown_document(slides=parts, title=snapshot.title, theme=snapshot.theme)


@contextmanager
def _staged_snapshot(snapshot: DeckSnapshot):
    """Create a request-local VaultPub document with only retained assets."""
    with TemporaryDirectory(prefix="liveclassroom-deck-") as directory:
        root = Path(directory)
        markdown_path = root / "deck.md"
        markdown_path.write_text(_manifest_markdown(snapshot), encoding="utf-8")
        for asset in snapshot.assets.all():
            name = Path(asset.original_name).name
            if not name or name in {".", ".."}:
                continue
            destination = root / name
            try:
                handle, _size = open_asset(asset)
                try:
                    with destination.open("wb") as output:
                        while chunk := handle.read(64 * 1024):
                            output.write(chunk)
                finally:
                    handle.close()
            except (ClassroomError, OSError):
                # The resource route will return an unavailable response for a
                # missing asset. Do not let one optional image hide text slides.
                continue
        yield markdown_path, root


def _render_unavailable():
    return JsonResponse({"detail": "Deck rendering is unavailable.", "code": "vaultpub_unavailable"}, status=503)


@require_safe
def snapshot_payload(request, session_id: int, snapshot_id: int):
    """Return the public immutable manifest for the active participant deck."""
    session, snapshot, entry = _authorized_snapshot(
        request, session_id, snapshot_id, channel=request.GET.get("channel", "participants")
    )
    payload = _public_payload(request, session, snapshot, entry)
    payload["slides"] = [
        {
            "key": item.get("key"),
            "position": item.get("position"),
            "markdown": item.get("markdown", ""),
            "asset_ids": item.get("asset_ids", []),
        }
        for item in snapshot.public_manifest
        if isinstance(item, dict)
    ]
    return JsonResponse(payload)


@require_safe
def snapshot_notes(request, session_id: int, snapshot_id: int):
    """Return retained presenter notes through a teacher-only session route."""
    session, snapshot, _entry = _authorized_snapshot(
        request, session_id, snapshot_id, channel=request.GET.get("channel", "display")
    )
    # Staff who can inspect a session must not automatically gain access to
    # speaker notes.  The stronger session-management capability is required.
    from .services.classroom import can_manage_session

    if not can_manage_session(request.user, session):
        raise Http404
    response = JsonResponse(deck_snapshot_notes_payload(snapshot))
    response["Cache-Control"] = "private, no-store"
    return response


@require_safe
@xframe_options_sameorigin
def snapshot_slides(request, session_id: int, snapshot_id: int):
    """Render public deck Markdown through VaultPub when the optional extra exists."""
    _session, snapshot, _entry = _authorized_snapshot(
        request, session_id, snapshot_id, channel=request.GET.get("channel", "participants")
    )
    prefix = reverse("liveclassroom:api-v1-session-deck-slides", args=[session_id, snapshot_id])
    with _staged_snapshot(snapshot) as (markdown_path, _root):
        try:
            response = render_document(request, markdown_path=markdown_path, url_prefix=prefix, mode="slides")
        except VaultPubUnavailable:
            return _render_unavailable()
    response["Cache-Control"] = "private, no-store"
    return response


@require_safe
def snapshot_slides_payload(request, session_id: int, snapshot_id: int):
    _session, snapshot, _entry = _authorized_snapshot(
        request, session_id, snapshot_id, channel=request.GET.get("channel", "participants")
    )
    prefix = reverse("liveclassroom:api-v1-session-deck-slides", args=[session_id, snapshot_id])
    with _staged_snapshot(snapshot) as (markdown_path, _root):
        try:
            response = render_slides_payload(request, markdown_path=markdown_path, url_prefix=prefix)
        except VaultPubUnavailable:
            return _render_unavailable()
    response["Cache-Control"] = "private, no-store"
    return response


@require_safe
def snapshot_resource(request, session_id: int, snapshot_id: int, resource_path: str):
    _session, snapshot, _entry = _authorized_snapshot(
        request, session_id, snapshot_id, channel=request.GET.get("channel", "participants")
    )
    clean = Path(resource_path)
    if clean.name != resource_path or clean.suffix.lower() == ".md" or resource_path in {"", ".", ".."}:
        raise Http404
    if not snapshot.assets.filter(original_name=clean.name).exists():
        raise Http404
    prefix = reverse("liveclassroom:api-v1-session-deck-slides", args=[session_id, snapshot_id])
    with _staged_snapshot(snapshot) as (markdown_path, _root):
        try:
            response = serve_document_resource(
                request, markdown_path=markdown_path, url_prefix=prefix, resource_path=resource_path
            )
        except (VaultPubUnavailable, ClassroomError, OSError):
            return _render_unavailable()
    response["Cache-Control"] = "private, no-store"
    return response
