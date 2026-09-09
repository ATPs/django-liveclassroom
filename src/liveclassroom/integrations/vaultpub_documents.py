"""Optional, exact-document adapter for VaultPub's Django renderer.

Callers authorize the selected retained Markdown document before reaching this
module.  It deliberately exposes no filesystem-path route or classroom policy.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from django.apps import apps
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse


class VaultPubUnavailable(RuntimeError):
    """Raised when the optional VaultPub document renderer cannot be used."""


def render_document(
    request: HttpRequest, *, markdown_path: Path, url_prefix: str, mode: str = "slides"
) -> HttpResponse:
    """Render one authorized Markdown document as a VaultPub note or slide deck."""
    rejected = _require_read_method(request)
    if rejected is not None:
        return rejected
    if mode not in {"note", "slides"}:
        raise ValueError("mode must be 'note' or 'slides'")
    return _with_document_state(
        markdown_path=markdown_path,
        url_prefix=url_prefix,
        render=lambda views, config, note_path, key: (
            views.render_page_with_config(
                request, config, note_path, cache_key=key, show_order_editor=False
            )
            if mode == "note"
            else views.render_slides_with_config(request, config, note_path, cache_key=key)
        ),
    )


def render_slides_payload(
    request: HttpRequest, *, markdown_path: Path, url_prefix: str
) -> JsonResponse:
    """Return VaultPub's slide JSON payload for one authorized Markdown document."""
    rejected = _require_read_method(request)
    if rejected is not None:
        return rejected  # type: ignore[return-value]
    return _with_document_state(
        markdown_path=markdown_path,
        url_prefix=url_prefix,
        render=lambda views, config, note_path, key: views.render_api_slides_with_config(
            request, config, note_path, cache_key=key
        ),
    )  # type: ignore[return-value]


def serve_document_resource(
    request: HttpRequest, *, markdown_path: Path, url_prefix: str, resource_path: str
) -> HttpResponse:
    """Stream one referenced, direct-sibling non-Markdown resource for a document."""
    rejected = _require_read_method(request)
    if rejected is not None:
        return rejected
    selected_path = _validated_markdown_path(markdown_path)
    resource_name = _validated_resource_path(resource_path, selected_path.parent)

    def render(views: Any, config: Any, note_path: str, key: str) -> HttpResponse:
        return views.render_attachment_with_config(request, config, resource_name, cache_key=key)

    return _with_document_state(markdown_path=selected_path, url_prefix=url_prefix, render=render)


def _with_document_state(*, markdown_path: Path, url_prefix: str, render: Any) -> HttpResponse:
    """Build, prime, use, and discard one non-shared VaultPub renderer state."""
    config_type, views = _vaultpub_api()
    selected_path = _validated_markdown_path(markdown_path)
    prefix = _validated_url_prefix(url_prefix)
    config = config_type(
        vault_path=selected_path,
        url_prefix=prefix,
        html_safe_mode=True,
        allow_raw_html=False,
        follow_symlinks=False,
        hidden_file_access=False,
        include_all_attachments=False,
        realtime=False,
        show_navigation=False,
        show_search=False,
        show_graph=False,
        show_local_graph=False,
        show_toc=False,
        show_backlinks=False,
        show_hover_preview=False,
        show_unlinked_mentions=False,
    )
    key = f"liveclassroom.document.{uuid4().hex}"
    try:
        state = views.build_state_for_config(config, cache_key=key)
        note_path = str(config.entry_file or "")
        note = next(
            (
                candidate
                for candidate in state["index"].notes_by_id.values()
                if candidate.rel_path.as_posix() == note_path
            ),
            None,
        )
        if note is None:
            raise Http404("Document not found")
        # Rendering first is required for VaultPub single-file mode to register
        # only the resources this note directly references.
        state["renderer"].render_note(note)
        response = render(views, config, note_path, key)
        response["Cache-Control"] = "private, no-store"
        return response
    finally:
        views.clear_state_cache(key)


def _vaultpub_api() -> tuple[Any, Any]:
    """Import and validate the optional upstream APIs only when invoked."""
    try:
        from vaultpub.core.config import PublisherConfig
        from vaultpub.django_app import views
    except ImportError as exc:
        raise VaultPubUnavailable("VaultPub document rendering requires the optional vaultpub dependency.") from exc
    if "entry_file" not in PublisherConfig.__dataclass_fields__:
        raise VaultPubUnavailable("Installed VaultPub does not support exact Markdown-file rendering.")
    required = (
        "build_state_for_config",
        "clear_state_cache",
        "render_page_with_config",
        "render_slides_with_config",
        "render_api_slides_with_config",
        "render_attachment_with_config",
    )
    if any(not callable(getattr(views, name, None)) for name in required):
        raise VaultPubUnavailable("Installed VaultPub lacks the required document-rendering APIs.")
    if not apps.is_installed("vaultpub.django_app"):
        raise VaultPubUnavailable("VaultPub document rendering requires vaultpub.django_app in INSTALLED_APPS.")
    return PublisherConfig, views


def _validated_markdown_path(markdown_path: Path) -> Path:
    """Accept only an existing absolute Markdown file without exposing its path."""
    path = Path(markdown_path)
    if not path.is_absolute() or path.suffix.lower() != ".md":
        raise ValueError("markdown_path must be an absolute Markdown file")
    if not path.exists() or not path.is_file():
        raise Http404("Document not found")
    return path.resolve(strict=True)


def _validated_url_prefix(url_prefix: str) -> str:
    """Accept one caller-controlled same-origin URL path ending in a slash."""
    if not isinstance(url_prefix, str) or not url_prefix:
        raise ValueError("url_prefix must be a same-origin URL path")
    if "\\" in url_prefix or any(ord(character) < 32 or ord(character) == 127 for character in url_prefix):
        raise ValueError("url_prefix must be a safe URL path")
    parsed = urlsplit(url_prefix)
    decoded_path = unquote(parsed.path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or not parsed.path.endswith("/")
        or any(part in {".", ".."} for part in decoded_path.split("/"))
    ):
        raise ValueError("url_prefix must be a same-origin URL path ending in '/'")
    return parsed.path


def _validated_resource_path(resource_path: str, root: Path) -> str:
    """Limit resources to direct, real non-Markdown siblings of the selected note."""
    if not isinstance(resource_path, str) or not resource_path or "\\" in resource_path:
        raise Http404("Resource not found")
    candidate = PurePosixPath(resource_path)
    if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.suffix.lower() == ".md":
        raise Http404("Resource not found")
    location = root / resource_path
    if location.is_symlink() or not location.is_file() or location.resolve().parent != root.resolve():
        raise Http404("Resource not found")
    return candidate.as_posix()


def _require_read_method(request: HttpRequest) -> HttpResponse | None:
    if request.method not in {"GET", "HEAD"}:
        return HttpResponseNotAllowed(["GET", "HEAD"])
    return None
