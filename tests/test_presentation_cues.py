"""Presentation source discovery, cue validation, and explicit launch checks."""

import json
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from liveclassroom.providers import ContentReference
from liveclassroom.services.classroom import ClassroomError, create_activity_definition, start_session
from liveclassroom.services.deck_snapshots import create_deck_snapshot
from liveclassroom.services.decks import create_deck
from liveclassroom.services.flows import add_flow_step, create_flow
from liveclassroom.services.plans import create_session
from liveclassroom.services.presentation_cues import (
    create_presentation_cue,
    launch_presentation_cue,
    list_presentation_cues,
    provider_search,
)


@dataclass
class SearchProvider:
    key: str = "search-provider"
    fingerprint: str = "one"
    search_supported: bool = True

    def parse_reference(self, url, *, request=None):
        return ContentReference(self.key, "note", {"url": url})

    def validate_reference(self, reference, *, request=None):
        return reference

    def describe(self, reference, *, request=None):
        return {"title": "Accessible note", "source_fingerprint": self.fingerprint, "slide_capable": True}

    def search(self, query, *, request=None):
        return [{"title": "Accessible note", "provider": self.key, "url": f"https://example.test/{query}"}]

    def embed_url(self, reference, *, request=None):
        return reference.value["url"]


@pytest.fixture
def teacher(db):
    return get_user_model().objects.create_user(username="cue-teacher")


def _flow_and_session(teacher):
    flow = create_flow(title="Cue lesson", creator=teacher)
    definition = create_activity_definition(
        owner=teacher,
        title="Prediction",
        type_key="liveclassroom.short_text",
        definition={"prompt": "What do you predict?"},
    )
    add_flow_step(flow=flow, actor=teacher, activity_definition=definition)
    session = create_session(owner=teacher, title="Cue classroom", flow=flow)
    start_session(session=session, actor=teacher)
    return session


def _snapshot(teacher):
    deck = create_deck(
        actor=teacher,
        data={"title": "Cue deck", "slides": [{"markdown": "# One"}, {"markdown": "# Two"}]},
    )
    return create_deck_snapshot(actor=teacher, deck=deck, expected_version=1)


@pytest.mark.django_db
def test_native_cue_binds_stable_slide_and_launch_is_idempotent(teacher):
    session = _flow_and_session(teacher)
    snapshot = _snapshot(teacher)
    step = session.plan_steps.get()
    cue = create_presentation_cue(
        session=session,
        actor=teacher,
        data={"step_key": str(step.key), "source": {"type": "native", "snapshot_id": snapshot.pk, "slide_index": 1}},
    )
    assert cue["valid"] is True
    assert cue["source"]["slide_key"] == snapshot.public_manifest[1]["key"]
    first = launch_presentation_cue(session=session, actor=teacher, cue_id=cue["id"])
    second = launch_presentation_cue(session=session, actor=teacher, cue_id=cue["id"])
    assert first["activity_id"] == second["activity_id"]
    assert session.activities.count() == 1
    assert list_presentation_cues(session=session, actor=teacher)[0]["status"] == "ready"


@pytest.mark.django_db
def test_external_cue_is_reauthorized_and_fingerprint_change_requires_reattach(teacher):
    session = _flow_and_session(teacher)
    step = session.plan_steps.get()
    provider = SearchProvider()
    with override_settings(LIVECLASSROOM={"CONTENT_PROVIDERS": {provider.key: provider}}):
        cue = create_presentation_cue(
            session=session,
            actor=teacher,
            data={
                "step_key": str(step.key),
                "source": {
                    "type": "external",
                    "provider": provider.key,
                    "url": "https://example.test/note",
                    "slide_index": 1,
                },
            },
        )
        assert cue["source"]["title"] == "Accessible note"
        provider.fingerprint = "two"
        listed = list_presentation_cues(session=session, actor=teacher)
        assert listed[0]["status"] == "reattach_required"
        with pytest.raises(ClassroomError, match="Reattach"):
            launch_presentation_cue(session=session, actor=teacher, cue_id=cue["id"])


@pytest.mark.django_db
def test_provider_picker_routes_search_and_resolve_without_vault_listing(teacher):
    session = _flow_and_session(teacher)
    client = Client()
    client.force_login(teacher)
    provider = SearchProvider()
    with override_settings(LIVECLASSROOM={"CONTENT_PROVIDERS": {provider.key: provider}}):
        catalog = client.get(reverse("liveclassroom:api-v1-presentation-providers", args=[session.pk]))
        assert catalog.status_code == 200
        assert {item["key"] for item in catalog.json()["providers"]} == {"search-provider", "vaultpub"}
        searched = client.get(
            reverse("liveclassroom:api-v1-presentation-provider-search", args=[session.pk, provider.key]),
            {"q": "lecture"},
        )
        assert searched.status_code == 200
        assert searched.json()["results"][0]["source_fingerprint"] == "one"
        resolved = client.post(
            reverse("liveclassroom:api-v1-presentation-provider-resolve", args=[session.pk]),
            data=json.dumps({"provider": provider.key, "url": "https://example.test/note"}),
            content_type="application/json",
        )
        assert resolved.status_code == 200
        assert resolved.json()["source"]["reference"]["value"] == {"url": "https://example.test/note"}
    with pytest.raises(ClassroomError, match="query"):
        provider_search(actor=teacher, provider_key=provider.key, query="")


@pytest.mark.django_db
def test_cue_api_uses_command_receipts_and_rejects_foreign_step(teacher):
    session = _flow_and_session(teacher)
    snapshot = _snapshot(teacher)
    client = Client()
    client.force_login(teacher)
    url = reverse("liveclassroom:api-v1-presentation-cues", args=[session.pk])
    payload = {"step_key": str(session.plan_steps.get().key), "source": {"snapshot_id": snapshot.pk, "slide_index": 0}}
    first = client.post(url, data=json.dumps(payload), content_type="application/json", HTTP_IDEMPOTENCY_KEY="cue-once")
    replay = client.post(
        url, data=json.dumps(payload), content_type="application/json", HTTP_IDEMPOTENCY_KEY="cue-once"
    )
    assert first.status_code == 201
    assert replay.status_code == first.status_code
    assert replay.headers["Idempotent-Replay"] == "true"
    assert session.creation_settings.get("presentation_cues") is None
    other = get_user_model().objects.create_user(username="cue-other")
    foreign = create_session(owner=other, title="Other")
    with pytest.raises(ClassroomError, match="permission"):
        create_presentation_cue(
            session=foreign,
            actor=teacher,
            data={"step_key": "bad", "source": {"snapshot_id": snapshot.pk}},
        )
