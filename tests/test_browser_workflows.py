"""Optional real-browser acceptance checks for package-owned teaching surfaces."""

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.services.classroom import create_instant_session, start_session


def _chromium_or_skip():
    sync_api = pytest.importorskip("playwright.sync_api")
    manager = sync_api.sync_playwright().start()
    try:
        if not Path(manager.chromium.executable_path).is_file():
            pytest.skip("Playwright Chromium is not installed")
        return manager, manager.chromium.launch()
    except Exception:
        manager.stop()
        pytest.skip("Playwright Chromium cannot launch in this environment")


@pytest.mark.django_db(transaction=True)
def test_student_join_and_teacher_console_render_without_mobile_overflow(live_server):
    teacher = get_user_model().objects.create_user(username="browser-teacher", password="password")
    session = create_instant_session(owner=teacher, title="Browser classroom")
    start_session(session=session, actor=teacher)
    client = Client()
    client.force_login(teacher)
    teacher_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    browser_manager, browser = _chromium_or_skip()
    try:
        student = browser.new_page(viewport={"width": 390, "height": 844})
        student.goto(f"{live_server.url}{reverse('liveclassroom:student-session', args=[session.id])}")
        student.locator("[data-liveclassroom-join-prompt] input").fill("Ada")
        with student.expect_response(
            lambda response: response.url.endswith(reverse("liveclassroom:api-v1-join", args=[session.join_code]))
        ) as joined_response, student.expect_response(
            lambda response: response.url.endswith(
                f"{reverse('liveclassroom:api-v1-state', args=[session.id])}?channel=participants"
            )
        ) as state_response:
            student.get_by_role("button", name="Join classroom").click()
        assert joined_response.value.status == 201
        assert state_response.value.status == 200
        student.wait_for_function("document.querySelector('[data-liveclassroom-join-prompt]') === null")
        student.wait_for_function("document.querySelector('#student-title')?.textContent === 'Browser classroom'")
        assert student.locator("#student-title").inner_text() == "Browser classroom"
        assert student.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        student.screenshot(path="/tmp/liveclassroom-student-mobile.png", full_page=True)

        teacher_page = browser.new_page(viewport={"width": 1440, "height": 900})
        teacher_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": teacher_cookie, "url": live_server.url}]
        )
        teacher_page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-console', args=[session.id])}")
        assert teacher_page.locator("[data-audience='teacher']").is_visible()
        assert teacher_page.locator(".lc-join-qr img").is_visible()
        teacher_page.screenshot(path="/tmp/liveclassroom-teacher-desktop.png", full_page=True)
    finally:
        browser.close()
        browser_manager.stop()
