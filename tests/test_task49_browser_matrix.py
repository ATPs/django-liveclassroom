"""Focused Chromium matrix for Task 49 acceptance gaps.

The other browser modules cover the individual authoring and classroom
surfaces.  These tests join the gaps that were previously only covered by
service or API tests: browser-authenticated review/progress privacy, native
deck audience separation, and builder recovery after a transient API failure.
The browser remains the actor for every HTTP request asserted here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from liveclassroom.models import AssessmentRun, Course, CourseMembership, Flow
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition, create_instant_session, start_session
from liveclassroom.services.deck_snapshots import create_deck_snapshot
from liveclassroom.services.decks import create_deck
from tests.test_assessment_review import _fixture as review_fixture
from tests.test_browser_workflows import _chromium_or_skip, database_call

SCREENSHOTS = Path(".local/2026-09-09/screenshots/task49")


@pytest.fixture
def vaultpub_apps():
    """Enable the optional renderer used by the native-deck browser path."""
    with override_settings(INSTALLED_APPS=[*settings.INSTALLED_APPS, "vaultpub.django_app"]):
        yield


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def _listeners(page):
    console_errors: list[str] = []
    api_failures: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    page.on(
        "response",
        lambda response: api_failures.append(f"{response.status} {response.url}")
        if response.status >= 400 and "/api/" in response.url
        else None,
    )
    return console_errors, api_failures


def _browser_request(page, url: str, *, method: str = "GET", body: dict | None = None) -> dict:
    """Make an authorized same-origin request from the real browser page."""
    result = page.evaluate(
        """
        async ({url, method, body}) => {
          const options = {method, credentials: "same-origin"};
          if (body !== null) {
            options.headers = {
              "Content-Type": "application/json",
              "Idempotency-Key": crypto.randomUUID(),
            };
            options.body = JSON.stringify(body);
          }
          const response = await fetch(url, options);
          return {
            status: response.status,
            contentType: response.headers.get("content-type"),
            body: await response.text(),
          };
        }
        """,
        {"url": url, "method": method, "body": body},
    )
    try:
        result["json"] = json.loads(result["body"])
    except (TypeError, json.JSONDecodeError):
        result["json"] = None
    return result


def _assessment_for_class(owner, course, question, *, title: str):
    assessment = create_assessment(
        actor=owner,
        data={
            "title": title,
            "course_id": course.id,
            "settings": {"audience": AssessmentRun.Audience.CLASS},
            "items": [{"revision_id": question.current_revision_id, "points": "2"}],
        },
    )
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


@pytest.mark.django_db(transaction=True)
def test_chromium_teacher_creates_previews_and_recovers_builder_api(live_server):
    teacher = get_user_model().objects.create_user(
        username=f"task49-builder-{uuid4().hex[:8]}", password="password"
    )
    cookie = _session_cookie(teacher)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
        console_errors, api_failures = _listeners(page)
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:flow-builder')}?lang=en")
        page.get_by_role("button", name=re.compile(r"Create lesson$"), exact=True).wait_for()

        page.once("dialog", lambda dialog: dialog.accept("Matrix lesson"))
        page.get_by_role("button", name=re.compile(r"Create lesson$"), exact=True).click()
        page.get_by_role("heading", name="Matrix lesson", exact=True).wait_for()

        page.get_by_role("button", name=re.compile(r"Add step$"), exact=True).click()
        form = page.locator(".lc-builder-step-form")
        form.locator("input").first.fill("Matrix Markdown")
        form.locator("select").first.select_option("liveclassroom.markdown")
        form.locator("textarea").first.fill("# Matrix content\n\nThis teacher authored content is previewable.")
        with page.expect_response(
            lambda response: response.request.method == "POST" and "/steps/" in response.url
        ) as saved:
            form.get_by_role("button", name="Save step", exact=True).click()
        assert saved.value.status == 201

        card = page.locator(".lc-builder-step-card").filter(has_text="Matrix Markdown")
        card.get_by_role("button", name="Preview", exact=True).click()
        preview = card.locator(".lc-builder-step-preview .lc-preview-markdown")
        preview.wait_for()
        assert "This teacher authored content is previewable." in preview.inner_text()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(SCREENSHOTS / "2026-09-10-task49-builder-en-desktop.png"), full_page=True)

        # A transient detail failure must remain visible and recover on the
        # next real request; the test deliberately records that one 503.
        flow_id = database_call(lambda: Flow.objects.get(created_by=teacher, title="Matrix lesson").id)
        detail_path = reverse("liveclassroom:api-v1-flow-detail", args=[flow_id])
        page.route(
            f"**{detail_path}",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "temporary builder outage"}),
            ),
        )
        page.reload()
        page.locator(".lc-builder-status-error").get_by_text(
            "temporary builder outage", exact=False
        ).wait_for()
        page.unroute(f"**{detail_path}")
        page.reload()
        page.get_by_role("heading", name="Matrix lesson", exact=True).wait_for()
        page.locator(".lc-builder-step-card").filter(has_text="Matrix Markdown").wait_for()

        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="Switch language / 切换语言", exact=True).click()
        page.get_by_role("heading", name="教学教案可视化编辑器", exact=True).wait_for()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(SCREENSHOTS / "2026-09-10-task49-builder-zh-mobile.png"), full_page=True)
        assert len(console_errors) == 1 and "503" in console_errors[0]
        assert len(api_failures) == 1 and "503" in api_failures[0]
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_chromium_native_deck_current_next_separates_display_and_student_channels(live_server, vaultpub_apps):
    teacher = get_user_model().objects.create_user(
        username=f"task49-deck-{uuid4().hex[:8]}", password="password"
    )
    deck = create_deck(
        actor=teacher,
        data={
            "title": "Matrix deck",
            "slides": [
                {"markdown": "# First slide", "notes": "Teacher-only cue."},
                {"markdown": "# Second slide", "notes": "Second cue."},
            ],
        },
    )
    snapshot = create_deck_snapshot(actor=teacher, deck=deck, expected_version=deck.version)
    session = create_instant_session(owner=teacher, title="Matrix presentation")
    start_session(session=session, actor=teacher)
    cookie = _session_cookie(teacher)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    manager, browser = _chromium_or_skip()
    try:
        teacher_page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
        teacher_errors, teacher_failures = _listeners(teacher_page)
        teacher_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        teacher_page.goto(
            f"{live_server.url}{reverse('liveclassroom:teacher-console', args=[session.id])}"
        )
        present_url = reverse("liveclassroom:api-v1-session-deck-present", args=[session.id])
        presented = _browser_request(
            teacher_page,
            f"{live_server.url}{present_url}",
            method="POST",
            body={"snapshot_id": snapshot.id, "channels": ["display", "participants"], "allow_review": True},
        )
        assert presented["status"] == 200, presented
        teacher_page.reload()
        teacher_page.locator(".lc-native-deck").wait_for()
        teacher_page.locator(".lc-native-deck-header").get_by_text("1 / 2", exact=True).wait_for()
        teacher_page.get_by_text("Teacher-only cue.", exact=True).wait_for()

        display = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
        display_errors, display_failures = _listeners(display)
        display.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        display.goto(f"{live_server.url}{reverse('liveclassroom:classroom-display', args=[session.id])}")
        display.locator(".lc-native-deck").wait_for()
        display.locator(".lc-native-deck-header").get_by_text("1 / 2", exact=True).wait_for()
        assert display.locator(".lc-native-deck-notes").count() == 0

        guest = browser.new_page(viewport={"width": 390, "height": 844}, locale="zh-CN")
        guest_errors, guest_failures = _listeners(guest)
        guest.goto(f"{live_server.url}{reverse('liveclassroom:student-session', args=[session.id])}")
        guest.locator("[data-liveclassroom-join-prompt] input").fill("Matrix guest")
        with guest.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(reverse("liveclassroom:api-v1-join", args=[session.join_code]))
        ) as joined:
            guest.get_by_role("button", name="Join classroom", exact=True).click()
        assert joined.value.status == 201
        guest.locator(".lc-native-deck").wait_for()
        guest.locator(".lc-native-deck-header").get_by_text("1 / 2", exact=True).wait_for()
        assert guest.locator(".lc-native-deck-notes").count() == 0
        assert guest.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

        # NativeDeckView handles arrow keys on the teacher surface.  The
        # display channel moves while the independently held student channel
        # remains on its first slide until explicitly brought forward.
        teacher_page.locator(".lc-native-deck").focus()
        with teacher_page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(
                reverse("liveclassroom:api-v1-session-presentation", args=[session.id])
            )
        ) as moved:
            teacher_page.keyboard.press("ArrowRight")
        assert moved.value.status == 200
        teacher_page.reload()
        teacher_page.locator(".lc-native-deck-header").get_by_text("2 / 2", exact=True).wait_for()
        display.reload()
        display.locator(".lc-native-deck-header").get_by_text("2 / 2", exact=True).wait_for()
        guest.reload()
        guest.locator(".lc-native-deck-header").get_by_text("1 / 2", exact=True).wait_for()
        guest.screenshot(path=str(SCREENSHOTS / "2026-09-10-task49-deck-zh-mobile.png"), full_page=True)
        # LiveServer is synchronous and has no ASGI websocket route.  Its
        # handshake errors are expected harness evidence; HTTP API failures
        # remain strict, apart from the guest's deliberate pre-join 403 probe.
        for errors in (teacher_errors, display_errors, guest_errors):
            assert all(
                "WebSocket connection" in error
                or "status code: 403" in error
                or "status code: 404" in error
                or "403 (Forbidden)" in error
                or "404 (Not Found)" in error
                for error in errors
            ), errors
        assert teacher_failures == [] and display_failures == []
        assert all("403" in failure and "/state/" in failure for failure in guest_failures), guest_failures
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_chromium_student_review_and_teacher_progress_summary_are_private(live_server):
    owner, learner, other, _question, review_run, submitted, _item = review_fixture()
    course = Course.objects.create(
        title=f"Matrix class {uuid4().hex[:8]}",
        slug=f"matrix-class-{uuid4().hex[:12]}",
        created_by=owner,
    )
    CourseMembership.objects.create(course=course, user=learner, role=CourseMembership.Role.STUDENT)
    question = create_activity_definition(
        owner=owner,
        title="Matrix progress question",
        type_key="single_choice",
        definition={"prompt": "Choose A", "options": [{"id": "a", "text": "A"}], "answer": "a"},
    )
    class_run = _assessment_for_class(owner, course, question, title="Matrix class assessment")
    active_attempt, _ = start_or_resume_attempt(actor=learner, run=class_run, request_id=uuid4())
    student_cookie = _session_cookie(learner)
    owner_cookie = _session_cookie(owner)
    other_cookie = _session_cookie(other)
    history_url = reverse("liveclassroom:api-v1-assessment-history")
    review_url = reverse("liveclassroom:api-v1-attempt-review", args=[submitted.public_id])
    result_url = reverse("liveclassroom:api-v1-attempt-result", args=[submitted.public_id])
    progress_url = reverse("liveclassroom:api-v1-assessment-run-progress", args=[class_run.public_id])
    summary_url = reverse("liveclassroom:api-v1-course-grade-summary", args=[course.id])
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    manager, browser = _chromium_or_skip()
    try:
        student = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
        student_errors, student_failures = _listeners(student)
        student.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": student_cookie, "url": live_server.url}]
        )
        student.goto(
            f"{live_server.url}{reverse('liveclassroom:assessment-attempt', args=[review_run.public_id])}"
        )
        student.get_by_role("heading", name=review_run.title, exact=True).wait_for()
        history = _browser_request(student, f"{live_server.url}{history_url}")
        review = _browser_request(student, f"{live_server.url}{review_url}")
        result = _browser_request(student, f"{live_server.url}{result_url}")
        assert history["status"] == review["status"] == result["status"] == 200
        assert history["json"]["total"] >= 1
        assert review["json"]["items"][0]["saved_answer"] == {"choice": "a"}
        assert review["json"]["items"][0]["released"] == {
            "scores": False,
            "answers": False,
            "explanations": False,
            "comments": False,
        }
        assert "answer_key" not in review["json"]["items"][0]["result"]
        assert "answer_key" not in result["json"]["items"][0]
        student.screenshot(path=str(SCREENSHOTS / "2026-09-10-task49-review-en-desktop.png"), full_page=True)

        owner_page = browser.new_page(viewport={"width": 390, "height": 844}, locale="zh-CN")
        owner_errors, owner_failures = _listeners(owner_page)
        owner_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": owner_cookie, "url": live_server.url}]
        )
        owner_page.goto(f"{live_server.url}{reverse('liveclassroom:assessment-workspace')}?lang=zh-Hans")
        owner_page.get_by_role("heading", name="测验编辑器", exact=True).wait_for()
        progress = _browser_request(owner_page, f"{live_server.url}{progress_url}")
        summary = _browser_request(owner_page, f"{live_server.url}{summary_url}")
        assert progress["status"] == summary["status"] == 200
        assert progress["json"]["students"][0]["student_username"] == learner.username
        assert progress["json"]["students"][0]["status"] == "in_progress"
        row = summary["json"]["students"][0]
        assert row["student_username"] == learner.username
        assert "answer" not in json.dumps(summary["json"], ensure_ascii=False)
        assert owner_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        owner_page.screenshot(path=str(SCREENSHOTS / "2026-09-10-task49-progress-zh-mobile.png"), full_page=True)

        intruder = browser.new_page(viewport={"width": 390, "height": 844}, locale="en-US")
        intruder.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": other_cookie, "url": live_server.url}]
        )
        intruder.goto(f"{live_server.url}{reverse('liveclassroom:assessment-attempt', args=[review_run.public_id])}")
        intruder.get_by_role("heading", name=review_run.title, exact=True).wait_for()
        assert _browser_request(intruder, f"{live_server.url}{review_url}")["status"] == 404
        assert _browser_request(intruder, f"{live_server.url}{result_url}")["status"] == 404
        assert _browser_request(intruder, f"{live_server.url}{progress_url}")["status"] == 404
        assert _browser_request(intruder, f"{live_server.url}{summary_url}")["status"] == 404
        assert student_errors == [] and owner_errors == []
        assert student_failures == [] and owner_failures == []
        assert active_attempt.user_id == learner.id
    finally:
        browser.close()
        manager.stop()
