"""Authorized route adapters for one retained VaultPub-rendered Markdown document."""

from __future__ import annotations

from collections.abc import Callable

from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_safe

from .integrations.vaultpub_documents import (
    VaultPubUnavailable,
    render_document,
    render_slides_payload,
    serve_document_resource,
)
from .services.classroom import ClassroomError
from .services.documents import authorize_asset_document, authorize_session_document, stage_markdown_asset


def _unavailable():
    return JsonResponse(
        {"detail": "Document rendering is unavailable.", "code": "vaultpub_unavailable"},
        status=503,
    )


def _render(request, *, asset, prefix: str, note_path: str | None, action: Callable):
    try:
        with stage_markdown_asset(asset) as staged:
            if note_path is not None and note_path != staged.filename:
                raise Http404("Document not found")
            return action(staged.path, prefix)
    except VaultPubUnavailable:
        return _unavailable()
    except (ClassroomError, OSError):
        raise Http404("Document not found") from None


def _asset_context(request, asset_id):
    asset = authorize_asset_document(actor=request.user, asset_id=asset_id)
    prefix = reverse("liveclassroom:api-v1-document-root", args=[asset.public_id])
    return asset, prefix


def _session_context(request, session_id, revision_id, asset_id):
    _session, revision = authorize_session_document(
        request=request,
        session_id=session_id,
        revision_id=revision_id,
        asset_id=asset_id,
    )
    prefix = reverse(
        "liveclassroom:api-v1-session-document-root",
        args=[session_id, revision_id, asset_id],
    )
    return revision.asset, prefix


@require_safe
@xframe_options_sameorigin
def document_note(request, asset_id, note_path=None):
    asset, prefix = _asset_context(request, asset_id)
    return _render(
        request,
        asset=asset,
        prefix=prefix,
        note_path=note_path,
        action=lambda path, url_prefix: render_document(
            request, markdown_path=path, url_prefix=url_prefix, mode="note"
        ),
    )


@require_safe
@xframe_options_sameorigin
def document_slides(request, asset_id, note_path):
    asset, prefix = _asset_context(request, asset_id)
    return _render(
        request,
        asset=asset,
        prefix=prefix,
        note_path=note_path,
        action=lambda path, url_prefix: render_document(
            request, markdown_path=path, url_prefix=url_prefix, mode="slides"
        ),
    )


@require_safe
def document_slides_payload(request, asset_id, note_path):
    asset, prefix = _asset_context(request, asset_id)
    return _render(
        request,
        asset=asset,
        prefix=prefix,
        note_path=note_path,
        action=lambda path, url_prefix: render_slides_payload(
            request, markdown_path=path, url_prefix=url_prefix
        ),
    )


@require_safe
def document_resource(request, asset_id, resource_path):
    asset, prefix = _asset_context(request, asset_id)
    return _render(
        request,
        asset=asset,
        prefix=prefix,
        note_path=None,
        action=lambda path, url_prefix: serve_document_resource(
            request, markdown_path=path, url_prefix=url_prefix, resource_path=resource_path
        ),
    )


def _session_view(handler):
    def view(request, session_id, revision_id, asset_id, **kwargs):
        asset, prefix = _session_context(request, session_id, revision_id, asset_id)
        return handler(request, asset=asset, prefix=prefix, **kwargs)

    return require_safe(view)


@_session_view
@xframe_options_sameorigin
def session_document_note(request, *, asset, prefix, note_path=None):
    return _render(
        request,
        asset=asset,
        prefix=prefix,
        note_path=note_path,
        action=lambda path, url_prefix: render_document(
            request, markdown_path=path, url_prefix=url_prefix, mode="note"
        ),
    )


@_session_view
@xframe_options_sameorigin
def session_document_slides(request, *, asset, prefix, note_path):
    return _render(
        request,
        asset=asset,
        prefix=prefix,
        note_path=note_path,
        action=lambda path, url_prefix: render_document(
            request, markdown_path=path, url_prefix=url_prefix, mode="slides"
        ),
    )


@_session_view
def session_document_slides_payload(request, *, asset, prefix, note_path):
    return _render(
        request,
        asset=asset,
        prefix=prefix,
        note_path=note_path,
        action=lambda path, url_prefix: render_slides_payload(
            request, markdown_path=path, url_prefix=url_prefix
        ),
    )


@_session_view
def session_document_resource(request, *, asset, prefix, resource_path):
    return _render(
        request,
        asset=asset,
        prefix=prefix,
        note_path=None,
        action=lambda path, url_prefix: serve_document_resource(
            request, markdown_path=path, url_prefix=url_prefix, resource_path=resource_path
        ),
    )
