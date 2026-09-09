"""Integration coverage for the optional exact-file VaultPub adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import Http404
from django.template.loader import get_template
from django.test import RequestFactory, override_settings

from liveclassroom.integrations import vaultpub_documents
from liveclassroom.integrations.vaultpub_documents import (
    VaultPubUnavailable,
    render_document,
    render_slides_payload,
    serve_document_resource,
)


@pytest.fixture
def request_factory() -> RequestFactory:
    return RequestFactory()


@pytest.fixture
def vaultpub_enabled():
    """Install VaultPub only for a test, without changing shared settings."""
    installed_apps = [*settings.INSTALLED_APPS, "vaultpub.django_app"]
    with override_settings(INSTALLED_APPS=installed_apps):
        yield


def _document(tmp_path: Path, name: str = "Deck.md", content: str | None = None) -> Path:
    note = tmp_path / name
    note.write_text(
        content
        or """# First slide

| Name | Value |
| --- | --- |
| alpha | 1 |

![A direct image](image.png)

> [!note] Important
> A callout from VaultPub.

$$x^2$$

```mermaid
graph TD
  A --> B
```

---

# Second slide

The second fragment.
""",
        encoding="utf-8",
    )
    (tmp_path / "image.png").write_bytes(b"PNG bytes")
    return note


def _prefix() -> str:
    return "/classroom/documents/example/"


def test_base_import_and_missing_django_app_are_explicit(request_factory, tmp_path):
    note = _document(tmp_path)
    assert vaultpub_documents.VaultPubUnavailable is VaultPubUnavailable

    with pytest.raises(VaultPubUnavailable, match="INSTALLED_APPS"):
        render_document(request_factory.get("/"), markdown_path=note, url_prefix=_prefix())


def test_full_note_slides_and_payload_delegate_to_vaultpub(vaultpub_enabled, request_factory, tmp_path):
    note = _document(tmp_path)

    page = render_document(request_factory.get("/"), markdown_path=note, url_prefix=_prefix(), mode="note")
    page_body = page.content.decode()
    assert page.status_code == 200
    assert "<table" in page_body
    assert "callout" in page_body
    assert "/classroom/documents/example/" in page_body
    assert "image.png" in page_body
    assert "mermaid" in page_body
    assert "math" in page_body
    assert page["Cache-Control"] == "private, no-store"
    assert str(tmp_path) not in page_body

    slides = render_document(
        request_factory.get("/?embed=1"), markdown_path=note, url_prefix=_prefix(), mode="slides"
    )
    slides_body = slides.content.decode()
    assert slides.status_code == 200
    assert slides_body.count("<section") == 2
    assert "embed" in slides_body
    assert str(tmp_path) not in slides_body

    payload = render_slides_payload(request_factory.get("/"), markdown_path=note, url_prefix=_prefix())
    assert payload.status_code == 200
    payload_data = json.loads(payload.content)
    assert payload_data["sourcePath"] == "Deck.md"
    assert len(payload_data["slides"]) == 2
    assert payload["Cache-Control"] == "private, no-store"

    assert get_template("vaultpub/page.html")
    assert get_template("vaultpub/slides.html")
    assert finders.find("vaultpub/slides.js")
    assert finders.find("vaultpub/assets/mermaid.core-19PqGS39.js")


@pytest.mark.django_db
def test_referenced_resource_is_streamed_cold_and_cleanup_keeps_handle_readable(
    vaultpub_enabled, request_factory, tmp_path
):
    note = _document(tmp_path)

    response = serve_document_resource(
        request_factory.get("/"), markdown_path=note, url_prefix=_prefix(), resource_path="image.png"
    )
    try:
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == b"PNG bytes"
        assert response["Cache-Control"] == "private, no-store"
    finally:
        response.close()


@pytest.mark.parametrize(
    "resource_path",
    ["unreferenced.png", "Other.md", "nested/image.png", "../image.png", "/image.png", ""],
)
def test_resource_scope_rejects_unreferenced_or_non_sibling_files(
    vaultpub_enabled, request_factory, tmp_path, resource_path
):
    note = _document(tmp_path)
    (tmp_path / "unreferenced.png").write_bytes(b"not referenced")
    (tmp_path / "Other.md").write_text("# private", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "image.png").write_bytes(b"nested")

    with pytest.raises(Http404):
        serve_document_resource(
            request_factory.get("/"), markdown_path=note, url_prefix=_prefix(), resource_path=resource_path
        )


def test_resource_scope_rejects_symlink_escape(vaultpub_enabled, request_factory, tmp_path):
    note = _document(tmp_path)
    outside = tmp_path.parent / "outside-document-resource.png"
    outside.write_bytes(b"outside")
    link = tmp_path / "escape.png"
    link.symlink_to(outside)
    note.write_text("# Deck\n\n![escape](escape.png)\n", encoding="utf-8")

    with pytest.raises(Http404):
        serve_document_resource(
            request_factory.get("/"), markdown_path=note, url_prefix=_prefix(), resource_path="escape.png"
        )


def test_excluded_note_and_invalid_inputs_do_not_widen_scope(vaultpub_enabled, request_factory, tmp_path):
    excluded = _document(tmp_path, "Excluded.md", "---\npublish: false\n---\n# hidden")
    request = request_factory.get("/")

    with pytest.raises(Http404):
        render_document(request, markdown_path=excluded, url_prefix=_prefix())
    with pytest.raises(ValueError):
        render_document(request, markdown_path=Path("Deck.md"), url_prefix=_prefix())
    with pytest.raises(ValueError):
        render_document(request, markdown_path=excluded, url_prefix="https://bad.example/documents/")
    with pytest.raises(ValueError):
        render_document(request, markdown_path=excluded, url_prefix="/documents/../escape/")
    with pytest.raises(ValueError):
        render_document(request, markdown_path=excluded, url_prefix=_prefix(), mode="other")
    with pytest.raises(ValueError):
        render_document(request, markdown_path=excluded, url_prefix=_prefix(), mode=[])


@pytest.mark.parametrize("url_prefix", ["/documents/%00/", "/documents/%5cescape/"])
def test_url_prefix_rejects_encoded_unsafe_characters(
    vaultpub_enabled, request_factory, tmp_path, url_prefix
):
    note = _document(tmp_path)
    with pytest.raises(ValueError):
        render_document(request_factory.get("/"), markdown_path=note, url_prefix=url_prefix)


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_only_get_and_head_are_allowed(vaultpub_enabled, request_factory, tmp_path, method):
    note = _document(tmp_path)
    response = render_document(getattr(request_factory, method.lower())("/"), markdown_path=note, url_prefix=_prefix())
    assert response.status_code == 405
    assert response["Allow"] == "GET, HEAD"


def test_document_state_is_isolated_repeated_and_cleaned(vaultpub_enabled, request_factory, tmp_path, monkeypatch):
    first = _document(tmp_path, "First.md", "# first\n\n![first](first.png)")
    second = _document(tmp_path, "Second.md", "# second\n\n![second](second.png)")
    (tmp_path / "first.png").write_bytes(b"first")
    (tmp_path / "second.png").write_bytes(b"second")
    from vaultpub.core.config import PublisherConfig
    from vaultpub.django_app import views

    host_key = "host-unrelated-state"
    views.build_state_for_config(PublisherConfig(vault_path=tmp_path), cache_key=host_key)
    cleared: list[str | None] = []
    real_clear = views.clear_state_cache

    def recording_clear(key=None):
        cleared.append(key)
        return real_clear(key)

    monkeypatch.setattr(views, "clear_state_cache", recording_clear)
    first_html = render_document(
        request_factory.get("/"), markdown_path=first, url_prefix=_prefix(), mode="note"
    ).content
    second_html = render_document(
        request_factory.get("/"), markdown_path=second, url_prefix=_prefix(), mode="note"
    ).content
    first.write_text("# first revised\n\n![first](first.png)", encoding="utf-8")
    first_changed = render_document(
        request_factory.get("/"), markdown_path=first, url_prefix=_prefix(), mode="note"
    ).content

    assert b"first" in first_html and b"second" not in first_html
    assert b"second" in second_html and b"first" not in second_html
    assert b"first revised" in first_changed and first_changed != first_html
    assert cleared and all(key and key.startswith("liveclassroom.document.") for key in cleared)
    assert host_key in views._state_cache
    real_clear(host_key)


def test_failure_clears_only_its_generated_key(vaultpub_enabled, request_factory, tmp_path, monkeypatch):
    note = _document(tmp_path)
    from vaultpub.django_app import views

    cleared: list[str | None] = []
    real_clear = views.clear_state_cache
    monkeypatch.setattr(
        views, "clear_state_cache", lambda key=None: (cleared.append(key), real_clear(key))[1]
    )
    monkeypatch.setattr(
        views,
        "render_slides_with_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        render_document(request_factory.get("/"), markdown_path=note, url_prefix=_prefix())
    assert len(cleared) == 1
    assert cleared[0] and cleared[0].startswith("liveclassroom.document.")


def test_missing_capability_has_a_concise_error(monkeypatch, request_factory, tmp_path):
    note = _document(tmp_path)
    monkeypatch.setattr(
        vaultpub_documents,
        "_vaultpub_api",
        lambda: (_ for _ in ()).throw(
            VaultPubUnavailable("Installed VaultPub lacks the required document-rendering APIs.")
        ),
    )
    with pytest.raises(VaultPubUnavailable, match="required document-rendering APIs"):
        render_document(request_factory.get("/"), markdown_path=note, url_prefix=_prefix())
