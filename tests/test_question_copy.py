"""Question-bank copy, private preview and revision boundaries."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import ActivityDefinition, ActivityDefinitionRevision
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.question_banks import add_question_to_bank, create_question_bank


@pytest.fixture
def question_owner(db):
    return get_user_model().objects.create_user(username="question-copy-owner")


@pytest.fixture
def question_setup(question_owner):
    question = create_activity_definition(
        owner=question_owner,
        title="RNA transcription",
        type_key="liveclassroom.single_choice",
        definition={
            "prompt": "Which molecule carries the code?",
            "options": [{"id": "A", "text": "RNA"}, {"id": "B", "text": "ATP"}],
            "answer": "A",
        },
        metadata={"topic": "Biology", "tags": ["rna"], "difficulty": "easy"},
    )
    source = create_question_bank(actor=question_owner, data={"title": "Biology"})
    target = create_question_bank(actor=question_owner, data={"title": "Revision"})
    add_question_to_bank(actor=question_owner, bank=source, definition=question)
    return question, source, target


@pytest.mark.django_db
def test_copy_question_creates_independent_definition_and_optional_membership(question_setup, question_owner):
    question, source, target = question_setup
    before_revision_ids = list(question.revisions.values_list("id", flat=True))
    client = Client()
    client.force_login(question_owner)

    response = client.post(
        reverse("liveclassroom:api-v1-question-bank-question-copy", args=[source.id, question.id]),
        data=json.dumps({"title": "RNA transcription practice", "target_bank_id": target.id}),
        content_type="application/json",
    )

    assert response.status_code == 201
    copied = ActivityDefinition.objects.get(pk=response.json()["id"])
    assert copied.pk != question.pk
    assert copied.title == "RNA transcription practice"
    assert copied.definition == question.definition
    assert copied.metadata == question.metadata
    assert list(question.revisions.values_list("id", flat=True)) == before_revision_ids
    assert source.items.filter(definition=question).exists()
    assert target.items.filter(definition=copied).exists()
    assert copied.revisions.count() == 1


@pytest.mark.django_db
def test_question_preview_is_private_and_patch_adds_revision(question_setup, question_owner):
    question, source, _target = question_setup
    client = Client()
    client.force_login(question_owner)
    detail_url = reverse("liveclassroom:api-v1-question-bank-question", args=[source.id, question.id])

    preview = client.get(detail_url)
    assert preview.status_code == 200
    assert preview.json()["definition"]["answer"] == "A"
    assert len(preview.json()["revisions"]) == 1

    update = client.patch(
        detail_url,
        data=json.dumps(
            {
                "title": "RNA transcription revised",
                "definition": {**question.definition, "prompt": "Which molecule carries the code now?"},
                "metadata": {"topic": "Biology", "tags": ["rna", "review"]},
            }
        ),
        content_type="application/json",
    )
    assert update.status_code == 200
    question.refresh_from_db()
    assert question.title == "RNA transcription revised"
    assert question.definition["prompt"].endswith("now?")
    assert question.revisions.count() == 2
    assert ActivityDefinitionRevision.objects.filter(definition=question, revision=1).exists()

    outsider = get_user_model().objects.create_user(username="question-copy-outsider")
    outsider_client = Client()
    outsider_client.force_login(outsider)
    assert outsider_client.get(detail_url).status_code == 404
    assert outsider_client.post(
        reverse("liveclassroom:api-v1-question-bank-question-copy", args=[source.id, question.id]),
        data=json.dumps({}),
        content_type="application/json",
    ).status_code == 404
