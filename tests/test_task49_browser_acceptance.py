"""Additional real Chromium evidence for the integrated Task 49 paths.

These checks deliberately keep the browser as the actor: the teacher and
student pages make the requests, while database assertions verify the durable
result after the visible interaction.  The package currently has no general
results page, so export and release assertions use same-origin browser fetches
against the authorized API endpoints.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from liveclassroom.ai import AIMessage, AIModel
from liveclassroom.models import (
    ActivityDefinition,
    AssessmentAttempt,
    AssessmentItemGrade,
    AuthoringDraft,
)
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.flows import create_flow
from liveclassroom.services.manual_grading import list_manual_grading_items
from tests.test_assessment_exports import _fixture as export_fixture
from tests.test_browser_workflows import _chromium_or_skip, database_call
from tests.test_manual_grading import _essay_attempt

SCREENSHOTS = Path(".local/2026-09-09/screenshots/task49")


def _session_cookie(user) -> str:
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def _browser_listeners(page):
    console_errors: list[str] = []
    api_failures: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on(
        "response",
        lambda response: api_failures.append(f"{response.status} {response.url}")
        if response.status >= 400 and "/api/" in response.url
        else None,
    )
    return console_errors, api_failures


def _assert_browser_clean(console_errors: list[str], api_failures: list[str]) -> None:
    assert console_errors == [], f"browser console errors: {console_errors}"
    assert api_failures == [], f"browser API failures: {api_failures}"


def _browser_fetch(page, url: str, *, method: str = "GET", body: dict | None = None) -> dict:
    return page.evaluate(
        """
        async ({url, method, body}) => {
          const options = {method, credentials: "same-origin"};
          if (body !== null) {
            options.headers = {"Content-Type": "application/json"};
            options.body = JSON.stringify(body);
          }
          const response = await fetch(url, options);
          return {
            status: response.status,
            contentType: response.headers.get("content-type"),
            disposition: response.headers.get("content-disposition"),
            body: await response.text(),
          };
        }
        """,
        {"url": url, "method": method, "body": body},
    )


class BrowserDraftBackend:
    """A deterministic provider used only to exercise the browser contract."""

    key = "browser-draft"

    def list_models(self, *, request=None):
        return [AIModel("browser-model", "Browser deterministic model")]

    def complete(self, messages, *, model, request=None, attachments=None):
        envelope = {
            "artifact_type": "question",
            "payload": {
                "title": "AI accepted browser question",
                "type_key": "liveclassroom.single_choice",
                "definition": {
                    "prompt": "Which result is deterministic?",
                    "options": [{"id": "A", "text": "The recorded answer"}, {"id": "B", "text": "A secret"}],
                    "answer": "A",
                },
            },
        }
        return AIMessage("assistant", json.dumps(envelope))


def _synchronous_dispatcher(*, job_id, actor, request=None, options=None):
    from liveclassroom.services.authoring import run_authoring_job

    run_authoring_job(job_id=job_id, actor=actor, request=request, options=options)


@pytest.mark.django_db(transaction=True)
def test_teacher_generates_reviews_and_accepts_ai_draft_in_bilingual_builder(live_server):
    teacher = get_user_model().objects.create_user(username="task49-ai-browser", password="password")
    flow = create_flow(title="AI browser lesson", creator=teacher)
    cookie = _session_cookie(teacher)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    manager, browser = _chromium_or_skip()
    try:
        with override_settings(
            LIVECLASSROOM={
                "AI_BACKENDS": {"browser-draft": BrowserDraftBackend()},
                "AI_JOB_DISPATCHER": _synchronous_dispatcher,
            }
        ):
            page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
            console_errors, api_failures = _browser_listeners(page)
            page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
            page.goto(f"{live_server.url}{reverse('liveclassroom:flow-builder-detail', args=[flow.id])}")
            page.get_by_role("heading", name="AI Authoring Assistant", exact=True).wait_for()
            model = page.locator(".lc-ai-control-group").nth(1).locator("select")
            model.select_option("browser-draft:browser-model")
            page.locator(".lc-ai-control-group").nth(2).locator("select").select_option("question")
            page.locator(".lc-ai-input").fill("Draft one deterministic question for review.")
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and "/authoring/threads/" in response.url
                and response.url.endswith("/messages/")
            ) as queued:
                page.get_by_role("button", name="Ask AI", exact=True).click()
            assert queued.value.status == 202
            draft_card = page.locator(".lc-ai-draft")
            draft_card.get_by_text("question", exact=True).wait_for()
            draft_card.get_by_text("proposed", exact=True).wait_for()
            assert "AI accepted browser question" in draft_card.locator("pre").inner_text()
            with page.expect_response(
                lambda response: response.request.method == "POST" and response.url.endswith("/accept/")
            ) as accepted:
                draft_card.get_by_role("button", name="Accept / 接受", exact=True).click()
            assert accepted.value.status == 200
            page.get_by_text("Draft accepted / 草稿已接受", exact=True).wait_for()
            draft_card.get_by_text("accepted", exact=True).wait_for()
            assert database_call(
                lambda: (
                    AuthoringDraft.objects.get(status=AuthoringDraft.Status.ACCEPTED).accepted_object_type,
                    ActivityDefinition.objects.filter(owner=teacher, title="AI accepted browser question").count(),
                )
            ) == ("question", 1)
            page.screenshot(path=str(SCREENSHOTS / "2026-09-10-task49-ai-review-en-desktop.png"), full_page=True)

            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(
                f"{live_server.url}{reverse('liveclassroom:flow-builder-detail', args=[flow.id])}?lang=zh-Hans"
            )
            page.get_by_role("heading", name="教学教案可视化编辑器", exact=True).wait_for()
            page.get_by_role("heading", name="AI 课件助手", exact=True).wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(SCREENSHOTS / "2026-09-10-task49-ai-review-zh-mobile.png"), full_page=True)
            _assert_browser_clean(console_errors, api_failures)
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_teacher_manually_grades_real_submitted_essay_in_english_and_chinese(live_server):
    owner, learner, run, attempt, item = _essay_attempt()
    cookie = _session_cookie(owner)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
        console_errors, api_failures = _browser_listeners(page)
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        page.goto(f"{live_server.url}{reverse('liveclassroom:assessment-workspace')}")
        page.get_by_role("heading", name="Manual grading queue", exact=True).wait_for()
        card = page.locator(".lc-manual-grade-card")
        card.get_by_text(learner.username, exact=True).wait_for()
        card.get_by_label("Awarded points", exact=True).fill("3")
        card.locator("label").filter(has_text="Comment").locator("textarea").fill("Clear evidence.")
        card.locator("label").filter(has_text="Reason").locator("input").fill("Reviewed in browser.")
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith("/manual-grade/")
        ) as graded:
            card.get_by_role("button", name="Save grade", exact=True).click()
        assert graded.value.status == 200
        page.get_by_text("No submitted responses need grading.", exact=True).wait_for()
        assert database_call(
            lambda: (
                AssessmentItemGrade.objects.get(item_id=item.pk).awarded_points,
                list_manual_grading_items(owner, run_id=run.public_id),
            )
        ) == (3, [])
        page.screenshot(path=str(SCREENSHOTS / "2026-09-10-task49-manual-grade-en-desktop.png"), full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{live_server.url}{reverse('liveclassroom:assessment-workspace')}?lang=zh-Hans")
        page.get_by_role("heading", name="人工评分队列", exact=True).wait_for()
        page.get_by_text("没有待评分的已提交答案。", exact=True).wait_for()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(SCREENSHOTS / "2026-09-10-task49-manual-grade-zh-mobile.png"), full_page=True)
        _assert_browser_clean(console_errors, api_failures)
    finally:
        browser.close()
        manager.stop()


def _timed_exam(owner):
    question = create_activity_definition(
        owner=owner,
        title="Timed browser question",
        type_key="single_choice",
        definition={
            "prompt": "Which answer survives a closed browser?",
            "options": [{"id": "a", "text": "The server"}, {"id": "b", "text": "The tab"}],
            "answer": "a",
        },
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Closed browser exam",
            "settings": {"mode": "exam", "duration_seconds": 2, "audience": "authenticated_link"},
            "items": [{"revision_id": question.current_revision_id}],
        },
    )
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


@pytest.mark.django_db(transaction=True)
def test_timed_exam_is_finalized_by_server_after_student_browser_closes(live_server):
    owner = get_user_model().objects.create_user(username="task49-timing-owner", password="password")
    student = get_user_model().objects.create_user(username="task49-timing-student", password="password")
    run = _timed_exam(owner)
    cookie = _session_cookie(student)
    manager, browser = _chromium_or_skip()
    try:
        page = browser.new_page(viewport={"width": 390, "height": 844}, locale="en-US")
        console_errors, api_failures = _browser_listeners(page)
        page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}])
        attempt_url = reverse("liveclassroom:assessment-attempt", args=[run.public_id])
        page.goto(f"{live_server.url}{attempt_url}")
        page.get_by_role("heading", name="Closed browser exam", exact=True).wait_for()
        page.get_by_role("button", name="Start / resume assessment", exact=True).click()
        page.get_by_text("Which answer survives a closed browser?", exact=True).wait_for()
        page.close()

        # The browser is gone. The next authenticated attempt read is the
        # server recovery path and finalizes the due attempt by server time.
        time.sleep(3)
        attempt = database_call(lambda: AssessmentAttempt.objects.get(run=run, user=student))
        check_page = browser.new_page(viewport={"width": 390, "height": 844}, locale="en-US")
        check_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie, "url": live_server.url}]
        )
        check_page.goto(f"{live_server.url}{attempt_url}")
        check_page.get_by_role("button", name="Start / resume assessment", exact=True).click()
        check_page.get_by_role("heading", name="Assessment submitted", exact=True).wait_for()
        detail = _browser_fetch(
            check_page,
            f"{live_server.url}{reverse('liveclassroom:api-v1-attempt-detail', args=[attempt.public_id])}",
        )
        assert detail["status"] == 200
        assert json.loads(detail["body"])["status"] == "submitted"
        assert database_call(
            lambda: AssessmentAttempt.objects.get(pk=attempt.pk).finalization_reason
        ) == "expired"
        assert check_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        _assert_browser_clean(console_errors, api_failures)
        check_page.close()
    finally:
        browser.close()
        manager.stop()


@pytest.mark.django_db(transaction=True)
def test_chromium_downloads_authorized_teacher_and_student_result_exports(live_server):
    owner, student, _other, _course, run, attempt = export_fixture()
    owner_cookie = _session_cookie(owner)
    student_cookie = _session_cookie(student)
    run.manifest["settings"]["release_policy"]["answers"] = "manual"
    run.manifest["settings"]["release_policy"]["comments"] = "manual"
    run.save(update_fields=["manifest"])
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    manager, browser = _chromium_or_skip()
    try:
        teacher = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
        console_errors, api_failures = _browser_listeners(teacher)
        teacher.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": owner_cookie, "url": live_server.url}]
        )
        teacher.goto(f"{live_server.url}{reverse('liveclassroom:assessment-workspace')}")
        teacher.get_by_role("heading", name="Assessment builder", exact=True).wait_for()
        csv_url = (
            f"{live_server.url}"
            f"{reverse('liveclassroom:api-v1-assessment-run-results-export', args=[run.public_id])}"
            "?format=csv&details=true"
        )
        with teacher.expect_download() as download_info:
            teacher.evaluate(
                """
                (url) => {
                  const link = document.createElement("a");
                  link.href = url;
                  link.click();
                }
                """,
                csv_url,
            )
        download = download_info.value
        assert download.suggested_filename.endswith(".csv")
        csv_body = Path(download.path()).read_text(encoding="utf-8")
        assert "'=student" in csv_body
        assert "private key" not in csv_body

        json_url = (
            f"{live_server.url}"
            f"{reverse('liveclassroom:api-v1-assessment-run-results-export', args=[run.public_id])}"
            "?format=json&details=true"
        )
        teacher_json = _browser_fetch(teacher, json_url)
        assert teacher_json["status"] == 200
        assert teacher_json["disposition"].endswith(".json\"")
        assert json.loads(teacher_json["body"])["attempts"][0]["items"][0]["answer"] == {"choice": "a"}

        release_url = f"{live_server.url}{reverse('liveclassroom:api-v1-assessment-run-release', args=[run.public_id])}"
        released = _browser_fetch(teacher, release_url, method="POST", body={"dimension": "answers"})
        assert released["status"] == 200

        student_page = browser.new_page(viewport={"width": 390, "height": 844}, locale="zh-CN")
        student_page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": student_cookie, "url": live_server.url}]
        )
        student_page.goto(
            f"{live_server.url}{reverse('liveclassroom:assessment-attempt', args=[run.public_id])}?lang=zh-Hans"
        )
        student_page.locator("h1").wait_for()
        student_page.get_by_role("button", name="开始 / 继续测验", exact=True).click()
        student_page.get_by_role("heading", name="测验已提交", exact=True).wait_for()
        student_json_url = (
            f"{live_server.url}"
            f"{reverse('liveclassroom:api-v1-attempt-result-export', args=[attempt.public_id])}"
            "?format=json"
        )
        student_json = _browser_fetch(student_page, student_json_url)
        assert student_json["status"] == 200
        student_payload = json.loads(student_json["body"])
        assert student_payload["attempt"]["released"]["answers"] is True
        assert student_payload["attempt"]["items"][0]["answer"] == {"choice": "a"}
        student_csv = _browser_fetch(
            student_page,
            f"{live_server.url}"
            f"{reverse('liveclassroom:api-v1-attempt-result-export', args=[attempt.public_id])}"
            "?format=csv",
        )
        assert student_csv["status"] == 200
        assert "assessment-result-" in student_csv["disposition"]
        assert '""choice"":""a""' in student_csv["body"]
        assert student_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        student_page.screenshot(path=str(SCREENSHOTS / "2026-09-10-task49-export-zh-mobile.png"), full_page=True)
        _assert_browser_clean(console_errors, api_failures)
        student_page.close()
        teacher.screenshot(path=str(SCREENSHOTS / "2026-09-10-task49-export-en-desktop.png"), full_page=True)
    finally:
        browser.close()
        manager.stop()
