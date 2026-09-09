"""Focused security and rendering checks for optional Markdown fragments."""

from __future__ import annotations

import json

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import RequestFactory, override_settings

from liveclassroom.api import _public_activity
from liveclassroom.fragment_views import (
    definition_fragment,
    fragment_markdown,
    session_fragment,
)
from liveclassroom.integrations import vaultpub_fragments
from liveclassroom.integrations.vaultpub_documents import VaultPubUnavailable
from liveclassroom.models import ActivityDefinitionRevision, ActivityRunRevision
from liveclassroom.services.classroom import (
    create_activity_definition,
    create_instant_session,
    join_guest,
    launch_item,
    publish_activity_to_channel,
    start_session,
)


@pytest.fixture
def request_factory() -> RequestFactory:
    return RequestFactory()


@pytest.fixture
def vaultpub_enabled():
    with override_settings(INSTALLED_APPS=[*settings.INSTALLED_APPS, "vaultpub.django_app"]):
        yield


def _request(factory: RequestFactory, user, path: str = "/"):
    request = factory.get(path)
    request.user = user
    return request


def _definition(owner, *, prompt: str = "# Prompt\n\n| A | B |\n|---|---|\n| 1 | 2 |"):
    return create_activity_definition(
        owner=owner,
        title="Fragment question",
        type_key="liveclassroom.short_text",
        definition={"prompt": prompt, "explanation_markdown": "## Explanation\n\nSafe text."},
    )


def test_fragment_adapter_uses_vaultpub_safe_article_and_private_response(vaultpub_enabled, request_factory):
    response = vaultpub_fragments.render_fragment(
        request_factory.get("/"),
        markdown="# Prompt\n\n<script>alert(1)</script>\n\n| A | B |\n|---|---|\n| 1 | 2 |",
        url_prefix="/classroom/api/v1/fragments/example/",
        revision_key="definition:1:r1",
    )

    payload = json.loads(response.content)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert payload["revision_key"] == "definition:1:r1"
    assert "<table" in payload["html"]
    assert "<script" not in payload["html"]
    assert payload["resources"] == []
    assert "/tmp/" not in response.content.decode()


def test_fragment_adapter_reports_optional_dependency_without_path(request_factory, monkeypatch):
    monkeypatch.setattr(
        vaultpub_fragments,
        "_vaultpub_api",
        lambda: (_ for _ in ()).throw(VaultPubUnavailable("VaultPub is unavailable.")),
    )
    with pytest.raises(VaultPubUnavailable, match="unavailable"):
        vaultpub_fragments.render_fragment(
            request_factory.get("/"),
            markdown="# Prompt",
            url_prefix="/classroom/api/v1/fragments/example/",
            revision_key="definition:1:r1",
        )


@pytest.mark.django_db
def test_definition_view_is_owner_scoped_and_whitelists_fields(vaultpub_enabled, request_factory):
    teacher = get_user_model().objects.create_user(username="fragment-owner")
    other = get_user_model().objects.create_user(username="fragment-other")
    activity = _definition(teacher)
    revision = ActivityDefinitionRevision.objects.get(pk=activity.current_revision_id)

    response = definition_fragment(
        _request(request_factory, teacher),
        revision.id,
        "prompt",
        url_prefix="/classroom/api/v1/activity-fragments/1/prompt/",
    )
    assert response.status_code == 200
    assert json.loads(response.content)["revision_key"] == f"definition:{activity.id}:r1"
    with pytest.raises(Http404):
        definition_fragment(
            _request(request_factory, other),
            revision.id,
            "prompt",
            url_prefix="/classroom/api/v1/activity-fragments/1/prompt/",
        )
    with pytest.raises(Http404):
        definition_fragment(
            _request(request_factory, teacher),
            revision.id,
            "answer",
            url_prefix="/classroom/api/v1/activity-fragments/1/answer/",
        )
    assert fragment_markdown(revision, "prompt").startswith("# Prompt")


@pytest.mark.django_db
def test_session_view_repeats_current_prompt_and_feedback_reveal_boundary(vaultpub_enabled, request_factory):
    teacher = get_user_model().objects.create_user(username="fragment-session-teacher")
    session = create_instant_session(owner=teacher, title="Fragment session")
    start_session(session=session, actor=teacher)
    activity_definition = _definition(teacher, prompt="# Current prompt")
    activity = launch_item(session=session, item=activity_definition, actor=teacher, channel="participants")
    publish_activity_to_channel(session=session, activity=activity, channel="participants", actor=teacher)
    revision = ActivityRunRevision.objects.get(activity=activity)
    participant = join_guest(session=session, display_name="Reader")

    student_request = _request(request_factory, AnonymousUser(), "/classroom/")
    student_request.session = {f"liveclassroom.participant.{session.id}": participant.id}
    prefix = "/classroom/api/v1/session-fragments/1/1/prompt/"
    prompt = session_fragment(
        student_request,
        session.id,
        revision.id,
        "prompt",
        url_prefix=prefix,
    )
    assert prompt.status_code == 200

    with pytest.raises(Http404):
        session_fragment(
            student_request,
            session.id,
            revision.id,
            "explanation",
            url_prefix=prefix,
        )
    state = session.channel_states.get(channel="participants")
    state.show_explanation = True
    state.save(update_fields=["show_explanation"])
    explanation = session_fragment(
        student_request,
        session.id,
        revision.id,
        "explanation",
        url_prefix=prefix,
    )
    assert explanation.status_code == 200
    assert "Explanation" in json.loads(explanation.content)["html"]

    state.show_prompt = False
    state.save(update_fields=["show_prompt"])
    with pytest.raises(Http404):
        session_fragment(student_request, session.id, revision.id, "prompt", url_prefix=prefix)


@pytest.mark.django_db
def test_public_activity_only_issues_fragment_urls_for_visible_fields(vaultpub_enabled, request_factory):
    teacher = get_user_model().objects.create_user(username="fragment-payload-teacher")
    session = create_instant_session(owner=teacher, title="Fragment payload session")
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=_definition(teacher), actor=teacher, channel="participants")
    publish_activity_to_channel(session=session, activity=activity, channel="participants", actor=teacher)
    participant = join_guest(session=session, display_name="Payload reader")
    state = session.channel_states.get(channel="participants")
    payload = _public_activity(
        activity,
        channel_state=state,
        request=_request(request_factory, AnonymousUser(), "/classroom/"),
        session=session,
        participant=participant,
    )
    urls = payload["definition"]["fragment_urls"]
    assert set(urls) == {"prompt"}
    assert urls["prompt"]["url"].startswith("/api/v1/sessions/")
    state.show_explanation = True
    state.save(update_fields=["show_explanation"])
    assert "explanation" in _public_activity(
        activity,
        channel_state=state,
        request=_request(request_factory, AnonymousUser(), "/classroom/"),
        session=session,
        participant=participant,
    )["definition"]["fragment_urls"]


@pytest.mark.django_db
def test_session_fragment_staff_can_review_but_wrong_revision_is_hidden(vaultpub_enabled, request_factory):
    teacher = get_user_model().objects.create_user(username="fragment-staff")
    session = create_instant_session(owner=teacher, title="Staff fragment session")
    start_session(session=session, actor=teacher)
    activity_definition = _definition(teacher)
    activity = launch_item(session=session, item=activity_definition, actor=teacher, channel="participants")
    revision = ActivityRunRevision.objects.get(activity=activity)
    response = session_fragment(
        _request(request_factory, teacher),
        session.id,
        revision.id,
        "explanation",
        url_prefix="/classroom/api/v1/session-fragments/1/1/explanation/",
    )
    assert response.status_code == 200
    with pytest.raises(Http404):
        session_fragment(
            _request(request_factory, teacher),
            session.id + 100,
            revision.id,
            "prompt",
            url_prefix="/classroom/api/v1/session-fragments/1/1/prompt/",
        )


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_fragment_adapter_only_allows_get_and_head(request_factory, method):
    response = getattr(request_factory, method)("/")
    result = vaultpub_fragments.render_fragment(
        response,
        markdown="# Prompt",
        url_prefix="/classroom/api/v1/fragments/example/",
        revision_key="definition:1:r1",
    )
    assert result.status_code == 405
    assert result["Allow"] == "GET, HEAD"
