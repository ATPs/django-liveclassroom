"""Browser acceptance for lesson saveback and classroom reuse."""

import re

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import Flow, FlowStep, LiveSession
from liveclassroom.services.classroom import create_activity_definition, start_session
from liveclassroom.services.flows import add_flow_step, create_flow
from liveclassroom.services.plans import create_session
from tests.test_browser_workflows import _chromium_or_skip, database_call


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def _lesson(teacher):
    lesson = create_flow(title="Browser reuse lesson", creator=teacher)
    steps = []
    for position in (1, 2):
        definition = create_activity_definition(
            owner=teacher,
            title=f"Question {position}",
            type_key="liveclassroom.short_text",
            definition={"prompt": f"Original prompt {position}"},
        )
        steps.append(add_flow_step(flow=lesson, actor=teacher, activity_definition=definition))
    return lesson, steps


@pytest.mark.django_db(transaction=True)
def test_teacher_saves_lesson_improvements_and_reuses_full_classroom(live_server):
    teacher = get_user_model().objects.create_user(username="reuse-browser-teacher", password="password")
    get_user_model().objects.create_user(username="reuse-browser-colleague", password="password")
    lesson, source_steps = _lesson(teacher)
    classroom = create_session(owner=teacher, title="Browser live classroom", flow=lesson)
    untouched = create_session(owner=teacher, title="Pre-created classroom", flow=lesson)
    start_session(session=classroom, actor=teacher)
    editable_step = classroom.plan_steps.get(position=2)
    untouched_step = untouched.plan_steps.get(key=source_steps[1].key)
    old_prompt = untouched_step.snapshot["content"]["prompt"]
    cookie = _session_cookie(teacher)

    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        plan_url = reverse("liveclassroom:api-v1-session-plan", args=[classroom.id])
        with page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(plan_url)
        ) as initial_plan:
            page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-console', args=[classroom.id])}")
        assert initial_plan.value.status == 200

        page.get_by_text("Edit lesson", exact=True).click()
        plan = page.locator("[data-session-plan]")
        step_card = plan.locator(":scope > div.lc-plan-step").filter(has_text="Question 2").first
        step_card.get_by_role("button", name="Edit this classroom", exact=True).click()
        editor = page.locator(".lc-editor-workspace form").filter(has_text="Prompt").first
        editor.get_by_label("Title", exact=True).fill("Revised question 2")
        editor.get_by_label("Prompt", exact=True).fill("Revised classroom prompt")
        step_url = reverse("liveclassroom:api-v1-plan-step", args=[classroom.id, editable_step.id])
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(step_url)
        ) as edit_response:
            editor.get_by_role("button", name="Save", exact=True).click()
        assert edit_response.value.status == 200

        compare_url = reverse("liveclassroom:api-v1-plan-compare", args=[classroom.id])
        with page.expect_response(
            lambda response: response.request.method == "GET"
            and response.url.endswith(f"{compare_url}?direction=to_lesson")
        ) as comparison_response:
            plan.get_by_role("button", name="Save improvements to lesson", exact=True).click()
        assert comparison_response.value.status == 200
        review = page.locator('section[aria-label="Review changes"]')
        review.get_by_role("heading", name="Choose changes to apply", exact=True).wait_for()
        assert review.locator('input[type="checkbox"]').first.is_checked()
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(compare_url)
        ) as apply_response:
            review.get_by_role("button", name="Apply selected changes", exact=True).click()
        assert apply_response.value.status == 200

        def check_source():
            source_step = FlowStep.objects.get(flow=lesson, key=source_steps[1].key)
            assert source_step.activity_definition.title == "Revised question 2"
            assert source_step.activity_definition.definition == {"prompt": "Revised classroom prompt"}
            untouched_step.refresh_from_db()
            assert untouched_step.snapshot["content"]["prompt"] == old_prompt

        database_call(check_source)

        copy_input = plan.get_by_label("Save a personal lesson copy", exact=True)
        copy_input.fill("Browser personal copy")
        save_flow_url = reverse("liveclassroom:api-v1-session-save-flow", args=[classroom.id])
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(save_flow_url)
        ) as copy_response:
            plan.get_by_role("button", name="Save lesson copy", exact=True).click()
        assert copy_response.value.status == 201
        copy_step_count = database_call(
            lambda: Flow.objects.get(title="Browser personal copy", created_by=teacher).steps.count()
        )
        assert copy_step_count == 2

        workspace_url = reverse("liveclassroom:api-v1-workspace")
        flows_url = reverse("liveclassroom:api-v1-flows")
        with page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(workspace_url)
        ), page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(flows_url)
        ):
            page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-dashboard')}")
        page.get_by_role("button", name="Recent sessions", exact=True).click()
        recent = page.locator(".lc-workspace-item").filter(has_text="Browser live classroom").first
        recent.get_by_role("button", name="Reuse session", exact=True).click()
        page.get_by_label("Title", exact=True).fill("Reused browser classroom")
        create_url = reverse("liveclassroom:api-v1-session-create")
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(create_url)
        ) as reuse_response:
            page.get_by_role("button", name="Create classroom", exact=True).click()
        assert reuse_response.value.status == 201
        destination = re.compile(rf"^{re.escape(live_server.url)}/teacher/sessions/(\d+)/$")
        page.wait_for_url(destination)
        matched = destination.fullmatch(page.url)
        assert matched is not None
        reused_id = int(matched.group(1))
        page.get_by_text("Edit lesson", exact=True).click()
        page.locator("[data-session-plan]").wait_for()

        def check_reused():
            reused = LiveSession.objects.get(pk=reused_id)
            assert reused.plan_steps.filter(removed=False).count() == 2
            assert reused.participants.count() == 0

        database_call(check_reused)
    finally:
        browser.close()
        manager.stop()
