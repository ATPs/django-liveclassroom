"""Teacher browser coverage for the question-bank workspace and picker."""

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.flows import create_flow
from liveclassroom.services.question_banks import add_question_to_bank, create_question_bank
from tests.test_browser_workflows import _chromium_or_skip


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


@pytest.mark.django_db(transaction=True)
def test_teacher_finds_previews_copies_and_picks_question(live_server):
    teacher = get_user_model().objects.create_user(username="question-bank-browser", password="password")
    question = create_activity_definition(
        owner=teacher,
        title="RNA transcription",
        type_key="liveclassroom.single_choice",
        definition={
            "prompt": "Which molecule carries the code?",
            "options": [{"id": "A", "text": "RNA"}, {"id": "B", "text": "ATP"}],
            "answer": "A",
        },
        metadata={"topic": "Biology", "tags": ["rna"]},
    )
    bank = create_question_bank(actor=teacher, data={"title": "Biology"})
    add_question_to_bank(actor=teacher, bank=bank, definition=question)
    lesson = create_flow(title="Question picker lesson", creator=teacher)
    cookie = _session_cookie(teacher)
    manager, browser = _chromium_or_skip()
    screenshots = Path(".local/screenshots")
    screenshots.mkdir(parents=True, exist_ok=True)
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-dashboard')}")
        page.get_by_role("heading", name="Teacher workspace", exact=True).wait_for()
        page.get_by_role("button", name="Question bank", exact=True).click()
        page.get_by_role("heading", name="Question bank workspace", exact=True).wait_for()
        page.locator(".lc-question-bank-item").filter(has_text="Biology").click()
        page.get_by_role("heading", name="RNA transcription", exact=True).wait_for()
        page.get_by_role("button", name="Preview", exact=True).click()
        page.get_by_text("Answer (teacher only)", exact=False).wait_for()
        page.once("dialog", lambda dialog: dialog.accept("RNA transcription copy"))
        page.get_by_role("button", name="Copy", exact=True).click()
        page.get_by_role("heading", name="RNA transcription copy", exact=True).wait_for()

        page.goto(f"{live_server.url}{reverse('liveclassroom:flow-builder')}?flow_id={lesson.id}")
        page.get_by_role("heading", name="Visual Lesson Builder", exact=True).wait_for()
        page.get_by_role("button", name="Add from question bank", exact=True).click()
        page.get_by_role("button", name="Use in lesson", exact=True).first.click()
        page.get_by_text("Question added to lesson.", exact=True).wait_for()
        page.screenshot(path=str(screenshots / "2026-09-09-question-bank-workspace-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        browser.close()
        manager.stop()
