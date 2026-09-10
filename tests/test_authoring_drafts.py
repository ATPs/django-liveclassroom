import json
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from liveclassroom.ai import AIMessage, AIModel
from liveclassroom.models import (
    ActivityDefinition,
    AssessmentDefinition,
    AuthoringDraft,
    AuthoringJob,
    AuthoringThread,
    Deck,
)
from liveclassroom.services.authoring import create_authoring_request, run_authoring_job
from liveclassroom.services.authoring_drafts import (
    AuthoringDraftError,
    accept_authoring_draft,
    build_authoring_context,
    reject_authoring_draft,
    validate_draft,
)
from liveclassroom.services.classroom import ClassroomError
from liveclassroom.services.definitions import create_activity_definition
from liveclassroom.services.question_banks import add_question_to_bank, create_question_bank


def _teacher(name="draft-owner"):
    return get_user_model().objects.create_user(username=name)


def _question(owner, title="Question"):
    return create_activity_definition(
        owner=owner,
        title=title,
        type_key="liveclassroom.single_choice",
        definition={
            "prompt": "Which letter?",
            "options": [{"id": "A", "text": "A"}, {"id": "B", "text": "B"}],
            "answer": "A",
        },
    )


@pytest.mark.django_db
def test_validate_and_accept_question_deck_and_assessment_are_independent():
    owner = _teacher()
    question = _question(owner)
    bank = create_question_bank(actor=owner, data={"title": "Bank"})
    add_question_to_bank(actor=owner, bank=bank, definition=question)

    question_payload = validate_draft(
        actor=owner,
        artifact_type="question",
        payload={
            "title": "Improved question",
            "type_key": "single_choice",
            "definition": {
                "prompt": "Improved wording",
                "options": [{"id": "A", "text": "A"}, {"id": "B", "text": "B"}],
                "answer": "A",
            },
        },
    )
    question_draft = AuthoringDraft.objects.create(
        owner=owner,
        thread=AuthoringThread.objects.create(owner=owner),
        artifact_type="question",
        payload=question_payload,
    )
    accepted_question = accept_authoring_draft(actor=owner, draft=question_draft)
    assert accepted_question.owner_id == owner.pk
    assert accepted_question.title == "Improved question"

    deck_payload = validate_draft(
        actor=owner,
        artifact_type="deck",
        payload={"title": "Generated slides", "slides": [{"markdown": "# Intro", "notes": "Say hello"}]},
    )
    deck_draft = AuthoringDraft.objects.create(
        owner=owner, thread=question_draft.thread, artifact_type="deck", payload=deck_payload
    )
    accepted_deck = accept_authoring_draft(actor=owner, draft=deck_draft)
    assert isinstance(accepted_deck, Deck)
    assert accepted_deck.slides.count() == 1

    assessment_payload = validate_draft(
        actor=owner,
        artifact_type="assessment",
        payload={"title": "Generated quiz", "items": [{"revision_id": question.current_revision_id, "points": 2}]},
    )
    assessment_draft = AuthoringDraft.objects.create(
        owner=owner, thread=question_draft.thread, artifact_type="assessment", payload=assessment_payload
    )
    accepted_assessment = accept_authoring_draft(actor=owner, draft=assessment_draft)
    assert isinstance(accepted_assessment, AssessmentDefinition)
    assert accepted_assessment.items.count() == 1
    assert question.title == "Question"


@pytest.mark.django_db
def test_structured_backend_response_creates_private_draft_and_rejects_free_text():
    owner = _teacher("ai-owner")
    thread = AuthoringThread.objects.create(owner=owner)

    @dataclass
    class Backend:
        key: str = "draft-backend"
        content: str = ""

        def list_models(self, *, request=None):
            return [AIModel("model", "Model")]

        def complete(self, messages, *, model, request=None, attachments=None):
            return AIMessage("assistant", self.content)

    backend = Backend(
        content=json.dumps(
            {
                "artifact_type": "question",
                "payload": {
                    "title": "Generated",
                    "type_key": "single_choice",
                    "definition": {
                        "prompt": "Pick one",
                        "options": [{"id": "A", "text": "One"}],
                        "answer": "A",
                    },
                },
            }
        )
    )
    with override_settings(LIVECLASSROOM={"AI_BACKENDS": {"draft-backend": backend}}):
        _prompt, job = create_authoring_request(
            thread=thread,
            author=owner,
            content="Generate a question",
            backend_key="draft-backend",
            model_identifier="model",
            artifact_type="question",
        )
        result = run_authoring_job(job_id=job.pk, actor=owner)
    assert result.status == AuthoringJob.Status.SUCCEEDED
    draft = AuthoringDraft.objects.get(thread=thread)
    assert draft.payload["title"] == "Generated"
    assert ActivityDefinition.objects.filter(title="Generated").exists() is False

    backend.content = "A paragraph instead of the required envelope"
    with override_settings(LIVECLASSROOM={"AI_BACKENDS": {"draft-backend": backend}}):
        _prompt, invalid_job = create_authoring_request(
            thread=thread,
            author=owner,
            content="Generate another question",
            backend_key="draft-backend",
            model_identifier="model",
            artifact_type="question",
        )
        invalid_result = run_authoring_job(job_id=invalid_job.pk, actor=owner)
    assert invalid_result.status == AuthoringJob.Status.FAILED
    assert invalid_result.error_code == "invalid_draft"
    assert AuthoringDraft.objects.filter(thread=thread).count() == 1


@pytest.mark.django_db
def test_draft_access_is_owner_only_and_transitions_are_idempotent():
    owner = _teacher("transition-owner")
    other = _teacher("transition-other")
    thread = AuthoringThread.objects.create(owner=owner)
    draft = AuthoringDraft.objects.create(
        owner=owner,
        thread=thread,
        artifact_type="deck",
        payload={"title": "Deck", "slides": [{"markdown": "# Draft", "notes": ""}]},
    )
    with pytest.raises(AuthoringDraftError, match="permission"):
        reject_authoring_draft(actor=other, draft=draft)
    rejected = reject_authoring_draft(actor=owner, draft=draft)
    assert rejected.status == AuthoringDraft.Status.REJECTED
    assert reject_authoring_draft(actor=owner, draft=draft).status == AuthoringDraft.Status.REJECTED
    with pytest.raises(AuthoringDraftError, match="cannot be accepted"):
        accept_authoring_draft(actor=owner, draft=draft)


@pytest.mark.django_db
def test_context_reauthorizes_exact_question_bank_and_does_not_allow_foreign_source():
    owner = _teacher("context-owner")
    other = _teacher("context-other")
    bank = create_question_bank(actor=owner, data={"title": "Selected bank"})
    question = _question(owner)
    add_question_to_bank(actor=owner, bank=bank, definition=question)
    context = build_authoring_context(
        actor=owner,
        attachments=[{"source_type": "question_bank", "bank_id": bank.pk}],
    )
    assert context["attachments"][0]["title"] == "Selected bank"
    with pytest.raises((ClassroomError, AuthoringDraftError), match="permission"):
        build_authoring_context(actor=other, attachments=[{"source_type": "question_bank", "bank_id": bank.pk}])
