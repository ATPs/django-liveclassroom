import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from liveclassroom.models import LiveSession


@pytest.mark.django_db
def test_help_page_explains_tasks_and_high_impact_actions(client):
    response = client.get(reverse("liveclassroom:help"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "LiveClassroom help" in content
    assert "What each surface is for" in content
    assert "A safe sequence for starting class" in content
    assert "Check before publishing, sharing, or ending" in content
    assert "Create a reusable lesson" in content
    assert reverse("liveclassroom:help") in content


@pytest.mark.django_db
def test_help_page_uses_simplified_chinese_for_the_requested_locale(client):
    response = client.get(f"{reverse('liveclassroom:help')}?lang=zh-Hans")

    assert response.status_code == 200
    content = response.content.decode()
    assert '<html lang="zh-Hans">' in content
    assert "LiveClassroom 帮助" in content
    assert "三个页面分别做什么" in content
    assert "发布、共享和结束前请确认" in content
    assert "创建可复用教案" in content


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="tests.mounted_urls")
def test_help_page_and_context_link_keep_the_mount_prefix(client):
    response = client.get(reverse("liveclassroom:help"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'href="/classroom/help/?lang=en"' in content
    assert 'href="/classroom/?lang=en"' in content


@pytest.mark.django_db
def test_teacher_surfaces_show_contextual_guidance_and_help_links(client):
    teacher = get_user_model().objects.create_user(username="guidance-teacher")
    session = LiveSession.objects.create(teacher=teacher, title="Guidance class", join_code="GUIDE1")
    client.force_login(teacher)

    workspace = client.get(reverse("liveclassroom:teacher-dashboard"))
    builder = client.get(reverse("liveclassroom:flow-builder"))
    console = client.get(reverse("liveclassroom:teacher-console", args=[session.id]))

    assert workspace.status_code == builder.status_code == console.status_code == 200
    workspace_content = workspace.content.decode()
    builder_content = builder.content.decode()
    console_content = console.content.decode()
    assert "Choose the right starting point" in workspace_content
    assert "Action check:" in workspace_content
    assert 'href="/help/?lang=en"' in workspace_content
    assert "Check before you use it in class" in builder_content
    assert "Action check:" in builder_content
    assert 'href="/help/?lang=en"' in builder_content
    assert "Confirm the target channel before publishing" in console_content
    assert "High impact check:" in console_content
    assert 'href="/help/?lang=en"' in console_content


@pytest.mark.django_db
def test_locale_cookie_keeps_server_guidance_and_internal_links_in_simplified_chinese(client):
    teacher = get_user_model().objects.create_user(username="cookie-guidance-teacher")
    client.force_login(teacher)
    client.cookies["liveclassroom_locale"] = "zh-Hans"

    response = client.get(reverse("liveclassroom:teacher-dashboard"))

    content = response.content.decode()
    assert '<html lang="zh-Hans">' in content
    assert "先选择合适的起点" in content
    assert 'data-builder-url="/teacher/builder/?lang=zh-Hans"' in content
    assert 'href="/help/?lang=zh-Hans"' in content
