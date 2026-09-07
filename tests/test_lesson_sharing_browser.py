"""Browser acceptance for named lesson sharing and independent copies."""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import Flow, FlowShare
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.flows import add_flow_step, create_flow
from tests.test_browser_workflows import _chromium_or_skip, database_call


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


@pytest.mark.django_db(transaction=True)
def test_named_lesson_sharing_preview_and_independent_copy(live_server):
    users = get_user_model()
    teacher_a = users.objects.create_user(username="sharing-browser-a", password="password")
    teacher_b = users.objects.create_user(username="sharing-browser-b", password="password")
    lesson = create_flow(title="Shared biology lesson", creator=teacher_a)
    definition = create_activity_definition(
        owner=teacher_a,
        title="Cell prompt",
        type_key="liveclassroom.short_text",
        definition={"prompt": "What is the role of the cell membrane?"},
    )
    add_flow_step(flow=lesson, actor=teacher_a, activity_definition=definition)
    teacher_a_cookie = _session_cookie(teacher_a)
    teacher_b_cookie = _session_cookie(teacher_b)

    manager, browser = _chromium_or_skip()
    try:
        teacher_a_page = browser.new_page(viewport={"width": 1440, "height": 900})
        teacher_a_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": teacher_a_cookie, "url": live_server.url}]
        )
        workspace_url = reverse("liveclassroom:api-v1-workspace")
        flows_url = reverse("liveclassroom:api-v1-flows")
        with teacher_a_page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(workspace_url)
        ), teacher_a_page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(flows_url)
        ):
            teacher_a_page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-dashboard')}")
        teacher_a_page.get_by_role("heading", name="Teacher workspace", exact=True).wait_for()

        lesson_card = teacher_a_page.locator(".lc-workspace-item").filter(has_text=lesson.title).first
        lesson_card.get_by_role("button", name="Share", exact=True).click()
        share_panel = lesson_card.locator(".lc-workspace-share")
        share_panel.get_by_label("Share with username", exact=True).fill(teacher_b.username)
        share_url = reverse("liveclassroom:api-v1-flow-shares", args=[lesson.id])
        with teacher_a_page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(share_url)
        ) as share_response:
            share_panel.get_by_role("button", name="Share", exact=True).click()
        assert share_response.value.status == 200

        def assert_shared():
            assert FlowShare.objects.filter(flow=lesson, user=teacher_b).exists()

        database_call(assert_shared)

        teacher_b_page = browser.new_page(viewport={"width": 1440, "height": 900})
        teacher_b_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": teacher_b_cookie, "url": live_server.url}]
        )
        with teacher_b_page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(workspace_url)
        ), teacher_b_page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(flows_url)
        ):
            teacher_b_page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-dashboard')}")
        teacher_b_page.get_by_role("heading", name="Teacher workspace", exact=True).wait_for()
        teacher_b_page.get_by_role("button", name="Shared with me", exact=True).click()

        shared_card = teacher_b_page.locator(".lc-workspace-item").filter(has_text=lesson.title).first
        preview_url = reverse("liveclassroom:api-v1-flow-detail", args=[lesson.id])
        with teacher_b_page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(preview_url)
        ) as preview_response:
            shared_card.get_by_role("button", name="Preview", exact=True).click()
        assert preview_response.value.status == 200
        shared_card.locator(".lc-workspace-preview").get_by_text(
            "What is the role of the cell membrane?", exact=False
        ).wait_for()

        shared_card.get_by_role("button", name="Duplicate", exact=True).click()
        shared_card.get_by_label("New lesson title", exact=True).fill("B cell lesson copy")
        duplicate_url = reverse("liveclassroom:api-v1-flow-duplicate", args=[lesson.id])
        with teacher_b_page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(duplicate_url)
        ) as duplicate_response:
            shared_card.get_by_role("button", name="Create duplicate", exact=True).click()
        assert duplicate_response.value.status == 201
        teacher_b_page.screenshot(path="/tmp/liveclassroom-workspace-desktop.png", full_page=True)

        def assert_copy():
            copied = Flow.objects.get(title="B cell lesson copy", created_by=teacher_b)
            copied_step = copied.steps.select_related("activity_definition").get()
            assert copied.id != lesson.id
            assert copied_step.activity_definition.owner_id == teacher_b.id
            assert copied_step.activity_definition.definition == {"prompt": "What is the role of the cell membrane?"}

        database_call(assert_copy)

        teacher_b_page.set_viewport_size({"width": 390, "height": 844})
        assert teacher_b_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        language_box = teacher_b_page.locator(".lc-lang-switch").bounding_box()
        title_box = teacher_b_page.locator(".lc-kicker").bounding_box()
        assert language_box and title_box
        assert language_box["y"] + language_box["height"] <= title_box["y"]
        teacher_b_page.screenshot(path="/tmp/liveclassroom-workspace-mobile.png", full_page=True)
        teacher_b_page.locator(".lc-lang-switch").click()
        teacher_b_page.get_by_role("heading", name="\u6559\u5e08\u5de5\u4f5c\u53f0", exact=True).wait_for()
        assert teacher_b_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        teacher_b_page.screenshot(path="/tmp/liveclassroom-workspace-mobile-zh.png", full_page=True)
    finally:
        browser.close()
        manager.stop()
