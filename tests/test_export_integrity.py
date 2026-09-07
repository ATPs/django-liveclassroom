import csv
import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import ActivityRunRevision, SessionChannelState, SessionEvent, SessionMessage
from liveclassroom.registry import ActivityType, activity_registry
from liveclassroom.services.classroom import (
    create_activity_definition,
    create_instant_session,
    join_guest,
    launch_item,
    start_session,
    submit_answer,
)


def _stream_bytes(response):
    return b"".join(response.streaming_content)


def _csv_rows(response):
    return list(csv.DictReader(io.StringIO(_stream_bytes(response).decode("utf-8"))))


@pytest.fixture
def export_teacher(db):
    return get_user_model().objects.create_user(username="export-integrity-teacher", password="password")


@pytest.fixture
def export_client(export_teacher):
    client = Client()
    client.force_login(export_teacher)
    return client


@pytest.mark.django_db
def test_empty_streaming_archive_and_csv_exports_have_valid_empty_shapes(export_client, export_teacher):
    session = create_instant_session(owner=export_teacher, title="Empty export")
    export_url = reverse("liveclassroom:api-v1-export", args=[session.id])

    archive_response = export_client.get(export_url, {"format": "json"})
    archive = json.loads(_stream_bytes(archive_response))
    assert archive["protocol_version"] == 1
    assert archive["participants"] == []
    assert archive["activities"] == []
    assert archive["responses"] == []
    assert archive["chat"] == []
    assert len(archive["events"]) == 1
    assert archive["events"][0]["event_type"] == "session.created"
    assert archive["events"][0]["actor_id"] == export_teacher.id
    assert archive["events"][0]["participant_id"] is None

    for dataset in ("summary", "responses", "participants", "chat"):
        response = export_client.get(export_url, {"format": "csv", "dataset": dataset})
        assert response.status_code == 200
        assert _csv_rows(response) == []


@pytest.mark.django_db
def test_populated_streaming_exports_include_identities_and_per_revision_performers(export_client, export_teacher):
    session = create_instant_session(owner=export_teacher, title="Populated export")
    definition = create_activity_definition(
        owner=export_teacher,
        title="Choose one",
        type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "A", "text": "First"}]},
    )
    start_session(session=session, actor=export_teacher)
    activity = launch_item(session=session, item=definition, actor=export_teacher)
    participant = join_guest(session=session, display_name="Ada")
    submission = submit_answer(
        activity=activity,
        participant=participant,
        answer={"choice": "A"},
        actor=export_teacher,
    )
    SessionMessage.objects.create(
        session=session,
        author=export_teacher,
        participant=participant,
        display_name=participant.display_name,
        body="Please repeat the question.",
    )
    sequence = (session.events.order_by("-sequence").values_list("sequence", flat=True).first() or 0) + 1
    SessionEvent.objects.create(
        session=session,
        sequence=sequence,
        event_type="export.audit",
        actor=export_teacher,
        participant=participant,
        payload={"source": "test"},
    )

    export_url = reverse("liveclassroom:api-v1-export", args=[session.id])
    archive_response = export_client.get(export_url, {"format": "json"})
    archive = json.loads(_stream_bytes(archive_response))
    assert "role" not in archive["participants"][0]
    response = archive["responses"][0]
    assert response["performed_by_id"] == export_teacher.id
    assert response["revisions"][0]["performed_by_id"] == export_teacher.id
    assert archive["chat"][0]["author_id"] == export_teacher.id
    assert archive["chat"][0]["participant_id"] == participant.id
    event = next(item for item in archive["events"] if item["event_type"] == "export.audit")
    assert event["actor_id"] == export_teacher.id
    assert event["participant_id"] == participant.id

    summary_rows = _csv_rows(export_client.get(export_url, {"format": "csv", "dataset": "summary"}))
    response_rows = _csv_rows(export_client.get(export_url, {"format": "csv", "dataset": "responses"}))
    participant_rows = _csv_rows(export_client.get(export_url, {"format": "csv", "dataset": "participants"}))
    chat_rows = _csv_rows(export_client.get(export_url, {"format": "csv", "dataset": "chat"}))
    assert len(summary_rows) == len(response_rows) == len(participant_rows) == len(chat_rows) == 1
    assert "role" not in participant_rows[0]
    assert response_rows[0]["performed_by_id"] == str(export_teacher.id)
    assert json.loads(response_rows[0]["revisions"])[0]["performed_by_id"] == export_teacher.id
    assert chat_rows[0]["author_id"] == str(export_teacher.id)
    assert chat_rows[0]["participant_id"] == str(participant.id)

    analytics = export_client.get(reverse("liveclassroom:api-v1-analytics", args=[session.id])).json()
    analytics_response = analytics["activities"][0]["responses"][0]
    assert analytics_response["performed_by_id"] == export_teacher.id
    assert analytics_response["revisions"][0]["performed_by_id"] == export_teacher.id
    assert analytics["chat"]["messages"][0]["author_id"] == export_teacher.id
    assert analytics["chat"]["messages"][0]["participant_id"] == participant.id
    assert submission.id == analytics_response["id"]


@pytest.mark.django_db
def test_response_export_uses_the_activity_revision_plugin_for_historical_answers(export_client, export_teacher):
    old_key = "tests.export_old"
    new_key = "tests.export_new"
    activity_registry.register(
        ActivityType(key=old_key, export_submission=lambda answer: {"exported_by": "old", "answer": answer})
    )
    activity_registry.register(
        ActivityType(key=new_key, export_submission=lambda answer: {"exported_by": "new", "answer": answer})
    )
    try:
        session = create_instant_session(owner=export_teacher, title="Historical plugin export")
        definition = create_activity_definition(
            owner=export_teacher,
            title="Versioned activity",
            type_key=old_key,
            definition={},
        )
        start_session(session=session, actor=export_teacher)
        activity = launch_item(session=session, item=definition, actor=export_teacher)
        participant = join_guest(session=session, display_name="Ada")
        submit_answer(activity=activity, participant=participant, answer={"value": "old"}, actor=export_teacher)
        # A type change is intentionally rejected by the editing service.  Build
        # this historical-plugin fixture through the trusted ORM boundary so the
        # export can prove it uses each answer's immutable run revision.
        new_snapshot = {"type_key": new_key, "kind": "export_new", "title": "Changed", "content": {}}
        new_run_revision = ActivityRunRevision.objects.create(
            activity=activity,
            revision=2,
            definition_snapshot=new_snapshot,
            created_by=export_teacher,
        )
        activity.definition_snapshot = new_snapshot
        activity.current_revision = new_run_revision
        activity.save(update_fields=["definition_snapshot", "current_revision"])
        SessionChannelState.objects.filter(session=session, current_activity=activity).update(
            current_revision=new_run_revision
        )
        submit_answer(activity=activity, participant=participant, answer={"value": "new"}, actor=export_teacher)

        export_url = reverse("liveclassroom:api-v1-export", args=[session.id])
        archive = json.loads(_stream_bytes(export_client.get(export_url, {"format": "json"})))
        revisions = archive["responses"][0]["revisions"]
        assert [revision["answer"]["exported_by"] for revision in revisions] == ["old", "new"]
        assert archive["responses"][0]["answer"]["exported_by"] == "new"
    finally:
        activity_registry.unregister(old_key)
        activity_registry.unregister(new_key)
