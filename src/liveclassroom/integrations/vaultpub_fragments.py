"""Optional VaultPub renderer for one authorized Markdown fragment.

The caller is responsible for deciding whether a teacher or participant may
read the selected field.  This module only receives the already selected
Markdown and a reverse-generated URL prefix.  It deliberately renders a
request-local temporary note so VaultPub never indexes the host vault or a
neighboring note.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse

from .vaultpub_documents import (
    VaultPubUnavailable,
    _validated_url_prefix,
    _vaultpub_api,
    _with_document_state,
)

MAX_FRAGMENT_CHARS = 200_000


def render_fragment(
    request: HttpRequest,
    *,
    markdown: str,
    url_prefix: str,
    revision_key: str,
) -> JsonResponse:
    """Render one selected Markdown field through VaultPub's safe article API.

    ``markdown`` must already have passed the caller's field and permission
    checks.  The optional integration returns a concise 503 when VaultPub is
    unavailable; the frontend can then retain its basic synchronous renderer.
    ``resources`` contains only direct sibling assets that VaultPub actually
    registered while rendering this temporary note.
    """
    rejected = _require_read_method(request)
    if rejected is not None:
        return rejected  # type: ignore[return-value]
    if not isinstance(markdown, str):
        raise ValueError("markdown must be a string")
    if not isinstance(revision_key, str) or not revision_key or len(revision_key) > 255:
        raise ValueError("revision_key must be a non-empty string")
    if len(markdown) > MAX_FRAGMENT_CHARS:
        raise ValueError("markdown fragment is too large")
    prefix = _validated_url_prefix(url_prefix)

    # Probe before creating a temporary file.  This keeps a missing optional
    # dependency an explicit capability response and avoids path-bearing errors.
    _config_type, views = _vaultpub_api()
    if not callable(getattr(views, "render_api_page_with_config", None)):
        raise VaultPubUnavailable("Installed VaultPub lacks the fragment rendering API.")
    with TemporaryDirectory(prefix="liveclassroom-fragment-") as directory:
        note_path = Path(directory) / "fragment.md"
        note_path.write_text(markdown, encoding="utf-8")

        def render(views: Any, config: Any, note_path_value: str, key: str) -> JsonResponse:
            upstream = views.render_api_page_with_config(
                request,
                config,
                note_path_value,
                cache_key=key,
            )
            try:
                payload = json.loads(upstream.content)
            except (TypeError, ValueError) as exc:
                raise VaultPubUnavailable("VaultPub returned an invalid fragment response.") from exc
            html = payload.get("html")
            if not isinstance(html, str):
                raise VaultPubUnavailable("VaultPub returned no fragment HTML.")
            state = views.build_state_for_config(config, cache_key=key)
            resources = _resource_urls(state, prefix)
            return JsonResponse(
                {
                    "html": html,
                    "revision_key": revision_key,
                    "resources": resources,
                }
            )

        response = _with_document_state(
            markdown_path=note_path,
            url_prefix=prefix,
            render=render,
        )
    response["Cache-Control"] = "private, no-store"
    return response  # type: ignore[return-value]


def _resource_urls(state: dict[str, Any], prefix: str) -> list[str]:
    """Return URLs for assets registered by the exact temporary note only."""
    renderer = state.get("renderer")
    dynamic = getattr(renderer, "dynamic_attachments_by_path", {})
    result: list[str] = []
    for raw_path in dynamic:
        path = PurePosixPath(str(raw_path))
        if len(path.parts) != 1 or path.is_absolute() or path.suffix.lower() == ".md":
            continue
        result.append(f"{prefix}__assets__/{path.as_posix()}")
    return sorted(set(result))


def _require_read_method(request: HttpRequest) -> HttpResponse | None:
    if request.method not in {"GET", "HEAD"}:
        return HttpResponseNotAllowed(["GET", "HEAD"])
    return None
