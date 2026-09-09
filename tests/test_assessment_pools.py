"""Assessment section and publication-time question-pool contracts."""

import json
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import AssessmentRun
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessment_sections import replace_sections
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.classroom import ClassroomError, create_activity_definition
from liveclassroom.services.question_banks import add_question_to_bank, create_question_bank


def _question(owner, title, *, tag="rna"):
    return create_activity_definition(
        owner=owner,
        title=title,
        type_key="single_choice",
        definition={
            "prompt": title,
            "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
            "answer": "a",
        },
        metadata={"tags": [tag]},
    )


def _section(item_key, bank_id, *, sample_size=2, filters=None, points="2"):
    return {
        "title": "RNA",
        "entries": [
            {"kind": "fixed", "item_key": str(item_key)},
            {
                "kind": "pool",
                "bank_id": bank_id,
                "filters": filters or {"tag": "rna"},
                "sample_size": sample_size,
                "points": points,
                "shuffle_options": False,
            },
        ],
    }


@pytest.mark.django_db
def test_pool_publication_freezes_candidates_and_excludes_fixed_item():
    owner = get_user_model().objects.create_user(username="pool-owner")
    fixed = _question(owner, "fixed")
    candidates = [_question(owner, f"candidate-{index}") for index in range(1, 4)]
    bank = create_question_bank(actor=owner, data={"title": "RNA bank"})
    for question in [fixed, *candidates]:
        add_question_to_bank(actor=owner, bank=bank, definition=question)
    item_key = uuid4()
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Pooled quiz",
            "items": [{"key": str(item_key), "revision_id": fixed.current_revision_id}],
            "sections": [_section(item_key, bank.id)],
        },
    )
    assert assessment.sections.count() == 1
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    section = run.manifest["sections"][0]
    assert section["entries"][0]["kind"] == "fixed"
    pool = section["entries"][1]
    assert pool["kind"] == "pool"
    assert pool["sample_size"] == 2
    assert pool["points"] == "2"
    assert {candidate["definition_id"] for candidate in pool["candidates"]} == {
        question.id for question in candidates
    }
    assert fixed.id not in {candidate["definition_id"] for candidate in pool["candidates"]}
    bank.items.filter(definition=candidates[0]).delete()
    run.refresh_from_db()
    assert {candidate["definition_id"] for candidate in run.manifest["sections"][0]["entries"][1]["candidates"]} == {
        question.id for question in candidates
    }


@pytest.mark.django_db
def test_pool_publication_rejects_insufficient_and_overlapping_rules_atomically():
    owner = get_user_model().objects.create_user(username="pool-invalid")
    fixed = _question(owner, "fixed")
    candidate = _question(owner, "candidate")
    bank = create_question_bank(actor=owner, data={"title": "Bank"})
    add_question_to_bank(actor=owner, bank=bank, definition=fixed)
    add_question_to_bank(actor=owner, bank=bank, definition=candidate)
    fixed_key = uuid4()
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Too large",
            "items": [{"key": str(fixed_key), "revision_id": fixed.current_revision_id}],
            "sections": [_section(fixed_key, bank.id, sample_size=2)],
        },
    )
    with pytest.raises(ClassroomError, match="eligible|unavailable"):
        publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    assert AssessmentRun.objects.count() == 0
    candidate2 = _question(owner, "candidate-2")
    add_question_to_bank(actor=owner, bank=bank, definition=candidate2)
    replace_sections(
        actor=owner,
        assessment=assessment,
        expected_version=assessment.version,
        sections=[
            {
                "title": "Overlap",
                "entries": [
                    {"kind": "fixed", "item_key": str(fixed_key)},
                    {"kind": "pool", "bank_id": bank.id, "filters": {"tag": "rna"}, "sample_size": 1},
                    {"kind": "pool", "bank_id": bank.id, "filters": {"tag": "rna"}, "sample_size": 1},
                ],
            }
        ],
    )
    assessment.refresh_from_db()
    with pytest.raises(ClassroomError, match="overlap"):
        publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    assert AssessmentRun.objects.count() == 0


@pytest.mark.django_db
def test_pool_rules_are_mount_safe_in_sections_api_and_attempts_are_gated():
    owner = get_user_model().objects.create_user(username="pool-api")
    fixed = _question(owner, "fixed")
    candidate = _question(owner, "candidate")
    bank = create_question_bank(actor=owner, data={"title": "Bank"})
    add_question_to_bank(actor=owner, bank=bank, definition=fixed)
    add_question_to_bank(actor=owner, bank=bank, definition=candidate)
    item_key = uuid4()
    assessment = create_assessment(
        actor=owner,
        data={"title": "API pool", "items": [{"key": str(item_key), "revision_id": fixed.current_revision_id}]},
    )
    client = Client()
    client.force_login(owner)
    url = reverse("liveclassroom:api-v1-assessment-sections", args=[assessment.id])
    response = client.put(
        url,
        data=json.dumps(
            {
                "expected_version": assessment.version,
                "sections": [_section(item_key, bank.id, sample_size=1)],
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["sections"][0]["entries"][1]["sample_size"] == 1
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version + 1)
    learner = get_user_model().objects.create_user(username="pool-learner")
    entry = Client()
    entry.force_login(learner)
    start = entry.post(
        reverse("liveclassroom:api-v1-assessment-attempts", args=[run.public_id]),
        data=json.dumps({"request_id": str(uuid4())}),
        content_type="application/json",
    )
    assert start.status_code == 403
    assert "pooled" in start.json()["detail"].casefold()
