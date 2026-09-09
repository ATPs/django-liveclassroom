import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_assessment_migration_is_additive_and_keeps_existing_question_history():
    previous = [("liveclassroom", "0009_deck_snapshots")]
    current = [("liveclassroom", "0014_assessment_sections")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(previous)
        apps = executor.loader.project_state(previous).apps
        user = apps.get_model("auth", "User").objects.create(username="assessment-migration-owner")
        definition = apps.get_model("liveclassroom", "ActivityDefinition").objects.create(
            owner_id=user.id,
            title="Existing question",
            type_key="liveclassroom.short_text",
            definition={"prompt": "Existing"},
            metadata={"default_points": "2"},
        )
        revision = apps.get_model("liveclassroom", "ActivityDefinitionRevision").objects.create(
            definition_id=definition.id,
            revision=1,
            payload={"prompt": "Existing"},
            metadata={"default_points": "2"},
            changed_by_id=user.id,
        )
        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        migrated = apps.get_model("liveclassroom", "ActivityDefinition").objects.get(pk=definition.pk)
        assert migrated.definition == {"prompt": "Existing"}
        assessment = apps.get_model("liveclassroom", "AssessmentDefinition").objects.create(
            owner_id=user.id, title="Migrated assessment", settings={"max_attempts": 1}
        )
        item = apps.get_model("liveclassroom", "AssessmentItem").objects.create(
            assessment_id=assessment.id,
            position=1,
            question_revision_id=revision.id,
            points="2",
        )
        assert item.assessment_id == assessment.id
    finally:
        MigrationExecutor(connection).migrate(current)
