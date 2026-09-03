import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from liveclassroom.models import Flow, LiveSession


@pytest.mark.django_db
def test_health_endpoint(client):
    response = client.get(reverse("liveclassroom:health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "liveclassroom"}


@pytest.mark.django_db
def test_home_page_is_available(client):
    response = client.get(reverse("liveclassroom:home"))

    assert response.status_code == 200
    assert b"LiveClassroom" in response.content


@pytest.mark.django_db
def test_flow_builder_view_requires_authentication(client):
    response = client.get(reverse("liveclassroom:flow-builder"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url or "login" in response.url


@pytest.mark.django_db
def test_flow_builder_view_authenticated(client):
    user = get_user_model().objects.create_user(username="builder-teacher")
    client.force_login(user)

    # 1. Base builder view
    response = client.get(reverse("liveclassroom:flow-builder"))
    assert response.status_code == 200
    assert b"data-liveclassroom-builder" in response.content

    # 2. Builder view with flow_id in kwargs
    flow = Flow.objects.create(title="Sample Flow", created_by=user)
    detail_response = client.get(reverse("liveclassroom:flow-builder-detail", args=[flow.id]))
    assert detail_response.status_code == 200
    assert detail_response.context["flow_id"] == flow.id
    assert f'data-flow-id="{flow.id}"'.encode() in detail_response.content

    # 3. Builder view with session_id query param
    session = LiveSession.objects.create(teacher=user, title="Biology Lab", join_code="BIO123")
    session_response = client.get(f"{reverse('liveclassroom:flow-builder')}?session_id={session.id}")
    assert session_response.status_code == 200
    assert session_response.context["session_id"] == session.id
    assert f'data-session-id="{session.id}"'.encode() in session_response.content


@pytest.mark.django_db
def test_teacher_dashboard_has_flow_builder_link(client):
    user = get_user_model().objects.create_user(username="dash-teacher")
    client.force_login(user)

    response = client.get(reverse("liveclassroom:teacher-dashboard"))
    assert response.status_code == 200
    assert reverse("liveclassroom:flow-builder").encode() in response.content
