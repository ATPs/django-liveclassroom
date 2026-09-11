"""The global teacher results destination mounts the results surface."""

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
def test_global_results_route_mounts_results_workspace(client):
    teacher = get_user_model().objects.create_user(username="global-results-teacher")
    client.force_login(teacher)

    response = client.get(reverse("liveclassroom:teacher-results"))

    assert response.status_code == 200
    content = response.content
    assert b'data-results-workspace' in content
    assert b'data-mode="global"' in content
    assert b'data-assessment-builder' not in content
    assert reverse("liveclassroom:api-v1-browse-navigation").encode() in content


@pytest.mark.django_db
@override_settings(
    LIVECLASSROOM={"TEACHER_AUTHORIZER": lambda actor: actor.username.startswith("global-results-teacher")}
)
def test_global_results_route_requires_teacher_access(client):
    learner = get_user_model().objects.create_user(username="global-results-learner")
    client.force_login(learner)

    response = client.get(reverse("liveclassroom:teacher-results"))

    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="tests.mounted_urls")
def test_global_results_route_keeps_api_links_under_a_mount_prefix(client):
    teacher = get_user_model().objects.create_user(username="mounted-global-results-teacher")
    client.force_login(teacher)

    response = client.get(reverse("liveclassroom:teacher-results"))

    assert response.status_code == 200
    assert b'data-api-root="/classroom/api/v1/workspace/"' in response.content
    assert b'data-navigation-url="/classroom/api/v1/browse/navigation/"' in response.content
