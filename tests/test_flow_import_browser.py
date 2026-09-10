"""Real-browser coverage for lesson Markdown import and visible error recovery."""

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import Flow
from liveclassroom.services.flows import create_flow
from tests.test_browser_workflows import _chromium_or_skip, database_call


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


@pytest.mark.django_db(transaction=True)
def test_teacher_imports_markdown_and_sees_a_recoverable_import_error(live_server):
    """Use the mounted browser UI for both a valid import and a bad-input response."""
    teacher = get_user_model().objects.create_user(username="flow-import-browser", password="password")
    editable = create_flow(title="Import destination", creator=teacher)
    cookie = _session_cookie(teacher)
    screenshots = Path(".local/2026-09-09/screenshots/task49")
    screenshots.mkdir(parents=True, exist_ok=True)

    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:flow-builder-detail', args=[editable.id])}")
        page.get_by_role("heading", name="Import destination", exact=True).wait_for()

        page.get_by_role("button", name="Import content", exact=True).click()
        modal = page.locator("#lc-import-modal")
        modal.get_by_role("combobox").select_option("markdown")
        modal.locator("textarea").fill(
            "---\ntitle: Imported Markdown lesson\ndescription: Browser-created portable lesson\n---\n\n"
            "# Cells\n\nExplain the membrane."
        )
        import_url = reverse("liveclassroom:api-v1-flow-import")
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(import_url)
        ) as imported:
            modal.get_by_role("button", name="Import", exact=True).click()
        assert imported.value.status == 201
        page.locator("#lc-import-modal").wait_for(state="detached")
        page.get_by_role("heading", name="Imported Markdown lesson", exact=True).wait_for()
        assert database_call(
            lambda: Flow.objects.filter(created_by=teacher, title="Imported Markdown lesson").count()
        ) == 1
        page.screenshot(path=str(screenshots / "2026-09-10-flow-import-desktop.png"), full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="Import content", exact=True).click()
        modal = page.locator("#lc-import-modal")
        modal.get_by_role("combobox").select_option("json")
        modal.locator("textarea").fill("{")
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(import_url)
        ) as rejected:
            modal.get_by_role("button", name="Import", exact=True).click()
        assert rejected.value.status == 400
        modal.locator(".lc-form-error").wait_for()
        assert modal.locator("textarea").input_value() == "{"
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(screenshots / "2026-09-10-flow-import-error-mobile.png"), full_page=True)
        modal.get_by_role("button", name="Cancel", exact=True).click()
        modal.wait_for(state="detached")

    finally:
        browser.close()
        manager.stop()
