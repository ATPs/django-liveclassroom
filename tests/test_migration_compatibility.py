"""The disposable development schema starts from a single current migration."""

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader


@pytest.mark.django_db
def test_fresh_schema_has_canonical_lesson_session_and_public_demo_tables():
    loader = MigrationLoader(connection)
    assert loader.graph.leaf_nodes("liveclassroom") == [("liveclassroom", "0008_native_decks")]
    assert sorted(key for key in loader.disk_migrations if key[0] == "liveclassroom") == [
        ("liveclassroom", "0001_initial"),
        ("liveclassroom", "0002_public_demo_lessons"),
        ("liveclassroom", "0003_test_participants"),
        ("liveclassroom", "0004_liveactivity_runtime_state"),
        ("liveclassroom", "0005_teaching_course_organization"),
        ("liveclassroom", "0006_activity_question_metadata"),
        ("liveclassroom", "0007_question_banks"),
        ("liveclassroom", "0008_native_decks"),
    ]
    tables = set(connection.introspection.table_names())
    assert {
        "liveclassroom_flowsnapshot",
        "liveclassroom_sessionplanstep",
        "liveclassroom_flowshare",
        "liveclassroom_demolesson",
        "liveclassroom_teachingcourse",
        "liveclassroom_questionbank",
        "liveclassroom_questionbankitem",
        "liveclassroom_deck",
        "liveclassroom_deckslide",
    } <= tables
    assert {"liveclassroom_flowitem", "liveclassroom_question"}.isdisjoint(tables)
    with connection.cursor() as cursor:
        columns = {c.name for c in connection.introspection.get_table_description(cursor, "liveclassroom_flowstep")}
    assert {"legacy_item_id", "kind", "title", "content"}.isdisjoint(columns)
    with connection.cursor() as cursor:
        definition_columns = {
            c.name
            for c in connection.introspection.get_table_description(
                cursor, "liveclassroom_activitydefinition"
            )
        }
    assert "metadata" in definition_columns
