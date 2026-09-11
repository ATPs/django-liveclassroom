"""Browser-level URL and Back behavior for the navigation surfaces."""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import Course, CourseMembership, TeachingCourse
from liveclassroom.services.decks import create_deck
from tests.test_browser_workflows import _chromium_or_skip, database_call


def _cookie(user):
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


@pytest.mark.django_db(transaction=True)
def test_workspace_tabs_and_learner_courses_have_addressable_history(live_server):
    users = get_user_model()
    teacher = users.objects.create_user(username="navigation-browser-teacher", password="password")
    learner = users.objects.create_user(username="navigation-browser-learner", password="password")
    program = TeachingCourse.objects.create(title="Navigation Biology", created_by=teacher)
    cohort = Course.objects.create(
        title="Navigation cohort", slug="navigation-cohort", created_by=teacher, teaching_course=program
    )
    CourseMembership.objects.create(course=cohort, user=learner, role=CourseMembership.Role.STUDENT)
    teacher_cookie = database_call(lambda: _cookie(teacher))
    learner_cookie = database_call(lambda: _cookie(learner))
    manager, browser = _chromium_or_skip()
    try:
        teacher_page = browser.new_page(viewport={"width": 1440, "height": 900})
        teacher_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": teacher_cookie, "url": live_server.url}]
        )
        teacher_page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-dashboard')}")
        teacher_page.get_by_role("button", name="Question bank", exact=True).click()
        teacher_page.wait_for_function("window.location.search.includes('view=questions')")
        teacher_page.go_back()
        teacher_page.get_by_role("button", name="My lessons", exact=True).wait_for()
        assert "view=questions" not in teacher_page.url

        learner_page = browser.new_page(viewport={"width": 390, "height": 844})
        learner_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": learner_cookie, "url": live_server.url}]
        )
        learner_page.goto(f"{live_server.url}{reverse('liveclassroom:learning-home')}")
        learner_page.get_by_role("link", name="Navigation Biology", exact=True).wait_for()
        learner_page.get_by_role("link", name="Navigation Biology", exact=True).click()
        learner_page.get_by_role("heading", name="Navigation Biology", exact=True).wait_for()
        learner_page.go_back()
        learner_page.get_by_role("heading", name="My courses", exact=True).wait_for()
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_deck_object_urls_restore_the_selected_deck_on_back(live_server):
    teacher = get_user_model().objects.create_user(username="navigation-deck-teacher", password="password")
    first = create_deck(actor=teacher, data={"title": "Deck one", "slides": [{"markdown": "# One"}]})
    second = create_deck(actor=teacher, data={"title": "Deck two", "slides": [{"markdown": "# Two"}]})
    cookie = database_call(lambda: _cookie(teacher))
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:deck-workspace-detail', args=[first.id])}")
        page.get_by_role("button", name="Deck one", exact=True).wait_for()
        page.get_by_role("button", name="Deck two", exact=True).click()
        page.wait_for_url(f"**{reverse('liveclassroom:deck-workspace-detail', args=[second.id])}*")
        page.go_back()
        page.wait_for_url(f"**{reverse('liveclassroom:deck-workspace-detail', args=[first.id])}*")
        selected = page.get_by_role("button", name="Deck one", exact=True).evaluate(
            "element => element.classList.contains('lc-deck-selected')"
        )
        assert selected
    finally:
        browser.close()
        manager.stop()
