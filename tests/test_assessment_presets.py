"""Focused tests for simple assessment delivery presets."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.services.assessment_presets import (
    apply_assessment_preset,
    preset_readiness,
    preset_settings,
)
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.classroom import ClassroomError, create_activity_definition


def _assessment(owner, *, settings=None):
    question = create_activity_definition(
        owner=owner,
        title="Preset question",
        type_key="single_choice",
        definition={
            "prompt": "Pick one",
            "options": [{"id": "a", "text": "A"}],
            "answer": "a",
        },
    )
    return create_assessment(
        actor=owner,
        data={
            "title": "Preset assessment",
            "settings": settings or {},
            "items": [{"revision_id": question.current_revision_id, "points": "2"}],
        },
    )


def test_named_preset_settings_use_existing_timing_and_release_contracts():
    closes = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    due = closes - timedelta(days=1)
    practice = preset_settings(mode="practice", current={"duration_seconds": 900, "closes_at": closes})
    assert practice["mode"] == "practice"
    assert practice["max_attempts"] is None
    assert practice["navigation"] == "free"
    assert practice["scoring"] is False
    assert "duration_seconds" not in practice and "closes_at" not in practice
    assert all(value == "after_submit" for value in practice["release_policy"].values())

    assignment = preset_settings(mode="assignment", current={"due_at": due, "closes_at": closes})
    assert assignment["max_attempts"] == 1
    assert assignment["due_at"] == due.isoformat()
    assert "duration_seconds" not in assignment
    assert all(value == "after_close" for value in assignment["release_policy"].values())

    no_close = preset_settings(mode="assignment", current={"due_at": due})
    assert no_close["release_policy"]["scores"] == "manual"
    quiz = preset_settings(mode="quiz", current={"duration_seconds": 600})
    assert quiz["duration_seconds"] == 600
    assert all(value == "manual" for value in quiz["release_policy"].values())
    exam = preset_settings(mode="exam")
    assert exam["audience"] == "authenticated_link"
    assert exam["navigation"] == "forward_only"
    assert preset_readiness(mode="exam", settings=exam) == {
        "mode": "exam",
        "ready": False,
        "missing": ["duration_seconds or opens_at and closes_at"],
    }


@pytest.mark.django_db
def test_apply_preset_bumps_version_preserves_items_and_does_not_rewrite_published_run():
    owner = get_user_model().objects.create_user(username="preset-owner")
    assessment = _assessment(owner)
    item_revision = assessment.items.get().question_revision_id
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    old_manifest = run.manifest
    updated = apply_assessment_preset(
        actor=owner, assessment=assessment, mode="practice", expected_version=assessment.version
    )
    assert updated.version == assessment.version + 1
    assert updated.settings["mode"] == "practice"
    assert updated.settings["max_attempts"] is None
    assert updated.items.get().question_revision_id == item_revision
    run.refresh_from_db()
    assert run.manifest == old_manifest
    with pytest.raises(ClassroomError, match="changed"):
        apply_assessment_preset(actor=owner, assessment=updated, mode="quiz", expected_version=1)


@pytest.mark.django_db
def test_preset_api_and_copy_mode_create_independent_draft():
    owner = get_user_model().objects.create_user(username="preset-api-owner")
    assessment = _assessment(owner)
    client = Client()
    client.force_login(owner)
    preset_url = reverse("liveclassroom:api-v1-assessment-preset", args=[assessment.id])
    response = client.post(
        preset_url,
        data=json.dumps({"mode": "practice", "expected_version": assessment.version}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="preset-practice",
    )
    assert response.status_code == 200
    assert response.json()["settings"]["mode"] == "practice"
    assert response.json()["preset"]["readiness"]["ready"] is True

    copy_response = client.post(
        reverse("liveclassroom:api-v1-assessment-copy", args=[assessment.id]),
        data=json.dumps({"mode": "exam", "title": "Exam copy"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="preset-copy-exam",
    )
    assert copy_response.status_code == 201
    copied = copy_response.json()
    assert copied["title"] == "Exam copy"
    assert copied["settings"]["mode"] == "exam"
    assert copied["settings"]["max_attempts"] == 1
    assert copied["settings"]["audience"] == "authenticated_link"
    assessment.refresh_from_db()
    assert assessment.settings["mode"] == "practice"


@pytest.mark.django_db
def test_preset_api_rejects_non_owner_without_revealing_assessment():
    users = get_user_model()
    owner = users.objects.create_user(username="preset-private-owner")
    other = users.objects.create_user(username="preset-private-other")
    assessment = _assessment(owner)
    client = Client()
    client.force_login(other)
    response = client.post(
        reverse("liveclassroom:api-v1-assessment-preset", args=[assessment.id]),
        data=json.dumps({"mode": "quiz", "expected_version": assessment.version}),
        content_type="application/json",
    )
    assert response.status_code == 400 or response.status_code == 404
    assert assessment.settings == {"max_attempts": 1}
