"""Optional real-browser acceptance checks for package-owned teaching surfaces."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client
from django.urls import reverse

from liveclassroom.models import Participant, Submission
from liveclassroom.services.analytics import session_analytics
from liveclassroom.services.classroom import (
    create_activity_definition,
    create_instant_session,
    launch_item,
    publish_activity_to_audiences,
    start_session,
)


def database_call(function):
    """Keep synchronous ORM assertions outside Playwright's active event loop."""
    def run():
        try:
            return function()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(run).result(timeout=30)


def _chromium_or_skip():
    sync_api = pytest.importorskip("playwright.sync_api")
    manager = sync_api.sync_playwright().start()
    try:
        if not Path(manager.chromium.executable_path).is_file():
            pytest.skip("Playwright Chromium is not installed")
        return manager, manager.chromium.launch()
    except Exception:
        manager.stop()
        pytest.skip("Playwright Chromium cannot launch in this environment")


@pytest.mark.django_db(transaction=True)
def test_student_join_and_teacher_console_render_without_mobile_overflow(live_server):
    assert live_server.thread.connections_override == {}
    teacher = get_user_model().objects.create_user(username="browser-teacher", password="password")
    session = create_instant_session(owner=teacher, title="Browser classroom")
    start_session(session=session, actor=teacher)
    client = Client()
    client.force_login(teacher)
    teacher_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    browser_manager, browser = _chromium_or_skip()
    try:
        student = browser.new_page(viewport={"width": 390, "height": 844})
        student.goto(f"{live_server.url}{reverse('liveclassroom:student-session', args=[session.id])}")
        student.locator("[data-liveclassroom-join-prompt] input").fill("Ada")
        with student.expect_response(
            lambda response: response.url.endswith(reverse("liveclassroom:api-v1-join", args=[session.join_code]))
        ) as joined_response, student.expect_response(
            lambda response: response.url.endswith(
                f"{reverse('liveclassroom:api-v1-state', args=[session.id])}?channel=participants"
            )
        ) as state_response:
            student.get_by_role("button", name="Join classroom").click()
        assert joined_response.value.status == 201
        assert state_response.value.status == 200
        student.wait_for_function("document.querySelector('[data-liveclassroom-join-prompt]') === null")
        student.wait_for_function("document.querySelector('#student-title')?.textContent === 'Browser classroom'")
        assert student.locator("#student-title").inner_text() == "Browser classroom"
        assert student.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        language_box = student.locator(".lc-lang-switch").bounding_box()
        title_box = student.locator("#student-title").bounding_box()
        assert language_box and title_box
        assert language_box["y"] + language_box["height"] <= title_box["y"]
        student.screenshot(path="/tmp/liveclassroom-student-mobile.png", full_page=True)
        student.locator(".lc-lang-switch").click()
        student.wait_for_function("document.querySelector('[data-liveclassroom-app]')?.dataset.locale === 'zh-Hans'")
        assert student.locator("#student-title").inner_text() == "Browser classroom"
        assert student.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        student.screenshot(path="/tmp/liveclassroom-student-mobile-zh.png", full_page=True)

        teacher_page = browser.new_page(viewport={"width": 1440, "height": 900})
        teacher_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": teacher_cookie, "url": live_server.url}]
        )
        teacher_page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-console', args=[session.id])}")
        assert teacher_page.locator("[data-audience='teacher']").is_visible()
        teacher_page.get_by_text("Invite students", exact=True).click()
        assert teacher_page.locator(".lc-join-qr img").is_visible()
        assert teacher_page.locator(".lc-presenter").is_visible()
        teacher_page.screenshot(path="/tmp/liveclassroom-teacher-desktop.png", full_page=True)

        teacher_page.goto(f"{live_server.url}{reverse('liveclassroom:student-view', args=[session.id])}")
        teacher_page.locator("#student-title").wait_for()
        teacher_page.wait_for_function("document.querySelector('#student-title')?.textContent === 'Browser classroom'")
        assert teacher_page.locator("#student-title").inner_text() == "Browser classroom"
        teacher_page.get_by_text("Participants", exact=True).click()
        teacher_page.locator("select").select_option(label="Ada (admitted)")
        assert teacher_page.get_by_role("button", name="Inspect").is_enabled()
    finally:
        browser.close()
        browser_manager.stop()


@pytest.mark.django_db(transaction=True)
def test_test_student_completes_bash_after_reload_without_affecting_class_totals(live_server):
    teacher = get_user_model().objects.create_user(username="browser-test-student", password="password")
    session = create_instant_session(owner=teacher, title="Bash test classroom")
    definition = create_activity_definition(
        owner=teacher,
        title="Practice Bash",
        type_key="liveclassroom.bash_simulator",
        definition={
            "prompt": "Run the four commands.",
            "filesystem": {"/home/student/README.txt": "Welcome!", "/home/student/projects/hello.txt": "Hi"},
            "initial_directory": "/home/student",
            "completion": {
                "required_commands": ["pwd", "ls", "cat", "cd"],
                "required_directory": "/home/student/projects",
            },
            "max_transcript_entries": 16,
        },
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    publish_activity_to_audiences(
        session=session,
        activity=activity,
        channels=["display", "participants"],
        actor=teacher,
    )
    teacher_cookie = Client()
    teacher_cookie.force_login(teacher)
    cookie = teacher_cookie.cookies[settings.SESSION_COOKIE_NAME].value

    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        test_url = reverse("liveclassroom:api-v1-test-student", args=[session.id])
        submit_url = reverse("liveclassroom:api-v1-submit", args=[activity.id])
        page.goto(f"{live_server.url}{reverse('liveclassroom:student-view', args=[session.id])}")
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(test_url)
        ) as created:
            page.get_by_role("button", name="Try as test student", exact=True).click()
        assert created.value.status == 200
        first_participant_id = created.value.json()["participant"]["id"]

        command = page.get_by_label("Command", exact=True)
        command.wait_for()
        command.fill("pwd")
        command.press("Enter")
        page.get_by_text("/home/student", exact=True).wait_for()

        # Reloading the staff page does not create a new participant. Reopening
        # the one-click test surface restores the same tab-local Bash draft.
        page.reload()
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(test_url)
        ) as reused:
            page.get_by_role("button", name="Try as test student", exact=True).click()
        assert reused.value.status == 200
        assert reused.value.json()["participant"]["id"] == first_participant_id
        command = page.get_by_label("Command", exact=True)
        command.wait_for()
        page.wait_for_function(
            "document.querySelector('.lc-bash-simulator-output')?.textContent?.includes('pwd')"
        )
        for command_text, expected in (
            ("ls", "README.txt"),
            ("cat README.txt", "Welcome!"),
        ):
            command.fill(command_text)
            command.press("Enter")
            page.wait_for_function(
                "(value) => document.querySelector('.lc-bash-simulator-output')?.textContent?.includes(value)",
                arg=expected,
            )
        command.fill("cd projects")
        command.press("Enter")
        page.wait_for_function(
            """document.querySelector('.lc-bash-simulator-directory')?.textContent
            === 'Working directory: /home/student/projects'"""
        )
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.split("?", 1)[0].endswith(submit_url)
        ) as submitted:
            page.get_by_role("button", name="Complete activity", exact=True).click()
        assert submitted.value.status == 201
        page.get_by_text("Completed and saved.", exact=True).wait_for()

        def assert_isolated_completion():
            participant = Participant.objects.get(pk=first_participant_id)
            assert participant.is_test is True
            assert Submission.objects.filter(activity=activity, participant=participant).count() == 1
            analytics = session_analytics(session)
            assert analytics["attendance"]["total"] == 0
            assert analytics["activities"][0]["submitted_count"] == 0

        database_call(assert_isolated_completion)
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_timer_is_shared_with_a_late_display_and_can_pause_and_resume(live_server):
    teacher = get_user_model().objects.create_user(username="browser-timer-teacher", password="password")
    session = create_instant_session(owner=teacher, title="Shared timer classroom")
    definition = create_activity_definition(
        owner=teacher,
        title="Pair discussion",
        type_key="liveclassroom.timer",
        definition={"duration_seconds": 20, "auto_start": False, "label": "Discuss"},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    publish_activity_to_audiences(
        session=session,
        activity=activity,
        channels=["display", "participants"],
        actor=teacher,
    )
    client = Client()
    client.force_login(teacher)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    timer_url = reverse("liveclassroom:api-v1-timer", args=[activity.id])
    display_url = f"{live_server.url}{reverse('liveclassroom:classroom-display', args=[session.id])}"

    manager, browser = _chromium_or_skip()
    try:
        teacher_page = browser.new_page()
        teacher_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        teacher_page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-console', args=[session.id])}")
        teacher_page.get_by_role("button", name="Start timer", exact=True).wait_for()

        first_display = browser.new_page()
        first_display.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        first_display.goto(display_url)
        first_display.get_by_text("Start timer", exact=True).wait_for()

        with teacher_page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(timer_url)
        ) as started:
            teacher_page.get_by_role("button", name="Start timer", exact=True).click()
        assert started.value.status == 200
        teacher_page.get_by_role("button", name="Pause timer", exact=True).wait_for()
        first_display.reload()
        first_display.wait_for_function(
            "document.querySelector('.lc-timer-countdown')?.textContent !== '00:20'"
        )

        # This context opens after the timer started. Its countdown is loaded
        # from the same server runtime rather than beginning a new local timer.
        late_display = browser.new_page()
        late_display.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        late_display.goto(display_url)
        late_display.wait_for_function(
            "document.querySelector('.lc-timer-countdown')?.textContent !== '00:20'"
        )

        with teacher_page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(timer_url)
        ) as paused:
            teacher_page.get_by_role("button", name="Pause timer", exact=True).click()
        assert paused.value.status == 200
        teacher_page.get_by_role("button", name="Resume timer", exact=True).wait_for()
        first_display.reload()
        late_display.reload()
        first_countdown = first_display.locator(".lc-timer-countdown").inner_text()
        late_countdown = late_display.locator(".lc-timer-countdown").inner_text()
        assert first_countdown == late_countdown

        with teacher_page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(timer_url)
        ) as resumed:
            teacher_page.get_by_role("button", name="Resume timer", exact=True).click()
        assert resumed.value.status == 200
        late_display.reload()
        late_display.wait_for_function(
            "document.querySelector('.lc-timer-countdown')?.textContent !== '00:20'"
        )
    finally:
        browser.close()
        manager.stop()
