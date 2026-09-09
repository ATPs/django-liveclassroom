"""Teacher browser coverage for the fixed-question assessment builder."""

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.question_banks import add_question_to_bank, create_question_bank
from tests.test_browser_workflows import _chromium_or_skip, database_call


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


@pytest.mark.django_db(transaction=True)
def test_teacher_builds_reopens_previews_and_copies_fixed_assessment(live_server):
    teacher = get_user_model().objects.create_user(username="assessment-browser", password="password")
    first = create_activity_definition(
        owner=teacher,
        title="DNA base",
        type_key="liveclassroom.single_choice",
        definition={
            "prompt": "Which base pairs with A?",
            "options": [{"id": "A", "text": "T"}, {"id": "B", "text": "C"}],
            "answer": "A",
        },
    )
    second = create_activity_definition(
        owner=teacher,
        title="Cell prompt",
        type_key="liveclassroom.short_text",
        definition={"prompt": "Name the cell powerhouse.", "answer": ["mitochondria"]},
    )
    bank = create_question_bank(actor=teacher, data={"title": "Biology"})
    add_question_to_bank(actor=teacher, bank=bank, definition=first)
    add_question_to_bank(actor=teacher, bank=bank, definition=second)
    cookie = _session_cookie(teacher)
    manager, browser = _chromium_or_skip()
    screenshots = Path(".local/screenshots")
    screenshots.mkdir(parents=True, exist_ok=True)
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:assessment-workspace')}")
        page.get_by_role("heading", name="Assessment builder", exact=True).wait_for()
        page.get_by_role("button", name="New assessment", exact=True).click()
        page.get_by_label("Title", exact=True).fill("Cell quiz")
        page.get_by_label("Instructions", exact=True).fill("Answer both questions.")
        page.get_by_role("button", name="Add questions", exact=True).click()
        page.locator(".lc-question-bank-item").filter(has_text="Biology").click()
        page.get_by_role("button", name="Add to assessment", exact=True).nth(0).click()
        page.get_by_role("button", name="Add questions", exact=True).click()
        page.locator(".lc-question-bank-item").filter(has_text="Biology").click()
        page.get_by_role("button", name="Add to assessment", exact=True).nth(1).click()
        page.get_by_label("Points for 1", exact=True).fill("3")
        page.get_by_label("Points for 2", exact=True).fill("4")
        page.get_by_role("button", name="Preview", exact=True).click()
        page.get_by_text("Answer (teacher only)", exact=False).first.wait_for()
        page.get_by_role("button", name="Save draft", exact=True).click()
        page.get_by_role("status").filter(has_text="Assessment saved.").wait_for()
        assert database_call(
            lambda: list(teacher.liveclassroom_assessments.values_list("title", flat=True))
        ) == ["Cell quiz"]
        page.locator(".lc-assessment-list-item").filter(has_text="Cell quiz").click()
        page.get_by_role("button", name="Copy", exact=True).click()
        page.get_by_text("Assessment copied.", exact=False).wait_for()
        page.screenshot(path=str(screenshots / "2026-09-10-assessment-builder-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.goto(f"{live_server.url}{reverse('liveclassroom:assessment-workspace')}?lang=zh-Hans")
        page.get_by_role("heading", name="测验编辑器", exact=True).wait_for()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(screenshots / "2026-09-10-assessment-builder-zh-mobile.png"), full_page=True)
    finally:
        browser.close()
        manager.stop()
