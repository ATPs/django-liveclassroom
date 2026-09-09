"""Browser coverage for authoring and responding to an essay activity."""

import re

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.services.flows import create_flow
from tests.test_browser_workflows import _chromium_or_skip, database_call


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


@pytest.mark.django_db(transaction=True)
def test_teacher_creates_and_reopens_essay_editor_on_mobile(live_server):
    teacher = get_user_model().objects.create_user(username="essay-browser-teacher", password="password")
    flow = create_flow(title="Essay workflow", creator=teacher)
    cookie = _session_cookie(teacher)
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:flow-builder-detail', args=[flow.id])}")
        page.get_by_role("heading", name="Essay workflow", exact=True).wait_for()

        page.get_by_role("button", name=re.compile(r"Add step")).click()
        form = page.locator(".lc-builder-step-form")
        form.locator("select").first.select_option("liveclassroom.essay")
        form.locator(".lc-form-group").filter(has_text="Title").locator("input").fill("Reflection")
        form.locator(".lc-form-group").filter(has_text="Prompt").locator("textarea").fill("Explain your reasoning.")
        form.locator(".lc-form-group").filter(has_text="Max length").locator("input").fill("120")
        form.get_by_role("button", name="Save step", exact=True).click()
        page.locator(".lc-builder-step-card").filter(has_text="Reflection").wait_for()

        saved = database_call(
            lambda: list(
                flow.steps.select_related("activity_definition")
                .values_list("activity_definition__type_key", "activity_definition__definition")
            )
        )
        assert saved == [("liveclassroom.essay", {"prompt": "Explain your reasoning.", "max_length": 120})]

        page.locator(".lc-builder-step-card").filter(has_text="Reflection").get_by_role(
            "button", name="Edit", exact=True
        ).click()
        editor = page.locator(".lc-builder-main form.lc-form")
        assert editor.get_by_label("Maximum response length", exact=True).input_value() == "120"
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.evaluate("""[...document.querySelectorAll('*')]
            .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
            .map((element) => `${element.tagName}.${element.className}`)
            .slice(0, 20)""")
        assert overflow == []
    finally:
        browser.close()
        manager.stop()
