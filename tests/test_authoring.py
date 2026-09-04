import json
from dataclasses import dataclass
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from liveclassroom.ai import AIMessage, AIModel
from liveclassroom.integrations.vaultpub import VaultPubProvider
from liveclassroom.models import (
    ActivityDefinition,
    AuthoringAttachment,
    AuthoringJob,
    AuthoringThread,
)
from liveclassroom.providers import ContentReference
from liveclassroom.services.authoring import (
    claim_next_authoring_job,
    create_authoring_request,
    recover_expired_authoring_jobs,
    run_authoring_job,
)
from liveclassroom.services.classroom import ClassroomError


@dataclass
class DummyAI:
    key: str = "dummy"
    calls: list = None

    def __post_init__(self):
        if self.calls is None:
            self.calls = []

    def list_models(self, *, request=None):
        return [AIModel("test-model", "Test model")]

    def complete(self, messages, *, model, request=None, attachments=None):
        options = getattr(request, "liveclassroom_ai_options", None) if request is not None else None
        self.calls.append((list(messages), model, attachments, options))
        return AIMessage("assistant", "A safe draft")


@dataclass
class DummyProvider:
    key: str = "dummy-provider"

    def parse_reference(self, url, *, request=None):
        return ContentReference(self.key, "note", {"url": url})

    def validate_reference(self, reference, *, request=None):
        return reference

    def describe(self, reference, *, request=None):
        return {"source_fingerprint": "fingerprint"}


def post_json(client, url, payload=None, **headers):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json", **headers)


@pytest.mark.django_db
def test_private_authoring_routes_and_model_discovery():
    user_model = get_user_model()
    owner = user_model.objects.create_user(username="authoring-owner")
    other = user_model.objects.create_user(username="authoring-other")
    owner_client = Client()
    owner_client.force_login(owner)
    other_client = Client()
    other_client.force_login(other)

    with override_settings(LIVECLASSROOM={"AI_BACKENDS": {"dummy": DummyAI()}}):
        created = post_json(owner_client, reverse("liveclassroom:api-v1-authoring-threads"), {"title": "Lesson helper"})
        assert created.status_code == 201
        thread_id = created.json()["id"]
        thread_list = owner_client.get(reverse("liveclassroom:api-v1-authoring-threads")).json()
        assert thread_list["threads"][0]["title"] == "Lesson helper"
        assert other_client.get(reverse("liveclassroom:api-v1-authoring-thread", args=[thread_id])).status_code == 403
        models = owner_client.get(reverse("liveclassroom:api-v1-authoring-models"))
        message = post_json(
            owner_client,
            reverse("liveclassroom:api-v1-authoring-message", args=[thread_id]),
            {"content": "Draft", "backend_key": "dummy", "model_identifier": "test-model"},
        )
        job_id = message.json()["job"]["id"]
        assert other_client.get(reverse("liveclassroom:api-v1-authoring-job", args=[job_id])).status_code == 403

    assert models.status_code == 200
    assert models.json()["models"] == [{"backend_key": "dummy", "identifier": "test-model", "label": "Test model"}]


@pytest.mark.django_db
def test_authoring_message_is_idempotent_and_worker_does_not_persist_options():
    owner = get_user_model().objects.create_user(username="authoring-worker")
    thread = AuthoringThread.objects.create(owner=owner, title="Drafts")
    backend = DummyAI()
    client = Client()
    client.force_login(owner)
    payload = {
        "content": "Make this clearer",
        "backend_key": "dummy",
        "model_identifier": "test-model",
        "options": {"api_key": "secret-not-persisted"},
    }
    with override_settings(LIVECLASSROOM={"AI_BACKENDS": {"dummy": backend}}):
        first = post_json(
            client,
            reverse("liveclassroom:api-v1-authoring-message", args=[thread.id]),
            payload,
            HTTP_IDEMPOTENCY_KEY="authoring-message-once",
        )
        replay = post_json(
            client,
            reverse("liveclassroom:api-v1-authoring-message", args=[thread.id]),
            payload,
            HTTP_IDEMPOTENCY_KEY="authoring-message-once",
        )
        job_id = first.json()["job"]["id"]
        request = type("Request", (), {})()
        job = run_authoring_job(job_id=job_id, actor=owner, request=request, options=payload["options"])

    assert first.status_code == replay.status_code == 202
    assert replay.headers["Idempotent-Replay"] == "true"
    assert job.status == AuthoringJob.Status.SUCCEEDED
    assert len(backend.calls) == 1
    assert backend.calls[0][3] == payload["options"]
    assert "secret-not-persisted" not in json.dumps(list(AuthoringJob.objects.values()), default=str)
    assert thread.messages.filter(role="assistant").count() == 1


@pytest.mark.django_db
def test_unauthorized_and_source_text_attachments_are_rejected():
    user_model = get_user_model()
    owner = user_model.objects.create_user(username="attachment-owner")
    other = user_model.objects.create_user(username="attachment-other")
    activity = ActivityDefinition.objects.create(
        owner=other,
        title="Private activity",
        type_key="liveclassroom.poll",
        definition={"options": [{"id": "A", "text": "One"}]},
    )
    thread = AuthoringThread.objects.create(owner=owner)

    with pytest.raises(ClassroomError, match="permission to attach"):
        create_authoring_request(
            thread=thread,
            author=owner,
            content="Use this",
            backend_key="dummy",
            model_identifier="model",
            attachments=[{"source_type": "activity", "source_id": activity.id}],
        )

    provider = DummyProvider()
    with override_settings(LIVECLASSROOM={"CONTENT_PROVIDERS": {"dummy-provider": provider}}):
        with pytest.raises(ClassroomError, match="must not contain source content"):
            create_authoring_request(
                thread=thread,
                author=owner,
                content="Use this",
                backend_key="dummy",
                model_identifier="model",
                attachments=[
                    {
                        "source_type": "provider",
                        "provider": "dummy-provider",
                        "reference": {"kind": "note", "value": {"content": "protected text"}},
                    }
                ],
            )
    assert not AuthoringAttachment.objects.exists()


@pytest.mark.django_db
def test_provider_attachment_is_reauthorized_when_job_runs():
    owner = get_user_model().objects.create_user(username="provider-owner")
    thread = AuthoringThread.objects.create(owner=owner)
    backend = DummyAI()
    provider = VaultPubProvider()
    with override_settings(
        LIVECLASSROOM={"AI_BACKENDS": {"dummy": backend}, "CONTENT_PROVIDERS": {"vaultpub": provider}}
    ):
        prompt, job = create_authoring_request(
            thread=thread,
            author=owner,
            content="Summarize the note",
            backend_key="dummy",
            model_identifier="test-model",
            attachments=[
                {
                    "source_type": "vaultpub",
                    "reference": {"kind": "standalone", "value": {"note_path": "Deck.md"}},
                }
            ],
        )
        assert job.status == AuthoringJob.Status.QUEUED
        result = run_authoring_job(job_id=job.id, actor=owner)

    assert result.status == AuthoringJob.Status.SUCCEEDED
    assert backend.calls[0][2][0]["reference"]["value"]["note_path"] == "Deck.md"
    assert len(prompt.attachments.get().source_fingerprint) == 64


@pytest.mark.django_db
def test_package_worker_claims_queued_job_and_keeps_secrets_out_of_storage():
    owner = get_user_model().objects.create_user(username="package-worker-owner")
    thread = AuthoringThread.objects.create(owner=owner)
    backend = DummyAI()
    with override_settings(LIVECLASSROOM={"AI_BACKENDS": {"dummy": backend}}):
        _, job = create_authoring_request(
            thread=thread,
            author=owner,
            content="Draft a poll",
            backend_key="dummy",
            model_identifier="test-model",
        )
        output = StringIO()
        call_command("process_liveclassroom_ai_jobs", "--once", stdout=output)

    job.refresh_from_db()
    assert job.status == AuthoringJob.Status.SUCCEEDED
    assert job.lease_token == ""
    assert job.lease_expires_at is None
    assert "processed=1" in output.getvalue()


@pytest.mark.django_db
def test_expired_package_worker_lease_is_requeued_with_a_bounded_attempt():
    owner = get_user_model().objects.create_user(username="expired-worker-owner")
    thread = AuthoringThread.objects.create(owner=owner)
    job = AuthoringJob.objects.create(
        thread=thread,
        message=thread.messages.create(role="teacher", author=owner, content="Retry me"),
        backend_key="dummy",
        model_identifier="test-model",
        status=AuthoringJob.Status.RUNNING,
        lease_token="dead-worker",
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )

    assert recover_expired_authoring_jobs() == 1
    job.refresh_from_db()
    assert (job.status, job.attempt, job.error_code) == (AuthoringJob.Status.QUEUED, 2, "worker_timeout")
    claimed = claim_next_authoring_job(worker_token="replacement-worker")
    assert claimed is not None and claimed.id == job.id
    assert claimed.lease_token == "replacement-worker"
