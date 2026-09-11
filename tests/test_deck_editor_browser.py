import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from tests.test_browser_workflows import _chromium_or_skip, database_call


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


@pytest.mark.django_db(transaction=True)
def test_teacher_creates_reorders_and_saves_deck_on_mobile(live_server):
    teacher = get_user_model().objects.create_user(username="deck-browser-owner", password="password")
    cookie = _session_cookie(teacher)
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        page.goto(f"{live_server.url}{reverse('liveclassroom:deck-workspace')}")
        page.get_by_role("button", name="New deck", exact=True).click()
        page.get_by_label("Title", exact=True).fill("Cell biology")
        page.get_by_label("Markdown", exact=True).fill("# Intro")
        page.get_by_role("button", name="Add slide", exact=True).click()
        page.get_by_label("Markdown", exact=True).fill("# Figure")
        page.get_by_role("button", name="Move up", exact=True).click()
        page.get_by_role("button", name="Save", exact=True).click()
        page.get_by_text("Deck saved.", exact=True).wait_for()
        assert database_call(
            lambda: list(
                teacher.liveclassroom_decks.filter(title="Cell biology").values_list("slides__markdown", flat=True)
                .order_by("slides__position")
            )
        ) == ["# Figure", "# Intro"]
        overflow = page.evaluate(
            """[...document.querySelectorAll('*')].some((el) => el.getBoundingClientRect().right > innerWidth + 1)"""
        )
        assert not overflow
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_second_stage_deck_save_failure_keeps_the_draft_retryable(live_server):
    teacher = get_user_model().objects.create_user(username="deck-browser-retry", password="password")
    cookie = _session_cookie(teacher)
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page()
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:deck-workspace')}")
        page.get_by_role("button", name="New deck", exact=True).click()
        page.get_by_label("Title", exact=True).fill("Retry deck")
        page.get_by_label("Markdown", exact=True).fill("# Retained")
        page.get_by_role("button", name="Save", exact=True).click()
        page.get_by_text("Deck saved.", exact=True).wait_for()
        page.get_by_label("Title", exact=True).fill("Retry deck updated")
        page.get_by_label("Markdown", exact=True).fill("# Still retained")
        failed = {"value": False}

        def reject_once(route):
            if not failed["value"]:
                failed["value"] = True
                route.fulfill(status=500, content_type="application/json", body='{"detail":"storage failed"}')
            else:
                route.continue_()

        page.route("**/slides/", reject_once)
        page.get_by_role("button", name="Save", exact=True).click()
        page.get_by_text("Details saved, but slides are still local.", exact=False).wait_for()
        page.unroute("**/slides/", reject_once)
        page.get_by_role("button", name="Save", exact=True).click()
        page.get_by_text("Deck saved.", exact=True).wait_for()
        assert database_call(lambda: teacher.liveclassroom_decks.filter(title="Retry deck updated").count()) == 1
    finally:
        browser.close()
        manager.stop()
