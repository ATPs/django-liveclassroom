"""The bank migration is additive and preserves pre-bank reusable content."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_question_bank_migration_preserves_definition_history():
    previous = [("liveclassroom", "0006_activity_question_metadata")]
    current = [("liveclassroom", "0007_question_banks")]
    final = [("liveclassroom", "0014_assessment_sections")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(previous)
        apps = executor.loader.project_state(previous).apps
        user = apps.get_model("auth", "User").objects.create(username="bank-migration-owner")
        definition = apps.get_model("liveclassroom", "ActivityDefinition").objects.create(
            owner_id=user.id,
            title="Existing",
            type_key="liveclassroom.short_text",
            definition={"prompt": "Existing"},
            metadata={"tags": ["old"]},
        )
        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        migrated = apps.get_model("liveclassroom", "ActivityDefinition").objects.get(pk=definition.pk)
        assert migrated.definition == {"prompt": "Existing"}
        assert migrated.metadata == {"tags": ["old"]}
        bank = apps.get_model("liveclassroom", "QuestionBank").objects.create(owner_id=user.id, title="New bank")
        apps.get_model("liveclassroom", "QuestionBankItem").objects.create(bank_id=bank.id, definition_id=definition.pk)
    finally:
        MigrationExecutor(connection).migrate(final)
