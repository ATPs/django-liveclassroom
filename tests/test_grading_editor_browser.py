"""Real-browser acceptance for ordinary objective-grading controls."""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import Flow
from liveclassroom.services.flows import create_flow
from tests.test_browser_workflows import _chromium_or_skip, database_call


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


@pytest.mark.django_db(transaction=True)
def test_teacher_creates_and_reopens_objective_grading_fields(live_server):
    teacher = get_user_model().objects.create_user(username="grading-browser-teacher", password="password")
    flow = create_flow(title="Grading controls", creator=teacher)
    cookie = _session_cookie(teacher)
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        page.goto(f"{live_server.url}{reverse('liveclassroom:flow-builder-detail', args=[flow.id])}")
        page.get_by_role("heading", name="Grading controls", exact=True).wait_for()
        add_step_url = reverse("liveclassroom:api-v1-flow-add-step", args=[flow.id])

        def open_add_form(activity_type: str):
            page.get_by_role("button", name="Add step").click()
            form = page.locator(".lc-builder-step-form")
            form.locator("select").first.select_option(activity_type)
            return form

        def fill_group(form, label: str, value: str, element: str):
            form.locator(".lc-form-group").filter(has_text=label).locator(element).fill(value)

        form = open_add_form("liveclassroom.single_choice")
        fill_group(form, "Title", "Choice grading", "input")
        fill_group(form, "Prompt", "Choose beta", "textarea")
        fill_group(form, "Options", "Alpha\nBeta", "textarea")
        form.locator(".lc-form-group").filter(has_text="Correct answer").locator("select").select_option("B")
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(add_step_url)
        ) as choice_response:
            form.get_by_role("button", name="Save step", exact=True).click()
        assert choice_response.value.status == 201
        page.locator(".lc-builder-step-card").filter(has_text="Choice grading").wait_for()

        form = open_add_form("liveclassroom.numeric")
        fill_group(form, "Title", "Numeric grading", "input")
        fill_group(form, "Prompt", "Give pi", "textarea")
        fill_group(form, "Correct number", "3.14", "input")
        fill_group(form, "Tolerance", "0.01", "input")
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(add_step_url)
        ) as numeric_response:
            form.get_by_role("button", name="Save step", exact=True).click()
        assert numeric_response.value.status == 201
        page.locator(".lc-builder-step-card").filter(has_text="Numeric grading").wait_for()

        form = open_add_form("liveclassroom.short_text")
        fill_group(form, "Title", "Text grading", "input")
        fill_group(form, "Prompt", "Name the molecule", "textarea")
        fill_group(form, "Accepted answers", "RNA\nDNA\nRNA", "textarea")
        form.get_by_text("Case sensitive", exact=True).locator("input").check()
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(add_step_url)
        ) as text_response:
            form.get_by_role("button", name="Save step", exact=True).click()
        assert text_response.value.status == 201
        page.locator(".lc-builder-step-card").filter(has_text="Text grading").wait_for()

        def definitions():
            saved = Flow.objects.get(pk=flow.pk).steps.select_related("activity_definition").order_by("position")
            return [step.activity_definition.definition for step in saved]

        assert database_call(definitions) == [
            {
                "prompt": "Choose beta",
                "options": [{"id": "A", "text": "Alpha"}, {"id": "B", "text": "Beta"}],
                "answer": "B",
            },
            {"prompt": "Give pi", "answer": "3.14", "tolerance": "0.01"},
            {"prompt": "Name the molecule", "answer": ["RNA", "DNA"], "case_sensitive": True},
        ]

        page.reload()
        page.get_by_role("heading", name="Grading controls", exact=True).wait_for()
        choice_card = page.locator(".lc-builder-step-card").filter(has_text="Choice grading")
        choice_card.get_by_role("button", name="Edit", exact=True).click()
        editor = page.locator(".lc-builder-main form.lc-form")
        assert editor.get_by_label("Correct answer", exact=True).input_value() == "B"
        editor.get_by_role("button", name="Cancel", exact=True).click()

        numeric_card = page.locator(".lc-builder-step-card").filter(has_text="Numeric grading")
        numeric_card.get_by_role("button", name="Edit", exact=True).click()
        editor = page.locator(".lc-builder-main form.lc-form")
        assert editor.get_by_label("Correct number", exact=True).input_value() == "3.14"
        assert editor.get_by_label("Tolerance", exact=True).input_value() == "0.01"
        editor.get_by_role("button", name="Cancel", exact=True).click()

        text_card = page.locator(".lc-builder-step-card").filter(has_text="Text grading")
        text_card.get_by_role("button", name="Edit", exact=True).click()
        editor = page.locator(".lc-builder-main form.lc-form")
        assert editor.get_by_label("Accepted answers", exact=True).input_value() == "RNA\nDNA"
        assert editor.get_by_text("Case sensitive", exact=True).locator("input").is_checked()
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.evaluate("""[...document.querySelectorAll('*')]
            .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
            .map((element) => {
                const right = Math.round(element.getBoundingClientRect().right);
                return `${element.tagName}.${element.className}:${right}`;
            })
            .slice(0, 20)""")
        assert overflow == []
    finally:
        browser.close()
        manager.stop()
