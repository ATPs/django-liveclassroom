"""Task 48 contracts for help links and the opt-in local demo package."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from liveclassroom.models import AssessmentDefinition, AssessmentRun, ClassroomAsset, Course, Deck, DemoLesson
from tests.test_browser_workflows import _chromium_or_skip


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="tests.mounted_urls")
def test_help_describes_the_teacher_path_and_keeps_links_mount_safe(client):
    response = client.get(reverse("liveclassroom:help"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Simple teacher path" in content
    assert "Course (subject) and Class (learner cohort)" in content
    assert 'href="/classroom/teacher/builder/?lang=en"' in content
    assert 'href="/classroom/teacher/decks/?lang=en"' in content
    assert 'href="/classroom/api/v1/content-shares/"' in content
    assert "VaultPub note and Slide View rendering" in content
    assert "Empty, loading, error, keyboard, and mobile guidance" in content
    assert "/data/" not in content


@pytest.mark.django_db
def test_help_chinese_has_the_same_defaults_and_workflow_boundaries(client):
    response = client.get(f"{reverse('liveclassroom:help')}?lang=zh-Hans")

    assert response.status_code == 200
    content = response.content.decode()
    assert '<html lang="zh-Hans">' in content
    assert "教师快速路径" in content
    assert "Course（课程主题）和 Class（学生班级）" in content
    assert "VaultPub 是启用后才可用的丰富笔记/幻灯片来源" in content
    assert "示例数据只在你主动运行种子命令时创建" in content


@pytest.mark.django_db
def test_demo_seed_is_repeatable_and_contains_authoring_and_assessment_examples():
    call_command("seed_liveclassroom_bash_demo", language="en")
    call_command("seed_liveclassroom_bash_demo", language="en")

    owner = get_user_model().objects.get(username="liveclassroom-demo")
    course = Course.objects.get(slug="liveclassroom-public-demos-en")
    assert owner.is_active is False
    assert course.created_by_id == owner.id
    assert DemoLesson.objects.get(slug="bash-for-linux-beginners", language="en").flow.steps.count() == 14

    imported = ClassroomAsset.objects.get(owner=owner, original_name="bash-import-example-en.md")
    assert imported.kind == ClassroomAsset.Kind.MARKDOWN
    deck = Deck.objects.get(owner=owner, title="Bash command map — demo deck")
    assert deck.course_id == course.id
    assert list(deck.slides.values_list("position", flat=True)) == [1, 2]

    assessment = AssessmentDefinition.objects.get(owner=owner, title="Bash starter check — demo assessment")
    assert assessment.course_id == course.id
    assert assessment.items.count() == 1
    assert AssessmentRun.objects.filter(owner=owner, source_assessment=assessment).count() == 1


@pytest.mark.django_db(transaction=True)
def test_help_page_fits_mobile_and_desktop_viewports(live_server):
    manager, browser = _chromium_or_skip()
    try:
        for viewport in ({"width": 390, "height": 844}, {"width": 1440, "height": 900}):
            page = browser.new_page(viewport=viewport)
            page.goto(f"{live_server.url}{reverse('liveclassroom:help')}?lang=en")
            page.get_by_role("heading", name="LiveClassroom help", exact=True).wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.close()
    finally:
        browser.close()
        manager.stop()
