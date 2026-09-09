"""Teacher-only native-deck previews backed by the optional VaultPub renderer."""

from __future__ import annotations

from tempfile import TemporaryDirectory

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_safe

from .integrations.vaultpub_documents import VaultPubUnavailable, render_document
from .models import Deck
from .services.permissions import can_teach


def deck_preview_markdown(deck: Deck) -> str:
    """Compose public slides only; private presenter notes never reach VaultPub."""
    slides = [slide.markdown for slide in deck.slides.order_by("position", "id")]
    return "\n\n---\n\n".join(slides) or f"# {deck.title}\n"


@require_safe
@xframe_options_sameorigin
def preview(request, deck_id: int):
    if not can_teach(request.user):
        raise Http404
    deck = get_object_or_404(Deck, pk=deck_id, owner=request.user)
    with TemporaryDirectory(prefix="liveclassroom-deck-preview-") as directory:
        from pathlib import Path

        path = Path(directory) / "deck.md"
        path.write_text(deck_preview_markdown(deck), encoding="utf-8")
        try:
            return render_document(
                request,
                markdown_path=path,
                url_prefix=reverse("liveclassroom:deck-preview", args=[deck.id]),
                mode="slides",
            )
        except VaultPubUnavailable:
            return JsonResponse(
                {"detail": "Slide preview is unavailable.", "code": "vaultpub_unavailable"}, status=503
            )
