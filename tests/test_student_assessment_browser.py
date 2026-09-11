"""Student browser coverage for published assessment start, resume and submit."""

from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.classroom import create_activity_definition
from tests.test_assessment_review import _fixture as review_fixture
from tests.test_browser_workflows import _chromium_or_skip


def _run(owner):
    question = create_activity_definition(
        owner=owner,
        title="Capital question",
        type_key="single_choice",
        definition={
            "prompt": "What is the capital of France?",
            "options": [{"id": "a", "text": "Paris"}, {"id": "b", "text": "Rome"}],
            "answer": "a",
        },
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Geography quiz",
            "instructions": "Choose one answer.",
            "settings": {"max_attempts": 1, "audience": "authenticated_link"},
            "items": [{"revision_id": question.current_revision_id}],
        },
    )
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


@pytest.mark.django_db
def test_student_assessment_page_requires_existing_account(client, db):
    owner = get_user_model().objects.create_user(username="assessment-page-owner")
    run = _run(owner)
    response = client.get(reverse("liveclassroom:assessment-attempt", args=[run.public_id]))
    assert response.status_code in {301, 302}


@pytest.mark.django_db
def test_authenticated_assessment_page_issues_a_csrf_token_for_react_mutations(client):
    owner = get_user_model().objects.create_user(username="assessment-page-csrf-owner")
    learner = get_user_model().objects.create_user(username="assessment-page-csrf-learner")
    run = _run(owner)

    client.force_login(learner)
    response = client.get(reverse("liveclassroom:assessment-attempt", args=[run.public_id]))

    assert response.status_code == 200
    assert 'name="csrfmiddlewaretoken"' in response.content.decode()


@pytest.mark.django_db(transaction=True)
def test_student_starts_saves_resumes_and_submits_assessment(live_server):
    users = get_user_model()
    owner = users.objects.create_user(username="assessment-ui-owner", password="password")
    users.objects.create_user(username="assessment-ui-learner", password="password")
    run = _run(owner)
    client = Client()
    assert client.login(username="assessment-ui-learner", password="password")
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    manager, browser = _chromium_or_skip()
    screenshots = Path(".local/screenshots")
    screenshots.mkdir(parents=True, exist_ok=True)
    try:
        page = browser.new_page(viewport={"width": 390, "height": 844}, locale="en-US")
        page.set_default_timeout(5000)
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:assessment-attempt', args=[run.public_id])}")
        page.get_by_role("heading", name="Geography quiz", exact=True).wait_for()
        assert page.get_by_text("Choose one answer.", exact=True).is_visible()
        page.get_by_role("button", name="Start / resume assessment", exact=True).click()
        page.get_by_text("What is the capital of France?", exact=True).wait_for()
        page.get_by_label("Paris", exact=False).check()
        page.get_by_role("status").filter(has_text="Saved").wait_for()
        page.reload()
        page.get_by_text("What is the capital of France?", exact=True).wait_for()
        assert page.get_by_label("Paris", exact=False).is_checked()
        page.goto(f"{live_server.url}{reverse('liveclassroom:assessment-attempt', args=[run.public_id])}?lang=zh-Hans")
        page.get_by_text("What is the capital of France?", exact=True).wait_for()
        page.get_by_role("button", name="提交测验", exact=True).wait_for()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(screenshots / "2026-09-10-student-assessment-zh-mobile.png"), full_page=True)
        page.goto(f"{live_server.url}{reverse('liveclassroom:assessment-attempt', args=[run.public_id])}")
        page.get_by_text("What is the capital of France?", exact=True).wait_for()
        page.get_by_role("button", name="Submit assessment", exact=True).click()
        page.get_by_role("heading", name="Submit this assessment?", exact=True).wait_for()
        page.get_by_role("button", name="Submit now", exact=True).click()
        page.get_by_role("heading", name="Assessment submitted", exact=True).wait_for()
        assert page.get_by_text("Scores and feedback are not released yet.", exact=True).is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(screenshots / "2026-09-10-student-assessment-mobile.png"), full_page=True)
        desktop_context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
        desktop = desktop_context.new_page()
        desktop.set_default_timeout(5000)
        desktop.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        desktop.set_default_timeout(5000)
        desktop.goto(f"{live_server.url}{reverse('liveclassroom:assessment-attempt', args=[run.public_id])}")
        desktop.get_by_role("button", name="Start / resume assessment", exact=True).click()
        desktop.get_by_role("heading", name="Assessment submitted", exact=True).wait_for()
        assert desktop.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        desktop.screenshot(path=str(screenshots / "2026-09-10-student-assessment-desktop.png"), full_page=True)
        desktop.close()
        desktop_context.close()
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_student_reviews_submitted_attempt_without_released_answer_key(live_server):
    """A learner can see their retained answer while unreleased keys stay hidden."""
    _owner, learner, _other, _question, _run, _attempt, _item = review_fixture()
    client = Client()
    client.force_login(learner)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1000, "height": 900}, locale="en-US")
        page.set_default_timeout(5000)
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:assessment-history')}")
        page.get_by_role("heading", name="Assessment history", exact=True).wait_for()
        page.get_by_role("button", name="Review attempt", exact=True).click()

        page.get_by_role("heading", name="Retained review", exact=True).wait_for()
        review_item = page.locator("[data-review-item]").first
        assert review_item.get_by_text("Original prompt", exact=True).is_visible()
        assert review_item.get_by_text("One", exact=True).is_visible()
        assert review_item.get_by_text("Answer key", exact=True).count() == 0
    finally:
        browser.close()
        manager.stop()
