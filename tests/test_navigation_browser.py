"""Browser-level URL and Back behavior for the navigation surfaces."""

import re

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import AssessmentAttempt, Course, CourseMembership, Flow, TeachingCourse
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.classroom import (
    create_activity_definition,
    create_instant_session,
    launch_item,
    publish_activity_to_audiences,
    start_session,
)
from liveclassroom.services.decks import create_deck
from liveclassroom.services.flows import create_flow
from tests.test_browser_workflows import _chromium_or_skip, database_call


def _cookie(user):
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def _assessment_run(owner, *, navigation: str):
    questions = [
        create_activity_definition(
            owner=owner,
            title=f"{navigation} navigation question {position}",
            type_key="short_text",
            definition={"prompt": f"{navigation} prompt {position}"},
        )
        for position in range(1, 3)
    ]
    assessment = create_assessment(
        actor=owner,
        data={
            "title": f"{navigation} browser navigation",
            "settings": {"navigation": navigation, "max_attempts": 1, "audience": "authenticated_link"},
            "items": [{"revision_id": question.current_revision_id} for question in questions],
        },
    )
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


def _attempt_item_keys(run, learner):
    attempt = AssessmentAttempt.objects.get(run=run, user=learner)
    return list(attempt.items.order_by("position").values_list("key", flat=True))


@pytest.mark.django_db(transaction=True)
def test_mobile_shell_drawer_closes_with_escape_and_backdrop(live_server):
    teacher = get_user_model().objects.create_user(username="navigation-mobile-shell", password="password")
    cookie = database_call(lambda: _cookie(teacher))
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:home')}")
        toggle = page.get_by_role("button", name="Toggle navigation", exact=True)
        toggle.click()
        page.locator("[data-classroom-shell]").wait_for()
        page.wait_for_function("document.querySelector('[data-classroom-shell]')?.dataset.drawer === 'open'")
        drawer_close = page.get_by_role("button", name="Close navigation", exact=True)
        drawer_close.wait_for()
        page.keyboard.press("Escape")
        page.wait_for_function("document.querySelector('[data-classroom-shell]')?.dataset.drawer === 'closed'")
        assert page.evaluate("document.activeElement?.classList.contains('lc-shell-toggle')")

        toggle.click()
        page.wait_for_function("document.querySelector('[data-classroom-shell]')?.dataset.drawer === 'open'")
        page.locator(".lc-shell-drawer-dismiss").click(position={"x": 4, "y": 4})
        page.wait_for_function("document.querySelector('[data-classroom-shell]')?.dataset.drawer === 'closed'")
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_assessment_question_history_is_local_and_never_replays_navigation_commands(live_server):
    users = get_user_model()
    owner = users.objects.create_user(username="navigation-assessment-owner", password="password")
    learner = users.objects.create_user(username="navigation-assessment-learner", password="password")
    free_run = _assessment_run(owner, navigation="free")
    forward_run = _assessment_run(owner, navigation="forward_only")
    cookie = database_call(lambda: _cookie(learner))
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        command_posts: list[str] = []
        page.on(
            "request",
            lambda request: command_posts.append(request.url)
            if request.method == "POST"
            else None,
        )

        free_url = reverse("liveclassroom:assessment-attempt", args=[free_run.public_id])
        page.goto(f"{live_server.url}{free_url}")
        page.get_by_role("button", name="Start / resume assessment", exact=True).click()
        page.get_by_text("free prompt 1", exact=True).wait_for()
        free_items = database_call(lambda: _attempt_item_keys(free_run, learner))
        first_key, second_key = map(str, free_items)
        command_posts.clear()

        page.locator(".lc-student-assessment-nav button").nth(1).click()
        page.wait_for_function(
            "(key) => new URL(window.location.href).searchParams.get('item') === key",
            arg=second_key,
        )
        page.get_by_text("free prompt 2", exact=True).wait_for()
        page.go_back()
        page.wait_for_function("!new URL(window.location.href).searchParams.has('item')")
        page.get_by_text("free prompt 1", exact=True).wait_for()
        page.go_forward()
        page.wait_for_function(
            "(key) => new URL(window.location.href).searchParams.get('item') === key",
            arg=second_key,
        )
        page.get_by_text("free prompt 2", exact=True).wait_for()
        page.goto(f"{live_server.url}{free_url}?item={second_key}")
        page.get_by_text("free prompt 2", exact=True).wait_for()
        assert command_posts == []

        forward_url = reverse("liveclassroom:assessment-attempt", args=[forward_run.public_id])
        page.goto(f"{live_server.url}{forward_url}")
        page.get_by_role("button", name="Start / resume assessment", exact=True).click()
        page.get_by_text("forward_only prompt 1", exact=True).wait_for()
        forward_items = database_call(lambda: _attempt_item_keys(forward_run, learner))
        first_forward, second_forward = map(str, forward_items)
        command_posts.clear()
        page.goto(f"{live_server.url}{forward_url}?item={second_forward}")
        page.get_by_text("forward_only prompt 1", exact=True).wait_for()
        page.wait_for_function(
            "(key) => new URL(window.location.href).searchParams.get('item') === key",
            arg=first_forward,
        )
        assert page.get_by_text("That question is not available", exact=False).is_visible()
        assert command_posts == []

        page.get_by_role("button", name="Next", exact=True).click()
        page.wait_for_function(
            "(key) => new URL(window.location.href).searchParams.get('item') === key",
            arg=second_forward,
        )
        page.get_by_text("forward_only prompt 2", exact=True).wait_for()
        assert [url for url in command_posts if url.endswith("/advance/")]
        assert len(command_posts) == 1
    finally:
        browser.close()
        manager.stop()


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
def test_paginated_course_browse_uses_page_history_without_posting(live_server):
    teacher = get_user_model().objects.create_user(username="navigation-page-teacher", password="password")
    for index in range(26):
        TeachingCourse.objects.create(title=f"Paged teaching course {index:02d}", created_by=teacher)
    cookie = database_call(lambda: _cookie(teacher))
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        command_posts: list[str] = []
        page.on(
            "request",
            lambda request: command_posts.append(request.url)
            if request.method == "POST"
            else None,
        )
        courses_url = reverse("liveclassroom:teacher-courses")
        page.goto(f"{live_server.url}{courses_url}?page=2")
        page.locator('[data-browse-page="2"]').first.wait_for()
        course_section = page.locator(".lc-learning-section").filter(
            has=page.get_by_role("heading", name="Teaching courses", exact=True)
        )
        course_section.get_by_role("button", name="Previous", exact=True).click()
        page.wait_for_function("new URL(window.location.href).searchParams.get('page') === '1'")
        course_section.get_by_role("button", name="Next", exact=True).click()
        page.wait_for_function("new URL(window.location.href).searchParams.get('page') === '2'")
        page.go_back()
        page.wait_for_function("new URL(window.location.href).searchParams.get('page') === '1'")
        page.locator('[data-browse-page="1"]').first.wait_for()
        assert command_posts == []
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


@pytest.mark.django_db(transaction=True)
def test_teacher_console_inspection_history_does_not_replay_live_commands(live_server):
    teacher = get_user_model().objects.create_user(username="navigation-console-teacher", password="password")
    first_definition = create_activity_definition(
        owner=teacher,
        title="First discussion",
        type_key="liveclassroom.markdown",
        definition={"markdown": "First"},
    )
    second_definition = create_activity_definition(
        owner=teacher,
        title="Second discussion",
        type_key="liveclassroom.markdown",
        definition={"markdown": "Second"},
    )
    session = create_instant_session(owner=teacher, title="Navigation classroom")
    start_session(session=session, actor=teacher)
    first = launch_item(session=session, item=first_definition, actor=teacher)
    publish_activity_to_audiences(session=session, activity=first, channels=["display", "participants"], actor=teacher)
    second = launch_item(session=session, item=second_definition, actor=teacher)
    publish_activity_to_audiences(session=session, activity=second, channels=["display", "participants"], actor=teacher)
    cookie = database_call(lambda: _cookie(teacher))
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        command_posts: list[str] = []
        page.on(
            "request",
            lambda request: command_posts.append(request.url)
            if request.method == "POST"
            else None,
        )
        page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-console', args=[session.id])}")
        page.wait_for_function(
            "(id) => new URL(window.location.href).searchParams.get('activity') === String(id)",
            arg=second.id,
        )
        results_panel = page.locator('[data-console-panel="results"]')
        results_panel.locator("summary").click()
        page.wait_for_function("new URL(window.location.href).searchParams.get('panel') === 'results'")
        results_panel.locator("select").select_option(str(first.id))
        page.wait_for_function(
            "(id) => new URL(window.location.href).searchParams.get('activity') === String(id)",
            arg=first.id,
        )
        page.go_back()
        page.wait_for_function(
            "(id) => new URL(window.location.href).searchParams.get('activity') === String(id)",
            arg=second.id,
        )
        assert page.evaluate("new URL(window.location.href).searchParams.get('panel')") == "results"
        page.go_back()
        page.wait_for_function("new URL(window.location.href).searchParams.get('panel') === null")
        assert page.evaluate("new URL(window.location.href).searchParams.get('activity')") == str(second.id)
        assert not results_panel.locator("select").is_visible()
        assert command_posts == []
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_flow_builder_draft_guards_shell_navigation_and_can_save_before_leaving(live_server):
    teacher = get_user_model().objects.create_user(username="navigation-flow-guard-teacher", password="password")
    flow = create_flow(title="Guarded lesson", creator=teacher)
    cookie = database_call(lambda: _cookie(teacher))
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        builder_url = reverse("liveclassroom:flow-builder-detail", args=[flow.id])
        page.goto(f"{live_server.url}{builder_url}")
        page.get_by_role("heading", name="Guarded lesson", exact=True).wait_for()

        page.get_by_role("button", name=re.compile(r"Add step$"), exact=True).click()
        form = page.locator(".lc-builder-step-form")
        form.locator("select").first.select_option("liveclassroom.markdown")
        form.locator("textarea").first.fill("Draft prompt")
        home = page.get_by_role("link", name="Home", exact=True)
        home.click()

        dialog = page.get_by_role("dialog", name="Unsaved changes")
        dialog.wait_for()
        assert page.url.endswith(builder_url)
        dialog.get_by_role("button", name="Stay", exact=True).click()
        dialog.wait_for(state="detached")
        assert page.url.endswith(builder_url)
        assert form.locator("textarea").first.input_value() == "Draft prompt"

        home.click()
        dialog.wait_for()
        step_url = reverse("liveclassroom:api-v1-flow-add-step", args=[flow.id])
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(step_url)
        ) as saved:
            dialog.get_by_role("button", name="Save and leave", exact=True).click()
        assert saved.value.status == 201
        page.wait_for_url(f"**{reverse('liveclassroom:home')}*")

        def step_count():
            return Flow.objects.get(pk=flow.id).steps.count()

        assert database_call(step_count) == 1
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_student_review_selection_has_history_without_replaying_session_commands(live_server):
    teacher = get_user_model().objects.create_user(username="navigation-student-teacher", password="password")
    first_definition = create_activity_definition(
        owner=teacher,
        title="Previous discussion",
        type_key="liveclassroom.markdown",
        definition={"markdown": "Previous classroom content"},
    )
    second_definition = create_activity_definition(
        owner=teacher,
        title="Current discussion",
        type_key="liveclassroom.markdown",
        definition={"markdown": "Current classroom content"},
    )
    session = create_instant_session(owner=teacher, title="Student review classroom")
    start_session(session=session, actor=teacher)
    first = launch_item(session=session, item=first_definition, actor=teacher)
    publish_activity_to_audiences(
        session=session,
        activity=first,
        channels=["participants"],
        actor=teacher,
        allow_review=True,
    )
    second = launch_item(session=session, item=second_definition, actor=teacher)
    publish_activity_to_audiences(
        session=session,
        activity=second,
        channels=["participants"],
        actor=teacher,
    )

    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        command_posts: list[str] = []
        page.on(
            "request",
            lambda request: command_posts.append(request.url)
            if request.method == "POST"
            else None,
        )
        session_url = reverse("liveclassroom:student-session", args=[session.id])
        page.goto(f"{live_server.url}{session_url}?activity=999999")
        page.locator("[data-liveclassroom-join-prompt] input").fill("Ada")
        page.get_by_role("button", name="Join classroom", exact=True).click()
        page.locator("#student-title").wait_for()
        page.wait_for_function("!new URL(window.location.href).searchParams.has('activity')")
        assert page.get_by_text("This review is no longer available", exact=False).is_visible()
        command_posts.clear()

        history = page.locator("[data-liveclassroom-history]")
        history.locator("summary").click()
        review_button = page.locator(f"[data-liveclassroom-review-activity='{first.id}']")
        review_button.wait_for()
        review_button.click()
        page.wait_for_function(
            "(id) => new URL(window.location.href).searchParams.get('activity') === String(id)",
            arg=first.id,
        )
        page.get_by_text("Previous classroom content", exact=True).first.wait_for()
        assert page.get_by_text("Current classroom content", exact=True).count() == 0

        page.go_back()
        page.wait_for_function("!new URL(window.location.href).searchParams.has('activity')")
        page.get_by_text("Current classroom content", exact=True).first.wait_for()
        page.go_forward()
        page.wait_for_function(
            "(id) => new URL(window.location.href).searchParams.get('activity') === String(id)",
            arg=first.id,
        )
        page.get_by_text("Previous classroom content", exact=True).first.wait_for()
        assert command_posts == []
    finally:
        browser.close()
        manager.stop()
