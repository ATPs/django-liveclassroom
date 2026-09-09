"""Browser acceptance for optional Course organization in the teacher workspace."""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import Course, CourseMembership, LiveSession, TeachingCourse
from liveclassroom.services.flows import create_flow
from tests.test_browser_workflows import _chromium_or_skip, database_call


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


@pytest.mark.django_db(transaction=True)
def test_teacher_groups_classes_without_changing_class_data(live_server):
    teacher = get_user_model().objects.create_user(username="course-workspace-teacher", password="password")
    student = get_user_model().objects.create_user(username="course-workspace-student")
    original = Course.objects.create(title="Original class", slug="original-class", created_by=teacher)
    membership = CourseMembership.objects.create(
        course=original,
        user=student,
        role=CourseMembership.Role.STUDENT,
    )
    lesson = create_flow(title="Original lesson", creator=teacher)
    lesson.associated_courses.add(original)
    retained_session = LiveSession.objects.create(teacher=teacher, course=original, title="Retained classroom")
    cookie = _session_cookie(teacher)
    screenshots = Path(".local/screenshots")
    screenshots.mkdir(parents=True, exist_ok=True)

    browser_manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        page.goto(f"{live_server.url}{reverse('liveclassroom:teacher-dashboard')}")
        page.get_by_role("heading", name="Teacher workspace", exact=True).wait_for()
        page.get_by_role("button", name="Classes", exact=True).click()
        page.get_by_role("heading", name="Courses", exact=True).wait_for()
        page.get_by_role("heading", name="Create class", exact=True).wait_for()

        for title in ("Second class", "Third class"):
            page.locator("#workspace-new-class-title").fill(title)
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith(reverse("liveclassroom:api-v1-courses"))
            ) as created_class:
                page.get_by_role("button", name="Create class", exact=True).click()
            assert created_class.value.status == 201
            page.get_by_role("heading", name=title, exact=True).wait_for()

        for title in ("Biology course", "Chemistry course"):
            page.locator("#workspace-new-course-title").fill(title)
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith(reverse("liveclassroom:api-v1-teaching-courses"))
            ) as created_course:
                page.get_by_role("button", name="Create course", exact=True).click()
            assert created_course.value.status == 201
            page.get_by_role("heading", name=title, exact=True).wait_for()

        biology = page.locator("article.lc-teaching-course").filter(has_text="Biology course")
        chemistry = page.locator("article.lc-teaching-course").filter(has_text="Chemistry course")
        attach_suffix = "/classes/"
        for class_title in ("Original class", "Second class"):
            biology.get_by_label("Choose a class", exact=True).select_option(label=class_title)
            with page.expect_response(
                lambda response: response.request.method == "POST" and response.url.endswith(attach_suffix)
            ) as attached:
                biology.get_by_role("button", name="Attach or move class", exact=True).click()
            assert attached.value.status == 200
            biology = page.locator("article.lc-teaching-course").filter(has_text="Biology course")
            chemistry = page.locator("article.lc-teaching-course").filter(has_text="Chemistry course")

        chemistry.get_by_label("Choose a class", exact=True).select_option(label="Second class")
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(attach_suffix)
        ) as moved:
            chemistry.get_by_role("button", name="Attach or move class", exact=True).click()
        assert moved.value.status == 200
        chemistry = page.locator("article.lc-teaching-course").filter(has_text="Chemistry course")
        moved_row = chemistry.locator(".lc-compact-list li").filter(has_text="Second class")
        with page.expect_response(
            lambda response: response.request.method == "DELETE" and "/classes/" in response.url
        ) as detached:
            moved_row.get_by_role("button", name="Detach", exact=True).click()
        assert detached.value.status == 200

        biology = page.locator("article.lc-teaching-course").filter(has_text="Biology course")
        page.once("dialog", lambda dialog: dialog.accept())
        with page.expect_response(
            lambda response: response.request.method == "DELETE"
            and "/teaching-courses/" in response.url
            and not response.url.endswith("/classes/")
        ) as deleted:
            biology.get_by_role("button", name="Delete course", exact=True).click()
        assert deleted.value.status == 200
        page.get_by_role("heading", name="Biology course", exact=True).wait_for(state="detached")

        chemistry = page.locator("article.lc-teaching-course").filter(has_text="Chemistry course")
        course_detail_pattern = re.compile(r"/api/v1/teaching-courses/\d+/$")
        page.route(
            course_detail_pattern,
            lambda route: route.fulfill(
                status=500,
                content_type="application/json",
                body='{"detail":"Temporary failure"}',
            )
            if route.request.method == "PATCH"
            else route.continue_(),
        )
        chemistry.get_by_label("Course title", exact=True).fill("Failed rename")
        chemistry.get_by_role("button", name="Save course", exact=True).click()
        page.get_by_role("alert").filter(has_text="Temporary failure").wait_for()
        assert page.get_by_role("heading", name="Chemistry course", exact=True).is_visible()
        page.unroute(course_detail_pattern)

        page.screenshot(path=str(screenshots / "2026-09-09-course-workspace-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.get_by_role("heading", name="Courses", exact=True).is_visible()
        assert page.get_by_role("heading", name="Create class", exact=True).is_visible()
        page.screenshot(path=str(screenshots / "2026-09-09-course-workspace-mobile.png"), full_page=True)
        with page.expect_navigation():
            page.locator(".lc-lang-switch").first.click()
        page.get_by_role("button", name="班级", exact=True).click()
        page.get_by_role("heading", name="课程", exact=True).wait_for()
        assert page.get_by_role("heading", name="创建班级", exact=True).is_visible()
        assert page.get_by_label("课程名称", exact=True).count() >= 2
        assert page.get_by_label("班级名称", exact=True).first.is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

        page.get_by_role("button", name="即时课堂", exact=True).click()
        page.get_by_role("heading", name="新建课堂", exact=True).wait_for()
        page.get_by_label("标题", exact=True).fill("No class classroom")
        page.get_by_label("此课堂所属班级", exact=True).select_option(value="")
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(reverse("liveclassroom:api-v1-session-create"))
        ) as created_session:
            page.get_by_role("button", name="创建课堂", exact=True).click()
        assert created_session.value.status == 201
        page.wait_for_url(re.compile(r"/teacher/sessions/\d+/$"))

        def assert_preserved():
            original.refresh_from_db()
            assert original.teaching_course_id is None
            assert CourseMembership.objects.filter(pk=membership.pk, course=original, user=student).exists()
            assert lesson.associated_courses.filter(pk=original.pk).exists()
            assert LiveSession.objects.filter(pk=retained_session.pk, course=original).exists()
            assert Course.objects.filter(created_by=teacher).count() == 3
            assert list(TeachingCourse.objects.filter(created_by=teacher).values_list("title", flat=True)) == [
                "Chemistry course"
            ]
            remaining = TeachingCourse.objects.get(created_by=teacher)
            assert not remaining.cohorts.exists()
            assert LiveSession.objects.get(title="No class classroom").course_id is None

        database_call(assert_preserved)
    finally:
        browser.close()
        browser_manager.stop()
