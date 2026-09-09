"""Authoring API contracts exercised by the objective-grading editor."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse


def post_json(client, url, payload, **headers):
    return client.post(
        url,
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )


@pytest.mark.django_db
def test_editor_grading_shapes_round_trip_through_authoring_api():
    teacher = get_user_model().objects.create_user(username="grading-editor-api-teacher")
    client = Client()
    client.force_login(teacher)
    endpoint = reverse("liveclassroom:api-v1-activity-create")
    cases = [
        (
            "liveclassroom.single_choice",
            {
                "options": [{"id": "A", "text": "One"}, {"id": "B", "text": "Two"}],
                "answer": "B",
            },
            {"answer": "B"},
        ),
        (
            "liveclassroom.multiple_choice",
            {
                "options": [
                    {"id": "A", "text": "One"},
                    {"id": "B", "text": "Two"},
                    {"id": "C", "text": "Three"},
                ],
                "answer": ["B", "A", "B"],
                "partial_credit": True,
            },
            {"answer": ["B", "A"], "partial_credit": True},
        ),
        (
            "liveclassroom.true_false",
            {"prompt": "The statement is true.", "answer": "true"},
            {"answer": "true"},
        ),
        (
            "liveclassroom.numeric",
            {"prompt": "What is pi?", "answer": "3.14", "tolerance": "0.01"},
            {"answer": "3.14", "tolerance": "0.01"},
        ),
        (
            "liveclassroom.short_text",
            {"prompt": "Name the molecule.", "answer": [" RNA ", "DNA", "RNA"], "case_sensitive": True},
            {"answer": ["RNA", "DNA"], "case_sensitive": True},
        ),
    ]

    created_ids = []
    for index, (type_key, definition, expected) in enumerate(cases):
        response = post_json(
            client,
            endpoint,
            {"title": f"Editor question {index}", "type_key": type_key, "definition": definition},
            HTTP_IDEMPOTENCY_KEY=f"grading-editor-create-{index}",
        )
        assert response.status_code == 201, response.content
        created_ids.append(response.json()["id"])

    listed = client.get(reverse("liveclassroom:api-v1-activity-definitions"))
    assert listed.status_code == 200
    by_id = {item["id"]: item for item in listed.json()["activities"]}
    for created_id, (_, _, expected) in zip(created_ids, cases):
        definition = by_id[created_id]["definition"]
        for key, value in expected.items():
            assert definition[key] == value


@pytest.mark.django_db
def test_editor_revision_replaces_legacy_answer_and_removes_irrelevant_keys():
    teacher = get_user_model().objects.create_user(username="grading-editor-revision-teacher")
    client = Client()
    client.force_login(teacher)
    create_url = reverse("liveclassroom:api-v1-activity-create")
    created = post_json(
        client,
        create_url,
        {
            "title": "Legacy answer",
            "type_key": "liveclassroom.numeric",
            "definition": {"prompt": "Value", "correct_answer": "5", "tolerance": "0.5"},
        },
        HTTP_IDEMPOTENCY_KEY="grading-editor-legacy-create",
    )
    assert created.status_code == 201, created.content
    activity_id = created.json()["id"]

    revised = post_json(
        client,
        reverse("liveclassroom:api-v1-activity-revise", args=[activity_id]),
        {"definition": {"prompt": "Value", "answer": "6"}},
        HTTP_IDEMPOTENCY_KEY="grading-editor-revise",
    )
    assert revised.status_code == 201, revised.content

    listed = client.get(reverse("liveclassroom:api-v1-activity-definitions")).json()["activities"]
    definition = next(item for item in listed if item["id"] == activity_id)["definition"]
    assert definition["answer"] == "6"
    assert "correct_answer" not in definition
    assert "tolerance" not in definition


@pytest.mark.django_db
def test_editor_rejects_tolerance_without_a_numeric_answer_and_keeps_response_error():
    teacher = get_user_model().objects.create_user(username="grading-editor-invalid-teacher")
    client = Client()
    client.force_login(teacher)

    response = post_json(
        client,
        reverse("liveclassroom:api-v1-activity-create"),
        {
            "title": "Missing answer",
            "type_key": "liveclassroom.numeric",
            "definition": {"prompt": "Value", "tolerance": "0.5"},
        },
        HTTP_IDEMPOTENCY_KEY="grading-editor-invalid-create",
    )

    assert response.status_code == 400
    assert "tolerance" in response.json()["detail"]
