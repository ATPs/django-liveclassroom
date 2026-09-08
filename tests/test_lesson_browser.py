"""Browser workflows for lesson snapshots and the teacher workspace."""

import re

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import Course, Participant, ParticipantConnection, Submission
from liveclassroom.services.classroom import (
    create_activity_definition,
    end_session,
    join_guest,
    start_session,
    submit_answer,
)
from liveclassroom.services.flows import add_flow_step, create_flow
from liveclassroom.services.plans import create_session, launch_plan_step
from tests.test_browser_workflows import _chromium_or_skip, database_call


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def _make_prepared_session(teacher):
    course = Course.objects.create(
        title="Browser biology",
        slug="browser-biology",
        created_by=teacher,
    )
    lesson = create_flow(title="Personal browser lesson", creator=teacher)
    assert lesson.course_id is None
    definition = create_activity_definition(
        owner=teacher,
        title="Original question",
        type_key="liveclassroom.short_text",
        definition={"prompt": "Original prompt"},
    )
    add_flow_step(flow=lesson, actor=teacher, activity_definition=definition)

    session = create_session(
        owner=teacher,
        title="Snapshot browser class",
        course=course,
        flow=lesson,
    )
    start_session(session=session, actor=teacher)
    plan_step = session.plan_steps.get()
    activity = launch_plan_step(
        session=session,
        step=plan_step,
        actor=teacher,
        channel="participants",
    )
    launch_plan_step(session=session, step=plan_step, actor=teacher, channel="display")
    return session, activity


@pytest.mark.django_db(transaction=True)
def test_student_can_submit_revise_and_resubmit_after_teacher_activity_edit(live_server):
    teacher = get_user_model().objects.create_user(username="lesson-browser-teacher", password="password")
    session, activity = _make_prepared_session(teacher)
    cookie = _session_cookie(teacher)
    student_state_url = reverse("liveclassroom:api-v1-state", args=[session.id])
    submit_url = reverse("liveclassroom:api-v1-submit", args=[activity.id])

    browser_manager, browser = _chromium_or_skip()
    from playwright.sync_api import expect

    try:
        student = browser.new_page(viewport={"width": 390, "height": 844})
        student.goto(f"{live_server.url}{reverse('liveclassroom:student-session', args=[session.id])}")
        student.locator("[data-liveclassroom-join-prompt] input").fill("Ada")
        with student.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(reverse("liveclassroom:api-v1-join", args=[session.join_code]))
        ) as joined_response, student.expect_response(
            lambda response: response.request.method == "GET"
            and response.url.endswith(f"{student_state_url}?channel=participants")
        ) as joined_state_response:
            student.get_by_role("button", name="Join classroom", exact=True).click()
        assert joined_response.value.status == 201
        assert joined_state_response.value.status == 200

        student.get_by_text("Original prompt", exact=True).wait_for()
        answer_input = student.locator('#student-content textarea[name="text"]')
        answer_input.wait_for()
        assert answer_input.is_enabled()

        answer_input.fill("first answer")
        with student.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(submit_url)
        ) as first_submission, student.expect_response(
            lambda response: response.request.method == "GET"
            and response.url.endswith(f"{student_state_url}?channel=participants")
        ) as first_submission_state:
            student.get_by_role("button", name="Submit answer", exact=True).click()
        assert first_submission.value.status == 201
        assert first_submission_state.value.status == 200
        student.wait_for_function(
            """() => {
                const input = document.querySelector('#student-content textarea[name="text"]');
                return input && !input.disabled;
            }"""
        )
        assert answer_input.is_enabled()

        answer_input.fill("revised answer")
        with student.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(submit_url)
        ) as second_submission, student.expect_response(
            lambda response: response.request.method == "GET"
            and response.url.endswith(f"{student_state_url}?channel=participants")
        ) as second_submission_state:
            student.get_by_role("button", name="Save changes", exact=True).click()
        assert second_submission.value.status == 201, second_submission.value.text()
        assert second_submission_state.value.status == 200

        teacher_page = browser.new_page(viewport={"width": 1440, "height": 900})
        teacher_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        plan_url = reverse("liveclassroom:api-v1-session-plan", args=[session.id])
        with teacher_page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(plan_url)
        ) as plan_response:
            teacher_page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-console', args=[session.id])}")
        assert plan_response.value.status == 200

        teacher_page.get_by_text("Edit lesson", exact=True).click()
        plan = teacher_page.locator("[data-session-plan]")
        edit_button = plan.get_by_role("button", name="Edit this classroom", exact=True)
        edit_button.wait_for()
        edit_button.click()
        editor = plan.locator("form").filter(has_text="Prompt").first
        editor.get_by_label("Title", exact=True).fill("Revised question")
        assert editor.get_by_label("Prompt", exact=True).count() == 1, editor.inner_html()
        editor.get_by_label("Prompt", exact=True).fill("Revised prompt")
        revise_url = reverse("liveclassroom:api-v1-revise", args=[activity.id])
        with teacher_page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(revise_url)
        ) as revision_response:
            editor.get_by_role("button", name="Save", exact=True).click()
        assert revision_response.value.status == 201

        def revised_participant_state(response):
            if response.request.method != "GET" or not response.url.endswith(
                f"{student_state_url}?channel=participants"
            ):
                return False
            payload = response.json()
            current = payload.get("current_activity") or {}
            return response.status == 200 and current.get("revision") == 2

        with student.expect_response(revised_participant_state) as revised_state:
            student.wait_for_function(
                """() => {
                    const input = document.querySelector('#student-content textarea[name="text"]');
                    return input && !input.disabled && input.value === "";
                }"""
            )
        assert revised_state.value.status == 200

        answer_input = student.locator('#student-content textarea[name="text"]')
        answer_input.fill("answer after revision")
        with student.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(submit_url)
        ) as final_submission, student.expect_response(
            lambda response: response.request.method == "GET"
            and response.url.endswith(f"{student_state_url}?channel=participants")
        ) as final_submission_state:
            student.get_by_role("button", name="Submit answer", exact=True).click()
        assert final_submission.value.status == 201
        assert final_submission_state.value.status == 200

        def assert_submission_saved():
            submission = Submission.objects.get(activity=activity)
            assert submission.answer == {"text": "answer after revision"}
            assert submission.is_stale is False
            assert submission.revisions.count() == 3

        database_call(assert_submission_saved)

        teacher_page.get_by_text("More", exact=True).click()
        review_fieldset = teacher_page.get_by_role("group", name="Student review access")
        allow_review = review_fieldset.get_by_label("Allow review", exact=True)
        allow_review.wait_for()
        review_url = reverse("liveclassroom:api-v1-review-settings", args=[activity.id])
        with teacher_page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(review_url)
        ) as review_response:
            allow_review.click()
        assert review_response.value.status == 200
        expect(allow_review).to_be_checked()
        teacher_page.screenshot(path="/tmp/liveclassroom-plan-desktop.png", full_page=True)

        end_url = reverse("liveclassroom:api-v1-end", args=[session.id])
        teacher_page.once("dialog", lambda dialog: dialog.accept())
        with teacher_page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(end_url)
        ) as end_response:
            teacher_page.get_by_text("Class menu", exact=True).click()
            teacher_page.get_by_role("button", name="End class", exact=True).click()
        assert end_response.value.status == 200

        def snapshot_participant():
            participant = Participant.objects.get(session=session, display_name="Ada")
            timestamps = (
                participant.joined_at,
                participant.last_seen_at,
                participant.connected_at,
                participant.disconnected_at,
            )
            connections = list(
                ParticipantConnection.objects.filter(participant=participant)
                .order_by("id")
                .values_list("id", "connection_id", "connected_at", "last_seen_at", "disconnected_at")
            )
            return participant.id, timestamps, connections, Participant.objects.filter(session=session).count()

        participant_id, participant_timestamps, connection_snapshot, participant_count = database_call(
            snapshot_participant
        )

        join_url = reverse("liveclassroom:api-v1-join", args=[session.join_code])
        join_requests = []

        def record_join_request(request):
            if request.method == "POST" and request.url.endswith(join_url):
                join_requests.append(request.url)

        student.on("request", record_join_request)
        history_url = reverse("liveclassroom:api-v1-history", args=[session.id])
        with student.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(history_url)
        ) as review_history_response:
            student.reload()
        assert review_history_response.value.status == 200
        history = student.locator("details[data-liveclassroom-history]")
        history.locator("summary").get_by_text("Previous activities", exact=True).click()
        history.get_by_text("Revised prompt", exact=True).wait_for()
        history.get_by_text("answer after revision", exact=True).wait_for()
        assert student.get_by_text("Waiting for the teacher.", exact=True).count() == 0
        assert join_requests == []
        enabled_answer_controls = student.locator(
            "#student-content input:not([disabled]), #student-content textarea:not([disabled]), "
            "#student-content select:not([disabled]), #student-content button:not([disabled])"
        )
        assert enabled_answer_controls.count() == 0
        student.screenshot(path="/tmp/liveclassroom-review-mobile.png", full_page=True)

        def assert_attendance_unchanged():
            participant = Participant.objects.get(pk=participant_id)
            assert (
                participant.joined_at,
                participant.last_seen_at,
                participant.connected_at,
                participant.disconnected_at,
            ) == participant_timestamps
            assert Participant.objects.filter(session=session).count() == participant_count
            assert list(
                ParticipantConnection.objects.filter(participant=participant)
                .order_by("id")
                .values_list("id", "connection_id", "connected_at", "last_seen_at", "disconnected_at")
            ) == connection_snapshot

        database_call(assert_attendance_unchanged)
    finally:
        browser.close()
        browser_manager.stop()


@pytest.mark.django_db(transaction=True)
def test_ended_single_choice_review_shows_labels_and_own_answer(live_server):
    teacher = get_user_model().objects.create_user(username="single-choice-review-teacher", password="password")
    lesson = create_flow(title="Single choice review lesson", creator=teacher)
    definition = create_activity_definition(
        owner=teacher,
        title="Review choice",
        type_key="liveclassroom.single_choice",
        definition={
            "prompt": "Choose a color",
            "options": [{"id": "A", "text": "Blue"}, {"id": "B", "text": "Green"}],
        },
    )
    add_flow_step(flow=lesson, actor=teacher, activity_definition=definition)
    session = create_session(owner=teacher, title="Single choice review classroom", flow=lesson)
    start_session(session=session, actor=teacher)
    activity = launch_plan_step(
        session=session,
        step=session.plan_steps.get(),
        actor=teacher,
        channel="participants",
    )
    participant = join_guest(session=session, display_name="Ada", guest_id="single-choice-review-guest")
    submit_answer(activity=activity, participant=participant, answer={"choice": "A"})
    activity.reviewable = True
    activity.save(update_fields=["reviewable"])
    end_session(session=session, actor=teacher)

    guest_client = Client()
    guest_session = guest_client.session
    guest_session[f"liveclassroom.guest.{session.id}"] = participant.guest_id
    guest_session[f"liveclassroom.participant.{session.id}"] = participant.id
    guest_session.save()
    guest_cookie = guest_client.cookies[settings.SESSION_COOKIE_NAME].value

    browser_manager, browser = _chromium_or_skip()
    try:
        student = browser.new_page(viewport={"width": 390, "height": 844})
        student.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": guest_cookie, "url": live_server.url}]
        )
        student.goto(f"{live_server.url}{reverse('liveclassroom:student-session', args=[session.id])}")
        history = student.locator("details[data-liveclassroom-history]")
        history.locator("summary").get_by_text("Previous activities", exact=True).click()
        assert history.get_by_label("Blue", exact=True).is_disabled()
        assert history.get_by_label("Green", exact=True).is_disabled()
        student.locator("[data-liveclassroom-own-answer]").get_by_text("Blue", exact=True).wait_for()
        enabled_answer_controls = student.locator(
            "#student-content input:not([disabled]), #student-content textarea:not([disabled]), "
            "#student-content select:not([disabled]), #student-content button:not([disabled])"
        )
        assert enabled_answer_controls.count() == 0
    finally:
        browser.close()
        browser_manager.stop()


@pytest.mark.django_db(transaction=True)
def test_teacher_workspace_tabs_create_class_and_start_instant_session(live_server):
    teacher = get_user_model().objects.create_user(username="workspace-browser-teacher", password="password")
    cookie = _session_cookie(teacher)
    dashboard_url = reverse("liveclassroom:teacher-dashboard")

    browser_manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        workspace_url = reverse("liveclassroom:api-v1-workspace")
        flows_url = reverse("liveclassroom:api-v1-flows")
        with page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(workspace_url)
        ) as workspace_response, page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(flows_url)
        ) as flows_response:
            page.goto(f"{live_server.url}{dashboard_url}")
        assert workspace_response.value.status == 200
        assert flows_response.value.status == 200
        page.get_by_role("heading", name="Teacher workspace", exact=True).wait_for()

        for label in ("My lessons", "Shared with me", "Classes", "Recent sessions"):
            tab = page.get_by_role("button", name=label, exact=True)
            tab.click()
            assert tab.get_attribute("aria-selected") == "true"

        page.get_by_role("button", name="Classes", exact=True).click()
        page.get_by_role("heading", name="Create class", exact=True).wait_for()
        page.get_by_label("Class title", exact=True).fill("Interactive biology")
        courses_url = reverse("liveclassroom:api-v1-courses")
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(courses_url)
        ) as course_response:
            page.get_by_role("button", name="Create class", exact=True).click()
        assert course_response.value.status == 201
        page.get_by_role("heading", name="Interactive biology", exact=True).wait_for()

        page.get_by_role("button", name="Instant classroom", exact=True).click()
        page.get_by_role("heading", name="New classroom", exact=True).wait_for()
        page.get_by_label("Title", exact=True).fill("Workspace instant class")
        page.get_by_label("Class for this classroom", exact=True).select_option(label="Interactive biology")
        session_url = reverse("liveclassroom:api-v1-session-create")
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(session_url)
        ) as session_response:
            page.get_by_role("button", name="Create classroom", exact=True).click()
        assert session_response.value.status == 201
        page.wait_for_url(re.compile(rf"^{re.escape(live_server.url)}/teacher/sessions/\d+/$"))
        page.get_by_role("heading", name="Instant session", exact=True).wait_for()
    finally:
        browser.close()
        browser_manager.stop()
