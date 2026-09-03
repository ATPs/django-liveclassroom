import json
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.importers import (
    ImportError,
    import_json_flow,
    parse_json_flow,
)
from liveclassroom.models import ActivityDefinition, Course, Flow, FlowItem, FlowStep


def post_json(client, url, payload=None, **headers):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json", **headers)


@pytest.fixture
def teacher(db):
    return get_user_model().objects.create_user(username="json-teacher")


def test_parse_json_flow_valid():
    source = {
        "title": "Quantum Physics Intro",
        "slug": "quantum-intro",
        "description": "Basics of quantum mechanics",
        "steps": [
            {
                "type": "single_choice",
                "title": "Planck constant",
                "definition": {
                    "prompt": "Is the Planck constant positive?",
                    "options": [{"id": "A", "text": "Yes"}, {"id": "B", "text": "No"}],
                    "answer": ["A"],
                },
            },
            {
                "type": "numeric",
                "title": "Spin of electron",
                "definition": {
                    "prompt": "What is electron spin?",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "step": 0.5,
                },
            },
        ],
    }

    parsed = parse_json_flow(source)
    assert parsed["title"] == "Quantum Physics Intro"
    assert parsed["slug"] == "quantum-intro"
    assert len(parsed["steps"]) == 2
    assert parsed["steps"][0]["type_key"] == "liveclassroom.single_choice"
    assert parsed["steps"][1]["type_key"] == "liveclassroom.numeric"


def test_parse_json_flow_rejects_malformed_json():
    with pytest.raises(ImportError, match="Invalid JSON"):
        parse_json_flow("{bad json")


def test_parse_json_flow_rejects_missing_title():
    with pytest.raises(ImportError, match="Flow title is required"):
        parse_json_flow({"title": "", "steps": [{"type": "single_choice"}]})


def test_parse_json_flow_rejects_empty_steps():
    with pytest.raises(ImportError, match="contains no importable steps"):
        parse_json_flow({"title": "Empty Flow", "steps": []})


def test_parse_json_flow_rejects_unsupported_type():
    with pytest.raises(ImportError, match="Unsupported activity type"):
        parse_json_flow({
            "title": "Flow",
            "steps": [{"type": "nonexistent_type", "definition": {}}],
        })


def test_parse_json_flow_rejects_invalid_definition():
    with pytest.raises(ImportError, match="Invalid activity definition"):
        parse_json_flow({
            "title": "Bad Flow",
            "steps": [
                {
                    "type": "single_choice",
                    "title": "Bad Choice",
                    "definition": {"options": []},  # Requires at least one option
                }
            ],
        })


@pytest.mark.django_db
def test_import_json_flow_success(teacher):
    source = {
        "title": "Computer Networks Flow",
        "slug": "networks-flow",
        "description": "OSI Model and TCP/IP",
        "steps": [
            {
                "type": "single_choice",
                "title": "OSI Layer",
                "question": "Which layer is HTTP?",
                "choices": ["Application", "Transport", "Network"],
                "answer": ["Application"],
            },
            {
                "type": "poll",
                "title": "Preferred Protocol",
                "options": ["TCP", "UDP", "QUIC"],
            },
        ],
    }

    course = Course.objects.create(title="Networking Course", slug="net-course", created_by=teacher)
    flow = import_json_flow(source=source, course=course, creator=teacher)

    assert flow.title == "Computer Networks Flow"
    assert flow.slug == "networks-flow"
    assert flow.course == course
    assert flow.steps.count() == 2
    assert flow.items.count() == 2

    step1 = flow.steps.first()
    assert step1.position == 1
    assert step1.activity_definition is not None
    assert step1.activity_definition.type_key == "liveclassroom.single_choice"
    assert len(step1.activity_definition.definition["options"]) == 3

    step2 = flow.steps.last()
    assert step2.position == 2
    assert step2.activity_definition is not None
    assert step2.activity_definition.type_key == "liveclassroom.poll"


@pytest.mark.django_db
def test_import_json_flow_atomic_rollback_on_invalid_step(teacher):
    # Step 1 is valid, Step 2 is invalid (numeric minimum > maximum)
    bad_source = {
        "title": "Rollback Test Flow",
        "slug": "rollback-test",
        "steps": [
            {
                "type": "single_choice",
                "title": "Valid Step",
                "options": ["A", "B"],
            },
            {
                "type": "numeric",
                "title": "Invalid Step",
                "minimum": 10.0,
                "maximum": 5.0,  # Invalid: minimum > maximum
            },
        ],
    }

    initial_flow_count = Flow.objects.count()
    initial_act_count = ActivityDefinition.objects.count()

    with pytest.raises(ImportError, match="minimum cannot be greater than maximum"):
        import_json_flow(source=bad_source, creator=teacher)

    # Verify no database rows were created (total rollback)
    assert Flow.objects.count() == initial_flow_count
    assert ActivityDefinition.objects.count() == initial_act_count


@pytest.mark.django_db
def test_import_json_flow_duplicate_slug_rejected(teacher):
    source = {
        "title": "Unique Flow",
        "slug": "unique-flow",
        "steps": [
            {"type": "single_choice", "options": ["Yes", "No"]}
        ],
    }
    import_json_flow(source=source, creator=teacher)

    with pytest.raises(ImportError, match="already has a flow with slug"):
        import_json_flow(source=source, creator=teacher)


@pytest.mark.django_db
def test_import_flow_api_json_and_markdown(teacher):
    client = Client()
    client.force_login(teacher)

    # 1. Unauthenticated request rejected
    anon = Client()
    assert anon.post(reverse("liveclassroom:api-v1-flow-import"), data="{}", content_type="application/json").status_code == 401

    # 2. Import via JSON payload
    json_payload = {
        "format": "json",
        "source": {
            "title": "API Imported JSON Flow",
            "slug": "api-json-flow",
            "steps": [
                {
                    "type": "poll",
                    "title": "API Poll",
                    "options": ["Option 1", "Option 2"],
                }
            ],
        },
    }
    res_json = post_json(client, reverse("liveclassroom:api-v1-flow-import"), json_payload)
    assert res_json.status_code == 201
    assert res_json.json()["title"] == "API Imported JSON Flow"
    assert len(res_json.json()["steps"]) == 1

    # 3. Import via Markdown payload
    md_payload = {
        "format": "markdown",
        "source": """---
title: API Imported Markdown Flow
slug: api-md-flow
---
# Introduction
:::quiz
type: single_choice
question: What is Markdown?
choices: ["Markup language", "Database"]
answer: ["Markup language"]
:::
""",
    }
    res_md = post_json(client, reverse("liveclassroom:api-v1-flow-import"), md_payload)
    assert res_md.status_code == 201
    assert res_md.json()["title"] == "API Imported Markdown Flow"
    assert len(res_md.json()["steps"]) == 2

    # 4. Import invalid payload returns 400
    res_bad = post_json(client, reverse("liveclassroom:api-v1-flow-import"), {"format": "json", "source": {"title": "Bad", "steps": []}})
    assert res_bad.status_code == 400
