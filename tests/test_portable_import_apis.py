import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import ActivityDefinition
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.portable_content import export_portable


def _teacher(name):
    return get_user_model().objects.create_user(username=f"portable-api-{name}")


def _question(owner):
    return create_activity_definition(
        owner=owner,
        title="Portable question",
        type_key="single_choice",
        definition={"prompt": "Pick", "options": [{"id": "A", "text": "Yes"}], "answer": "A"},
    )


def _client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_portable_endpoints_export_copy_and_replay_without_leaking_source_ids():
    teacher = _teacher("copy")
    question = _question(teacher)
    client = _client(teacher)
    export = client.get(reverse("liveclassroom:api-v1-portable-export", args=["question", question.pk]))
    assert export.status_code == 200
    payload = export.json()
    assert "owner_id" not in json.dumps(payload)
    response = client.post(
        reverse("liveclassroom:api-v1-portable-import"),
        data=json.dumps({"payload": payload, "idempotency_key": "copy-question"}),
        content_type="application/json",
    )
    assert response.status_code == 201
    copied_id = response.json()["objects"][0]["id"]
    assert copied_id != question.pk
    replay = client.post(
        reverse("liveclassroom:api-v1-portable-import"),
        data=json.dumps({"payload": payload, "idempotency_key": "copy-question"}),
        content_type="application/json",
    )
    assert replay.status_code == 201
    assert replay["Idempotent-Replay"] == "true"
    assert replay.json()["objects"][0]["id"] == copied_id


@pytest.mark.django_db
def test_portable_import_rejects_changed_key_and_invalid_bundle_without_writes():
    teacher = _teacher("invalid")
    payload = export_portable(actor=teacher, kind="activity", object_id=_question(teacher).pk)
    client = _client(teacher)
    url = reverse("liveclassroom:api-v1-portable-import")
    first = client.post(
        url, data=json.dumps({"payload": payload, "idempotency_key": "copy"}), content_type="application/json"
    )
    assert first.status_code == 201
    before = ActivityDefinition.objects.count()
    changed = {**payload, "unexpected": True}
    replay = client.post(
        url, data=json.dumps({"payload": changed, "idempotency_key": "copy"}), content_type="application/json"
    )
    invalid = client.post(
        url, data=json.dumps({"payload": changed, "idempotency_key": "new"}), content_type="application/json"
    )
    assert replay.status_code == 409
    assert invalid.status_code == 400
    assert ActivityDefinition.objects.count() == before


@pytest.mark.django_db
def test_markdown_preview_and_commit_are_mounted_and_fingerprint_guarded():
    teacher = _teacher("markdown")
    client = _client(teacher)
    preview_url = reverse("liveclassroom:api-v1-markdown-import-preview")
    commit_url = reverse("liveclassroom:api-v1-markdown-import-commit")
    source = "kind: question\ntitle: Imported\ntype: markdown\nmarkdown: Hello\n"
    preview = client.post(
        preview_url,
        data=json.dumps({"filename": "question.yaml", "content": source}),
        content_type="application/json",
    )
    assert preview.status_code == 200
    draft = preview.json()
    assert draft["valid"] and draft["kind"] == "question"
    body = {
        "filename": "question.yaml",
        "content": source,
        "fingerprint": draft["fingerprint"],
        "idempotency_key": "markdown-copy",
    }
    committed = client.post(commit_url, data=json.dumps(body), content_type="application/json")
    assert committed.status_code == 201
    assert committed.json()["objects"][0]["kind"] == "activity"
    stale = {**body, "content": source + "changed"}
    assert client.post(commit_url, data=json.dumps(stale), content_type="application/json").status_code == 409
