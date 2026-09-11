from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import ActivityDefinition, AssessmentDefinition, Deck
from tests.test_browser_workflows import _chromium_or_skip, database_call


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


@pytest.mark.django_db(transaction=True)
def test_teacher_previews_and_commits_question_deck_and_assessment_imports(live_server):
    teacher = get_user_model().objects.create_user(username="markdown-import-browser", password="password")
    # Create the Django session before Playwright's synchronous bridge starts
    # its event loop; otherwise Django correctly rejects this database call.
    cookie = _session_cookie(teacher)
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        page.goto(f"{live_server.url}{reverse('liveclassroom:assessment-workspace')}")
        page.get_by_role("heading", name="Import Markdown or YAML", exact=True).wait_for()
        source = page.get_by_label("Source", exact=True)
        filename = page.get_by_label("File name", exact=True)
        cases = [
            (
                "question.yaml",
                "kind: question\ntitle: Imported question\ntype: markdown\nmarkdown: Hello\n",
                ActivityDefinition,
                "Imported question",
            ),
            (
                "deck.yaml",
                "kind: deck\ntitle: Imported deck\nslides:\n  - markdown: '# Slide'\n",
                Deck,
                "Imported deck",
            ),
            (
                "assessment.yaml",
                (
                    "kind: assessment\ntitle: Imported assessment\nitems:\n  - type: single_choice\n"
                    "    title: Item\n    definition:\n      prompt: Pick one\n      options:\n"
                    "        - id: A\n          text: Yes\n        - id: B\n          text: No\n"
                    "      answer: A\n    points: '1'\n"
                ),
                AssessmentDefinition,
                "Imported assessment",
            ),
        ]
        for name, document, model, title in cases:
            filename.fill(name)
            source.fill(document)
            page.get_by_role("button", name="Preview import", exact=True).click()
            ready = page.get_by_text("Ready to import", exact=False)
            ready.wait_for()
            page.get_by_role("button", name="Create copy", exact=True).click()
            # Commit clears its preview only after its response completes, so
            # this remains a visible browser synchronization point rather
            # than racing the asynchronous POST with a direct DB assertion.
            ready.wait_for(state="detached")
            assert database_call(lambda: model.objects.filter(owner=teacher, title=title).exists())
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(Path('.local/screenshots/2026-09-10-markdown-import-mobile.png')), full_page=True)
    finally:
        browser.close()
        manager.stop()
