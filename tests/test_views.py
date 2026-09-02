import pytest
from django.urls import reverse


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
