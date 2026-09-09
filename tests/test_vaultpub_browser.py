"""Browser evidence for the authorized VaultPub Markdown activity surface."""

from __future__ import annotations

import base64

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from liveclassroom.models import ActivityRunRevision, ClassroomAsset
from liveclassroom.services.classroom import (
    create_activity_definition,
    create_instant_session,
    launch_item,
    publish_activity_to_channel,
    start_session,
)
from tests.test_browser_workflows import _chromium_or_skip


@pytest.fixture
def vaultpub_apps():
    with override_settings(INSTALLED_APPS=[*settings.INSTALLED_APPS, "vaultpub.django_app"]):
        yield


def test_optional_standalone_profile_keeps_vaultpub_activation_explicit():
    from standalone.liveclassroom_site import settings as base_settings
    from standalone.liveclassroom_site import vaultpub_settings

    assert "vaultpub.django_app" not in base_settings.INSTALLED_APPS
    assert "vaultpub.django_app" in vaultpub_settings.INSTALLED_APPS


@pytest.mark.django_db(transaction=True)
def test_vaultpub_markdown_activity_browser_and_raw_fallback(live_server, tmp_path, vaultpub_apps):
    """A permitted participant gets the full renderer and a missing renderer falls back."""
    teacher = get_user_model().objects.create_user(username="vaultpub-browser-teacher", password="password")
    session = create_instant_session(owner=teacher, title="VaultPub browser classroom")
    start_session(session=session, actor=teacher)

    note = tmp_path / "teaching.md"
    note.write_text(
        """# First slide

| Item | Value |
| --- | --- |
| table | rendered |

![A local image](pixel.png)

$$x^2 + y^2$$

```mermaid
graph TD
  A[One] --> B[Two]
```

> [!note] Callout
> Rendered by VaultPub.

<!-- Speaker note: explain the relationship before advancing. -->

---

# Second slide

The second section is visible after navigation.
""",
        encoding="utf-8",
    )
    # A real, tiny image makes the browser check image loading rather than only
    # checking for an image tag.  It is kept as a sibling of the selected note.
    (tmp_path / "pixel.png").write_bytes(
        base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    )
    asset = ClassroomAsset.objects.create(
        owner=teacher,
        source=ClassroomAsset.Source.SERVER_PATH,
        server_path=str(note),
        original_name=note.name,
        kind=ClassroomAsset.Kind.MARKDOWN,
        content_type="text/markdown; charset=utf-8",
        byte_size=note.stat().st_size,
    )
    definition = create_activity_definition(
        owner=teacher,
        title="VaultPub teaching material",
        type_key="liveclassroom.file",
        definition={
            "asset_id": str(asset.public_id),
            "file_kind": ClassroomAsset.Kind.MARKDOWN,
            "caption": "",
        },
        asset=asset,
    )
    activity = launch_item(session=session, item=definition, actor=teacher, channel="participants")
    publish_activity_to_channel(session=session, activity=activity, channel="display", actor=teacher)
    revision = ActivityRunRevision.objects.get(activity=activity, asset=asset)
    document_url = reverse(
        "liveclassroom:api-v1-session-document-root",
        args=[session.id, revision.id, asset.public_id],
    )
    slides_url = reverse(
        "liveclassroom:api-v1-session-document-slides",
        args=[session.id, revision.id, asset.public_id, asset.original_name],
    )

    manager, browser = _chromium_or_skip()
    try:
        from playwright.sync_api import expect

        page = browser.new_page(viewport={"width": 390, "height": 844})
        # A normal browser navigation establishes the session cookie; joining
        # through the UI below then associates it with this participant.
        page.goto(f"{live_server.url}{reverse('liveclassroom:student-session', args=[session.id])}")
        page.locator("[data-liveclassroom-join-prompt] input").fill("Browser reader")
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(reverse("liveclassroom:api-v1-join", args=[session.join_code]))
        ) as joined:
            page.get_by_role("button", name="Join classroom", exact=True).click()
        assert joined.value.status == 201

        frame = page.locator("iframe.lc-file-vaultpub-frame")
        frame.wait_for()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.get_by_role("button", name="Slide view", exact=True).is_visible()
        assert page.get_by_role("button", name="Note view", exact=True).is_visible()
        assert frame.get_attribute("src").endswith(f"{slides_url}?embed=1")

        slide_frame = page.frame_locator("iframe.lc-file-vaultpub-frame")
        slide_frame.locator("section.vaultpub-slide").first.wait_for()
        assert slide_frame.locator("section.vaultpub-slide").count() == 2
        assert slide_frame.locator("table").count() >= 1
        assert slide_frame.locator("img").count() >= 1
        assert slide_frame.locator(".callout").count() >= 1
        assert slide_frame.locator(".mermaid").count() >= 1
        # VaultPub loads KaTeX dynamically after the slide shell is mounted.
        # Wait for the rendered node instead of racing that optional module.
        slide_frame.locator(".katex").first.wait_for()
        assert slide_frame.locator(".katex").count() >= 1

        page.get_by_role("button", name="Next page", exact=True).click()
        expect(slide_frame.locator("section.vaultpub-slide.present h1")).to_contain_text("Second slide")

        page.get_by_role("button", name="Note view", exact=True).click()
        page.wait_for_function(
            "(url) => document.querySelector('iframe.lc-file-vaultpub-frame')?.src === url",
            arg=f"{live_server.url}{document_url}",
        )
        note_frame = page.frame_locator("iframe.lc-file-vaultpub-frame")
        note_frame.locator("table").first.wait_for()
        assert note_frame.locator("h1").first.inner_text() == "First slide"

        # Route-level authorization still applies to the opaque URL.  A fresh
        # context has no participant cookie and must receive a 404.
        anonymous_context = browser.new_context()
        try:
            denied = anonymous_context.request.get(f"{live_server.url}{document_url}")
            assert denied.status == 404
        finally:
            anonymous_context.close()

        # Simulate VaultPub being absent/unavailable at the capability probe.
        # The file renderer must retain the existing raw Markdown path.  Keep
        # this in the joined tab because the application intentionally uses one
        # idempotency key per browser session for guest entry.
        page.route(
            f"**{slides_url}*",
            lambda route: route.fulfill(status=503, body="Document rendering is unavailable."),
        )
        page.reload()
        page.locator(".lc-markdown-body").wait_for()
        assert page.locator(".lc-markdown-body h1").count() >= 1
        assert page.locator("iframe.lc-file-vaultpub-frame").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        browser.close()
        manager.stop()
