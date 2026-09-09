"""Question-bank ownership, search and API boundaries."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import ActivityDefinition, QuestionBank
from liveclassroom.services.classroom import ClassroomError, create_activity_definition
from liveclassroom.services.question_banks import add_question_to_bank, create_question_bank, list_bank_questions


def question(owner, title, *, metadata=None):
    return create_activity_definition(
        owner=owner,
        title=title,
        type_key="liveclassroom.short_text",
        definition={"prompt": f"Explain {title}"},
        metadata=metadata or {},
    )


@pytest.mark.django_db
def test_question_bank_membership_is_reusable_and_owner_scoped():
    users = get_user_model()
    owner = users.objects.create_user(username="bank-owner")
    other = users.objects.create_user(username="bank-other")
    definition = question(owner, "Transcription", metadata={"topic": "RNA", "tags": ["gene"]})
    first = create_question_bank(actor=owner, data={"title": "Biology"})
    second = create_question_bank(actor=owner, data={"title": "Revision"})
    first_item = add_question_to_bank(actor=owner, bank=first, definition=definition)
    assert add_question_to_bank(actor=owner, bank=first, definition=definition).pk == first_item.pk
    add_question_to_bank(actor=owner, bank=second, definition=definition)
    assert first.items.count() == second.items.count() == 1
    assert list_bank_questions(actor=owner, bank=first, filters={"tag": "GENE"}) == [definition]
    with pytest.raises(ClassroomError, match="permission"):
        list_bank_questions(actor=other, bank=first)
    first.delete()
    assert ActivityDefinition.objects.filter(pk=definition.pk).exists()
    assert QuestionBank.objects.filter(pk=second.pk).exists()


@pytest.mark.django_db
def test_question_bank_api_filters_without_answer_key_or_foreign_leak():
    users = get_user_model()
    owner = users.objects.create_user(username="bank-api-owner")
    other = users.objects.create_user(username="bank-api-other")
    definition = question(
        owner,
        "RNA synthesis",
        metadata={"topic": "Molecular biology", "difficulty": "easy", "tags": ["RNA"]},
    )
    private = create_activity_definition(
        owner=other,
        title="Other answer",
        type_key="liveclassroom.single_choice",
        definition={"prompt": "Private", "options": [{"id": "A", "text": "One"}], "answer": "A"},
    )
    client = Client()
    client.force_login(owner)
    created = client.post(
        reverse("liveclassroom:api-v1-question-banks"),
        data=json.dumps({"title": "RNA questions"}),
        content_type="application/json",
    )
    assert created.status_code == 201
    bank_id = created.json()["id"]
    add_url = reverse("liveclassroom:api-v1-question-bank-questions", args=[bank_id])
    added = client.post(
        add_url,
        data=json.dumps({"definition_id": definition.id}),
        content_type="application/json",
    )
    assert added.status_code == 201
    forbidden = client.post(add_url, data=json.dumps({"definition_id": private.id}), content_type="application/json")
    assert forbidden.status_code == 403
    listed = client.get(add_url, {"q": "synthesis", "tag": "rna", "difficulty": "easy"})
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["count"] == 1
    assert payload["questions"][0]["id"] == definition.id
    assert "definition" not in payload["questions"][0]
    other_client = Client()
    other_client.force_login(other)
    assert other_client.get(add_url).status_code == 404
    assert other_client.get(reverse("liveclassroom:api-v1-question-banks")).json() == {"question_banks": []}
