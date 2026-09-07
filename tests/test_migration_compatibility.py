"""The disposable development schema starts from a single current migration."""

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader


@pytest.mark.django_db
def test_fresh_schema_has_only_canonical_lesson_and_session_tables():
    loader = MigrationLoader(connection)
    assert loader.graph.leaf_nodes("liveclassroom") == [("liveclassroom", "0001_initial")]
    assert [key for key in loader.disk_migrations if key[0] == "liveclassroom"] == [
        ("liveclassroom", "0001_initial")
    ]
    tables = set(connection.introspection.table_names())
    assert {"liveclassroom_flowsnapshot", "liveclassroom_sessionplanstep", "liveclassroom_flowshare"} <= tables
    assert {"liveclassroom_flowitem", "liveclassroom_question"}.isdisjoint(tables)
    with connection.cursor() as cursor:
        columns = {c.name for c in connection.introspection.get_table_description(cursor, "liveclassroom_flowstep")}
    assert {"legacy_item_id", "kind", "title", "content"}.isdisjoint(columns)
