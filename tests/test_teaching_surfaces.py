"""Tests for bilingual teaching surfaces, language switching, and rich renderers."""

from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from liveclassroom.models import Flow, LiveSession


@pytest.fixture
def teacher_user():
    return get_user_model().objects.create_user(username="prof_teacher", password="password123")


@pytest.fixture
def session_with_flow(teacher_user):
    flow = Flow.objects.create(title="Biology Lecture", created_by=teacher_user)
    session = LiveSession.objects.create(
        teacher=teacher_user,
        flow=flow,
        title="Cell Biology 101",
        join_code="BIO999",
    )
    return session


@pytest.mark.django_db
def test_base_template_lang_attribute_and_fallback(client):
    # Default is English
    resp = client.get(reverse("liveclassroom:home"))
    assert resp.status_code == 200
    assert b'<html lang="en">' in resp.content

    # Query param ?lang=zh-Hans updates html lang attribute
    resp_zh = client.get(f"{reverse('liveclassroom:home')}?lang=zh-Hans")
    assert resp_zh.status_code == 200
    assert b'<html lang="zh-Hans">' in resp_zh.content

    # Query param ?lang=zh-CN updates html lang attribute
    resp_cn = client.get(f"{reverse('liveclassroom:home')}?lang=zh-CN")
    assert resp_cn.status_code == 200
    assert b'<html lang="zh-CN">' in resp_cn.content


@pytest.mark.django_db
def test_teacher_console_bilingual_and_lang_switch(client, teacher_user, session_with_flow):
    client.force_login(teacher_user)

    # 1. Default (English)
    resp_en = client.get(reverse("liveclassroom:teacher-console", args=[session_with_flow.id]))
    assert resp_en.status_code == 200
    content_en = resp_en.content.decode()
    assert 'class="lc-lang-switch"' in content_en
    assert 'data-locale="en"' in content_en
    assert 'data-audience="teacher"' in content_en
    assert 'id="start-session"' in content_en
    assert 'id="analytics-summary"' in content_en
    assert 'id="result-summary"' in content_en
    assert 'data-liveclassroom-content' in content_en
    assert 'data-liveclassroom-participant-preview' in content_en

    # 2. Simplified Chinese
    resp_zh = client.get(f"{reverse('liveclassroom:teacher-console', args=[session_with_flow.id])}?lang=zh-Hans")
    assert resp_zh.status_code == 200
    content_zh = resp_zh.content.decode()
    assert '<html lang="zh-Hans">' in content_zh
    assert 'data-locale="zh-Hans"' in content_zh
    assert 'class="lc-lang-switch"' in content_zh


@pytest.mark.django_db
def test_classroom_display_bilingual_and_lang_switch(client, teacher_user, session_with_flow):
    client.force_login(teacher_user)

    # Display surface with Chinese locale
    resp = client.get(f"{reverse('liveclassroom:classroom-display', args=[session_with_flow.id])}?lang=zh-Hans")
    assert resp.status_code == 200
    content = resp.content.decode()
    assert '<html lang="zh-Hans">' in content
    assert 'data-locale="zh-Hans"' in content
    assert 'data-audience="display"' in content
    assert 'class="lc-lang-switch"' in content
    assert 'id="display-content"' in content


@pytest.mark.django_db
def test_student_session_bilingual_and_lang_switch(client, session_with_flow):
    # Student surface with Chinese locale
    resp = client.get(f"{reverse('liveclassroom:student-session', args=[session_with_flow.id])}?lang=zh-Hans")
    assert resp.status_code == 200
    content = resp.content.decode()
    assert '<html lang="zh-Hans">' in content
    assert 'data-locale="zh-Hans"' in content
    assert 'data-audience="student"' in content
    assert 'class="lc-lang-switch"' in content
    assert 'id="student-content"' in content


@pytest.mark.django_db
def test_flow_builder_bilingual_and_lang_switch(client, teacher_user, session_with_flow):
    client.force_login(teacher_user)

    resp = client.get(f"{reverse('liveclassroom:flow-builder')}?session_id={session_with_flow.id}&lang=zh-Hans")
    assert resp.status_code == 200
    content = resp.content.decode()
    assert '<html lang="zh-Hans">' in content
    assert 'data-locale="zh-Hans"' in content
    assert 'data-liveclassroom-builder' in content
    assert 'class="lc-lang-switch"' in content


def test_frontend_bundle_contains_all_renderers_and_locales():
    bundle_path = Path("src/liveclassroom/static/liveclassroom/app.js")
    assert bundle_path.exists(), "app.js must be bundled and present in static files"
    content = bundle_path.read_text(encoding="utf-8")

    # Verify Language Switcher
    assert "mountLanguageSwitcher" in content
    assert "lc-lang-switch" in content
    assert "getLabels" in content

    # Verify Timer Renderer
    assert "renderTimer" in content
    assert "lc-timer-display" in content
    assert "lc-timer-countdown" in content
    assert "timerFinished" in content

    # Verify Media Renderer
    assert "renderMedia" in content
    assert "lc-media-container" in content

    # Verify Markdown Renderer
    assert "renderMarkdownText" in content
    assert "lc-markdown-body" in content

    # Verify Word Cloud Renderer
    assert "renderWordCloud" in content
    assert "lc-word-cloud" in content
    assert "lc-word-tag" in content
    assert "lc-word-cloud-moderation" in content

    # Verify Richer Analytics
    assert "renderTeacherAnalytics" in content
    assert "renderAggregate" in content
    assert "lc-bar-container" in content
    assert "lc-bar" in content
    assert "lc-choice-bars" in content
    assert "lc-rate-badge" in content

    # Verify Bilingual Chinese and English translation strings
    assert "时间到！" in content
    assert "Time's up!" in content
    assert "作答率" in content
    assert "Response rate" in content
    assert "词频统计" in content
    assert "Word frequencies" in content


def test_css_contains_teaching_surface_styles():
    css_path = Path("src/liveclassroom/static/liveclassroom/liveclassroom.css")
    assert css_path.exists(), "liveclassroom.css must exist"
    css = css_path.read_text(encoding="utf-8")

    # Language Switcher
    assert ".lc-lang-switch" in css
    # Timer
    assert ".lc-timer-display" in css
    assert ".lc-timer-countdown" in css
    assert ".lc-timer-ended" in css
    # Media
    assert ".lc-media-container" in css
    # Markdown
    assert ".lc-markdown-body" in css
    # Word cloud
    assert ".lc-word-cloud" in css
    assert ".lc-word-tag" in css
    # Analytics bars
    assert ".lc-bar-container" in css
    assert ".lc-bar" in css
    assert ".lc-rate-badge" in css


def test_locales_ts_key_parity_and_coverage():
    locales_path = Path("frontend/src/locales.ts")
    assert locales_path.exists()
    content = locales_path.read_text(encoding="utf-8")

    # Extract keys in en block and zh-Hans block
    import re
    en_match = re.search(
        r"en:\s*\{([^}]+(?:\{[^}]+\}[^}]+)*)\},\s*[\"']zh-Hans[\"']:\s*\{([^}]+(?:\{[^}]+\}[^}]+)*)\}",
        content,
    )
    assert en_match is not None, "Both en and zh-Hans dictionaries must be defined in locales.ts"
    en_block, zh_block = en_match.group(1), en_match.group(2)

    en_keys = set(re.findall(r"^\s*([a-zA-Z0-9_]+)\s*:", en_block, flags=re.MULTILINE))
    zh_keys = set(re.findall(r"^\s*([a-zA-Z0-9_]+)\s*:", zh_block, flags=re.MULTILINE))

    # All en keys must exist in zh-Hans
    missing_in_zh = en_keys - zh_keys
    assert not missing_in_zh, f"Keys missing in zh-Hans: {missing_in_zh}"

    # All zh-Hans keys must exist in en
    missing_in_en = zh_keys - en_keys
    assert not missing_in_en, f"Keys missing in en: {missing_in_en}"

    # Ensure critical activity renderer keys exist
    critical_keys = {
        "timer", "timerRemaining", "timerFinished", "seconds",
        "wordCloud", "wordFrequencies", "moderation",
        "markdownContent", "mediaContent",
        "singleChoice", "multipleChoice", "trueFalse", "poll", "shortText", "numeric", "rating", "ranking",
        "responseRate", "admitted", "connected", "attended",
        "publish", "display", "participants", "displayPreview", "participantPreview",
        "save", "cancel", "submit", "update", "saved", "stale",
    }
    assert critical_keys.issubset(en_keys)


@pytest.mark.django_db
def test_mobile_first_student_route_structure(client, session_with_flow):
    resp = client.get(reverse("liveclassroom:student-session", args=[session_with_flow.id]))
    assert resp.status_code == 200
    content = resp.content.decode()

    # Viewport for mobile-first rendering
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in content
    # Card and surface data
    assert 'data-audience="student"' in content
    assert 'data-access-mode="guest"' in content
    assert 'id="student-content"' in content
    assert 'data-liveclassroom-chat' in content
    assert 'data-liveclassroom-history' in content


@pytest.mark.django_db
def test_chrome_free_display_route_structure(client, teacher_user, session_with_flow):
    client.force_login(teacher_user)
    resp = client.get(reverse("liveclassroom:classroom-display", args=[session_with_flow.id]))
    assert resp.status_code == 200
    content = resp.content.decode()

    assert 'data-display="true"' in content
    assert 'data-audience="display"' in content
    assert 'id="display-title"' in content
    assert 'id="display-content"' in content
    assert 'id="display-status"' in content
