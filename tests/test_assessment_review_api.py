import pytest
from django.test import Client
from django.urls import reverse

from tests.test_assessment_review import _fixture


@pytest.mark.django_db
def test_history_and_review_endpoints_are_mounted_and_own_only():
    _owner, learner, other, _question, _run, attempt, _item = _fixture()
    client = Client()
    client.force_login(learner)
    history = client.get(reverse("liveclassroom:api-v1-assessment-history"))
    assert history.status_code == 200 and history.json()["total"] == 1
    review = reverse("liveclassroom:api-v1-attempt-review", args=[attempt.public_id])
    assert client.get(review).status_code == 200
    foreign = Client()
    foreign.force_login(other)
    assert foreign.get(review).status_code == 404
