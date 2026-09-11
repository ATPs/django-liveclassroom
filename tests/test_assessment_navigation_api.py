"""HTTP contract for server-authoritative assessment URL navigation."""

import json
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition


def _attempt(owner, learner):
    questions = [
        create_activity_definition(
            owner=owner,
            title=f"Question {position}",
            type_key="short_text",
            definition={"prompt": f"Question {position}"},
        )
        for position in range(1, 3)
    ]
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Navigation API exam",
            "settings": {"navigation": "forward_only", "max_attempts": 1},
            "items": [{"revision_id": question.current_revision_id} for question in questions],
        },
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    return start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())[0]


@pytest.mark.django_db
def test_attempt_navigation_http_obeys_forward_only_cursor():
    users = get_user_model()
    owner = users.objects.create_user(username="navigation-api-owner")
    learner = users.objects.create_user(username="navigation-api-learner")
    attempt = _attempt(owner, learner)
    first, second = list(attempt.items.order_by("position"))
    client = Client()
    client.force_login(learner)

    future = client.post(
        reverse("liveclassroom:api-v1-attempt-navigate", args=[attempt.public_id]),
        data=json.dumps({"item_key": str(second.key), "expected_navigation_version": 1}),
        content_type="application/json",
    )
    assert future.status_code == 409
    assert future.json()["code"] == "item_not_accessible"

    advanced = client.post(
        reverse("liveclassroom:api-v1-attempt-advance", args=[attempt.public_id]),
        data=json.dumps({"item_key": str(first.key), "expected_navigation_version": 1}),
        content_type="application/json",
    )
    assert advanced.status_code == 200
    assert advanced.json()["current_item_key"] == str(second.key)
    assert advanced.json()["navigation_version"] == 2

    reviewed = client.post(
        reverse("liveclassroom:api-v1-attempt-navigate", args=[attempt.public_id]),
        data=json.dumps({"item_key": str(first.key), "expected_navigation_version": 2}),
        content_type="application/json",
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["read_only"] is False
