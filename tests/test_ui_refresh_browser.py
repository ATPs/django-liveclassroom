"""Browser acceptance for the compact shell and teacher-session ribbon."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.services.classroom import create_activity_definition, create_instant_session, start_session
from liveclassroom.services.flows import add_flow_step, create_flow
from tests.test_browser_workflows import _chromium_or_skip


@pytest.mark.django_db(transaction=True)
def test_teacher_console_uses_compact_shell_actions_and_responses_ribbon(live_server):
    teacher = get_user_model().objects.create_user(username="ui-refresh-teacher", password="password")
    session = create_instant_session(owner=teacher, title="UI refresh classroom")
    start_session(session=session, actor=teacher)
    client = Client()
    client.force_login(teacher)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        posts: list[str] = []
        page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
        page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-console', args=[session.id])}?panel=current")
        slot = page.locator("#lc-session-action-slot")
        slot.get_by_role("button", name="Pause").wait_for()
        page.wait_for_function("new URL(window.location.href).searchParams.get('panel') === 'responses'")
        assert slot.get_by_role("link", name="Student view").get_attribute("target") == "_blank"
        header_box = page.locator(".lc-shell-header").bounding_box()
        slot_box = slot.bounding_box()
        utilities_box = page.locator("[data-liveclassroom-shell-header-utilities] .lc-shell-header-actions").bounding_box()
        assert header_box and slot_box and utilities_box
        assert header_box["height"] <= 48
        # Global utilities sit after the identity; classroom actions stay as
        # the final right-aligned group for quick access during teaching.
        assert slot_box["x"] >= utilities_box["x"] + utilities_box["width"] + 4
        assert slot_box["x"] + slot_box["width"] >= header_box["x"] + header_box["width"] - 12
        page.set_viewport_size({"width": 1024, "height": 768})
        tablet_overflow = page.evaluate("""() => ({
          width: document.documentElement.scrollWidth,
          viewport: window.innerWidth,
          headerRight: document.querySelector('.lc-shell-header-right')?.getBoundingClientRect().right,
        })""")
        assert tablet_overflow["width"] <= tablet_overflow["viewport"], tablet_overflow
        assert tablet_overflow["headerRight"] >= tablet_overflow["viewport"] - 24
        page.screenshot(path=".local/screenshots/2026-09-16-ui-refresh-teacher-tablet.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 900})
        next_toggle = page.get_by_role("button", name="Hide next item")
        next_toggle.click()
        assert not page.locator("#lc-presenter-next").is_visible()
        page.get_by_role("button", name="Show next item").click()
        assert page.locator("#lc-presenter-next").is_visible()
        invite = slot.get_by_role("button", name="Invite students")
        invite.click()
        popover = page.get_by_role("dialog", name="Invite students")
        assert popover.is_visible()
        assert popover.locator(".lc-btn").count() == 4
        assert popover.evaluate("node => Math.abs(node.querySelector('.lc-btn').getBoundingClientRect().height - node.querySelectorAll('.lc-btn')[1].getBoundingClientRect().height) <= 1")
        page.keyboard.press("Escape")
        assert not popover.is_visible()
        assert invite.evaluate("node => document.activeElement === node")
        assert page.locator(".lc-session-command-bar #session-status").count() == 0
        responses = page.locator("#console-panel-responses")
        assert responses.is_visible()
        assert responses.get_by_role("heading", name="Responses").is_visible()
        page.get_by_role("tab", name="Results", exact=True).click()
        page.wait_for_function("new URL(window.location.href).searchParams.get('panel') === 'results'")
        assert posts == []
        page.locator(".lc-shell-sidebar-toggle").click()
        page.wait_for_function("document.querySelector('[data-classroom-shell]')?.dataset.sidebar === 'collapsed'")
        assert page.locator(".lc-shell-compact-group .lc-shell-link").count() > 4
        assert page.locator(".lc-shell-compact-group .lc-shell-link").first.get_attribute("aria-label")
        page.locator(".lc-shell-compact-group .lc-shell-link").first.hover()
        tooltip = page.get_by_role("tooltip")
        assert tooltip.is_visible()
        page.keyboard.press("Escape")
        assert not tooltip.is_visible()
        collapse = page.locator(".lc-shell-sidebar-toggle")
        assert collapse.inner_text() == ""
        box = collapse.bounding_box()
        assert box and box["width"] <= 34 and box["height"] <= 34
        assert page.locator(".lc-shell-header").evaluate("node => getComputedStyle(node).borderBottomWidth") == "0px"
        assert collapse.evaluate("node => getComputedStyle(node).borderTopWidth") == "0px"
        assert page.locator(".lc-shell-sidebar").evaluate("node => getComputedStyle(node).backgroundColor") == "rgba(0, 0, 0, 0)"
        page.screenshot(path=".local/screenshots/2026-09-16-ui-refresh-teacher-final.png", full_page=True)
        page.locator(".lc-shell-sidebar-toggle").click()
        page.wait_for_function("document.querySelector('[data-classroom-shell]')?.dataset.sidebar === 'expanded'")
        assert slot.get_by_role("button", name="Pause").is_visible()
        page.locator("[data-audience='teacher']").evaluate("element => element.dispatchEvent(new Event('liveclassroom:unmount'))")
        page.wait_for_function("document.querySelector('#lc-session-action-slot')?.childElementCount === 0")
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_student_surface_has_no_mobile_overflow(live_server):
    teacher = get_user_model().objects.create_user(username="ui-refresh-student", password="password")
    session = create_instant_session(owner=teacher, title="Mobile UI classroom")
    start_session(session=session, actor=teacher)
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"{live_server.url}{reverse('liveclassroom:student-session', args=[session.id])}")
        page.locator("[data-liveclassroom-join-prompt] input").fill("Ada")
        page.get_by_role("button", name="Join classroom").click()
        page.wait_for_function("document.querySelector('[data-liveclassroom-join-prompt]') === null")
        overflow = page.evaluate("""() => ({
          width: document.documentElement.scrollWidth,
          viewport: window.innerWidth,
          elements: [...document.querySelectorAll('*')].filter((node) => {
            const box = node.getBoundingClientRect();
            return box.right > window.innerWidth + 1 || box.left < -1;
          }).map((node) => `${node.tagName}.${node.className}`).slice(0, 10),
        })""")
        assert overflow["width"] <= overflow["viewport"], overflow
        page.set_viewport_size({"width": 320, "height": 844})
        narrow_overflow = page.evaluate("""() => ({
          width: document.documentElement.scrollWidth,
          viewport: window.innerWidth,
        })""")
        assert narrow_overflow["width"] <= narrow_overflow["viewport"], narrow_overflow
        page.screenshot(path="/tmp/liveclassroom-student-320.png", full_page=True)
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_teacher_console_uses_chinese_dark_theme(live_server):
    teacher = get_user_model().objects.create_user(username="ui-refresh-dark-teacher", password="password")
    session = create_instant_session(owner=teacher, title="深色课堂")
    start_session(session=session, actor=teacher)
    client = Client()
    client.force_login(teacher)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.emulate_media(color_scheme="dark")
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-console', args=[session.id])}?lang=zh-Hans")
        slot = page.locator("#lc-session-action-slot")
        slot.get_by_text("课堂进行中", exact=True).wait_for()
        page.get_by_role("tab", name="答题情况", exact=True).wait_for()
        assert page.locator("#liveclassroom-root").evaluate("node => getComputedStyle(node).getPropertyValue('--lc-bg').trim()") == "#191c1a"
        page.screenshot(path="/tmp/liveclassroom-teacher-dark-zh.png", full_page=True)
        page.set_viewport_size({"width": 720, "height": 900})
        page.wait_for_function("document.querySelector('.lc-shell-header')?.getBoundingClientRect().height > 44")
        narrow_overflow = page.evaluate("""() => ({
          width: document.documentElement.scrollWidth,
          viewport: window.innerWidth,
        })""")
        assert narrow_overflow["width"] <= narrow_overflow["viewport"], narrow_overflow
        page.screenshot(path="/tmp/liveclassroom-teacher-dark-zh-720.png", full_page=True)
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_classroom_display_keeps_long_titles_and_utilities_readable(live_server):
    teacher = get_user_model().objects.create_user(username="ui-refresh-display", password="password")
    session = create_instant_session(
        owner=teacher,
        title="Long bilingual classroom title for a projector display with enough words to verify safe wrapping 长标题课堂展示",
    )
    start_session(session=session, actor=teacher)
    client = Client()
    client.force_login(teacher)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:classroom-display', args=[session.id])}")
        title = page.locator("#display-title")
        title.wait_for()
        toolbar = page.locator(".lc-display-toolbar")
        toolbar.get_by_role("button", name="Fullscreen", exact=True).wait_for()
        assert toolbar.locator(".lc-lang-switch").evaluate("node => getComputedStyle(node).position") == "static"
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=".local/screenshots/2026-09-16-ui-refresh-display-desktop.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert title.evaluate("node => node.getBoundingClientRect().width <= window.innerWidth")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=".local/screenshots/2026-09-16-ui-refresh-display-mobile.png", full_page=True)
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_flow_builder_switches_regions_without_losing_an_unsaved_draft(live_server):
    teacher = get_user_model().objects.create_user(username="ui-refresh-builder", password="password")
    flow = create_flow(title="Responsive lesson", creator=teacher)
    definition = create_activity_definition(
        owner=teacher,
        title="Existing preview activity",
        type_key="liveclassroom.markdown",
        definition={"markdown": "# Existing preview"},
    )
    add_flow_step(flow=flow, actor=teacher, activity_definition=definition)
    client = Client()
    client.force_login(teacher)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:flow-builder-detail', args=[flow.id])}")
        page.get_by_role("heading", name="Responsive lesson", exact=True).wait_for()
        layout = page.locator(".lc-builder-layout")
        outline = page.locator(".lc-builder-outline")
        main = page.locator(".lc-builder-main")
        preview = page.locator(".lc-builder-sidebar")
        assert outline.is_visible() and main.is_visible() and preview.is_visible()
        assert preview.bounding_box()["x"] > main.bounding_box()["x"]

        page.set_viewport_size({"width": 1024, "height": 768})
        tabs = page.locator(".lc-builder-view-tabs")
        assert tabs.is_visible() and outline.is_visible() and main.is_visible()
        assert not preview.is_visible()
        tabs.get_by_role("button", name="Preview", exact=True).click()
        assert layout.get_attribute("data-editor-view") == "preview"
        assert outline.is_visible() and preview.is_visible() and not main.is_visible()
        tabs.get_by_role("button", name="Edit", exact=True).click()
        assert main.is_visible() and not preview.is_visible()

        page.set_viewport_size({"width": 390, "height": 844})
        tabs.get_by_role("button", name="Outline", exact=True).click()
        assert outline.is_visible() and not main.is_visible() and not preview.is_visible()
        tabs.get_by_role("button", name="Edit", exact=True).click()
        page.get_by_role("button", name="Add step", exact=False).click()
        draft = page.locator(".lc-builder-step-form input").first
        draft.fill("Retained responsive draft")
        tabs.get_by_role("button", name="Preview", exact=True).click()
        assert preview.is_visible() and not main.is_visible()
        tabs.get_by_role("button", name="Edit", exact=True).click()
        assert draft.input_value() == "Retained responsive draft"

        page.set_viewport_size({"width": 320, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        browser.close()
        manager.stop()
