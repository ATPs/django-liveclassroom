"""Regression coverage for upgrades from the former initial schema."""

import importlib
import json

import pytest
from django.apps import apps as global_apps
from django.contrib.auth import get_user_model
from django.db import connection

from liveclassroom.models import Flow, FlowStep, LiveActivity, LiveSession, SessionChannelState


@pytest.mark.django_db(transaction=True)
def test_legacy_authoring_schema_is_converted_before_cleanup():
    teacher = get_user_model().objects.create_user(username="legacy_teacher", password="password123")
    flow = Flow.objects.create(title="Legacy flow", slug="legacy-flow", created_by=teacher)
    session = LiveSession.objects.create(teacher=teacher, flow=flow, title="Legacy session")
    SessionChannelState.objects.filter(session=session).delete()
    activity = LiveActivity.objects.create(
        session=session,
        sequence=1,
        kind="question",
        definition_snapshot={"type_key": "liveclassroom.single_choice", "content": {}},
    )

    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE liveclassroom_flowstep ADD COLUMN legacy_item_id integer")
        cursor.execute("ALTER TABLE liveclassroom_flowstep ADD COLUMN kind varchar(32)")
        cursor.execute("ALTER TABLE liveclassroom_flowstep ADD COLUMN title varchar(200)")
        cursor.execute("ALTER TABLE liveclassroom_flowstep ADD COLUMN content text")
        cursor.execute("ALTER TABLE liveclassroom_livesession ADD COLUMN current_item_id integer")
        cursor.execute("ALTER TABLE liveclassroom_liveactivity ADD COLUMN source_item_id integer")
        cursor.execute(
            "CREATE TABLE liveclassroom_question ("
            "id integer primary key, question_type varchar(32), stem_markdown text, "
            "data text, answer text, explanation_markdown text)"
        )
        cursor.execute(
            "CREATE TABLE liveclassroom_flowitem ("
            "id integer primary key, flow_id integer, position integer, kind varchar(16), "
            "title varchar(200), content text, question_id integer, activity_definition_id integer)"
        )
        cursor.execute(
            "INSERT INTO liveclassroom_question "
            "(id, question_type, stem_markdown, data, answer, explanation_markdown) VALUES (%s, %s, %s, %s, %s, %s)",
            [
                1,
                "single_choice",
                "Which option is correct?",
                json.dumps({"options": [{"id": "A", "text": "Yes"}, {"id": "B", "text": "No"}]}),
                json.dumps(["A"]),
                "Because it is correct.",
            ],
        )
        cursor.execute(
            "INSERT INTO liveclassroom_flowitem "
            "(id, flow_id, position, kind, title, content, question_id, activity_definition_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [1, flow.id, 1, "question", "Legacy question", json.dumps({}), 1, None],
        )
        cursor.execute("UPDATE liveclassroom_livesession SET current_item_id = %s WHERE id = %s", [1, session.id])
        cursor.execute("UPDATE liveclassroom_liveactivity SET source_item_id = %s WHERE id = %s", [1, activity.id])

    migration = importlib.import_module("liveclassroom.migrations.0003_retire_legacy_authoring_schema")
    with connection.schema_editor() as editor:
        migration.forward(global_apps, editor)

    step = FlowStep.objects.get(flow=flow)
    assert step.activity_definition.type_key == "liveclassroom.single_choice"
    assert step.activity_definition.definition["options"] == [{"id": "A", "text": "Yes"}, {"id": "B", "text": "No"}]
    assert step.activity_definition.current_revision_id is not None
    states = list(SessionChannelState.objects.filter(session=session).order_by("channel"))
    assert [state.channel for state in states] == ["display", "participants"]
    assert all(state.current_activity_id == activity.id for state in states)

    tables = set(connection.introspection.table_names())
    assert "liveclassroom_flowitem" not in tables
    assert "liveclassroom_question" not in tables
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, "liveclassroom_flowstep")
    columns = {column.name for column in description}
    assert {"legacy_item_id", "kind", "title", "content"}.isdisjoint(columns)
