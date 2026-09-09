"""Reusable question metadata validation, history, API, and delivery tests."""

import json
from copy import deepcopy

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import ActivityDefinition, SessionChannelState
from liveclassroom.services.classroom import (
    ClassroomError,
    create_activity_definition,
    create_instant_session,
    join_guest,
    launch_item,
    publish_activity_to_channel,
    revise_activity_definition,
    start_session,
)
from liveclassroom.services.question_metadata import (
    FEEDBACK_MAX_LENGTH,
    OBJECTIVE_MAX_LENGTH,
    TAG_MAX_LENGTH,
    TOPIC_MAX_LENGTH,
    validate_question_metadata,
)


def test_metadata_normalizes_without_mutating_input():
    value = {
        "topic": " Cell biology ",
        "difficulty": " EASY ",
        "learning_objectives": [" Explain transcription ", "explain transcription", ""],
        "tags": [" RNA ", "rna", "gene expression"],
        "default_points": "2.00",
        "feedback": {"correct": " Well done ", "incorrect": " Review slide 3 "},
    }
    original = deepcopy(value)
    assert validate_question_metadata(value) == {
        "topic": "Cell biology",
        "difficulty": "easy",
        "learning_objectives": ["Explain transcription"],
        "tags": ["RNA", "gene expression"],
        "default_points": "2",
        "feedback": {"correct": "Well done", "incorrect": "Review slide 3"},
    }
    assert value == original


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"unknown": True},
        {"topic": 1},
        {"topic": "x" * (TOPIC_MAX_LENGTH + 1)},
        {"difficulty": "expert"},
        {"tags": "rna"},
        {"tags": [1]},
        {"tags": ["x" * (TAG_MAX_LENGTH + 1)]},
        {"learning_objectives": ["x"] * 51},
        {"learning_objectives": ["x" * (OBJECTIVE_MAX_LENGTH + 1)]},
        {"default_points": True},
        {"default_points": 0},
        {"default_points": 1001},
        {"default_points": "NaN"},
        {"default_points": "Infinity"},
        {"feedback": []},
        {"feedback": {"hint": "No"}},
        {"feedback": {"correct": "x" * (FEEDBACK_MAX_LENGTH + 1)}},
    ],
)
def test_metadata_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        validate_question_metadata(value)


@pytest.mark.django_db
def test_create_and_revise_preserve_immutable_metadata():
    teacher = get_user_model().objects.create_user(username="metadata-teacher")
    activity = create_activity_definition(
        owner=teacher,
        title="Metadata question",
        type_key="liveclassroom.short_text",
        definition={"prompt": "Name it"},
        metadata={"topic": "Biology", "tags": ["RNA"]},
    )
    first = activity.current_revision
    assert activity.metadata == first.metadata == {"topic": "Biology", "tags": ["RNA"]}

    second = revise_activity_definition(
        activity=activity,
        definition={"prompt": "Name the molecule"},
        actor=teacher,
        metadata={"topic": "Molecular biology", "default_points": 2},
    )
    activity.refresh_from_db()
    first.refresh_from_db()
    assert first.metadata == {"topic": "Biology", "tags": ["RNA"]}
    assert second.metadata == activity.metadata == {"topic": "Molecular biology", "default_points": "2"}

    other = get_user_model().objects.create_user(username="metadata-other")
    with pytest.raises(ClassroomError, match="permission"):
        revise_activity_definition(
            activity=activity,
            definition=activity.definition,
            actor=other,
            metadata={},
        )


@pytest.mark.django_db
def test_authoring_api_round_trip_and_delivery_feedback_redaction():
    teacher = get_user_model().objects.create_user(username="metadata-api-teacher")
    client = Client()
    client.force_login(teacher)
    response = client.post(
        reverse("liveclassroom:api-v1-activity-definitions"),
        data=json.dumps({
            "title": "API metadata",
            "type_key": "liveclassroom.single_choice",
            "definition": {"options": [{"id": "A", "text": "One"}], "answer": "A"},
            "metadata": {
                "difficulty": "medium",
                "default_points": "3.0",
                "feedback": {"correct": "Correct feedback"},
            },
        }),
        content_type="application/json",
    )
    assert response.status_code == 201
    activity = ActivityDefinition.objects.get(pk=response.json()["id"])
    assert response.json()["metadata"]["default_points"] == "3"
    listed = client.get(reverse("liveclassroom:api-v1-activity-definitions")).json()["activities"]
    assert listed[0]["metadata"] == activity.metadata

    session = create_instant_session(owner=teacher, title="Metadata delivery")
    start_session(session=session, actor=teacher)
    launched = launch_item(session=session, item=activity, actor=teacher)
    publish_activity_to_channel(
        session=session,
        activity=launched,
        channel=SessionChannelState.Channel.PARTICIPANTS,
        actor=teacher,
    )
    from liveclassroom.services.runtime import activity_snapshot

    snapshot = activity_snapshot(activity)
    assert snapshot["metadata"] == activity.metadata
    assert launched.definition_snapshot["metadata"] == activity.metadata

    participant = join_guest(session=session, display_name="Metadata learner")
    student = Client()
    browser_session = student.session
    browser_session[f"liveclassroom.participant.{session.id}"] = participant.id
    browser_session.save()
    state_url = reverse("liveclassroom:api-v1-state", args=[session.id])
    hidden = student.get(state_url, {"channel": "participants"})
    assert hidden.status_code == 200
    assert "metadata" not in hidden.json()["current_activity"]["definition"]

    SessionChannelState.objects.filter(
        session=session,
        channel=SessionChannelState.Channel.PARTICIPANTS,
    ).update(show_explanation=True)
    revealed = student.get(state_url, {"channel": "participants"})
    assert revealed.status_code == 200
    assert revealed.json()["current_activity"]["definition"]["metadata"] == {
        "feedback": {"correct": "Correct feedback"}
    }
