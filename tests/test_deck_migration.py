import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_deck_migration_preserves_question_bank_history():
    old = [("liveclassroom", "0007_question_banks")]
    new = [("liveclassroom", "0008_native_decks")]
    final = [("liveclassroom", "0010_assessmentdefinition_assessmentitem_and_more")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        user = apps.get_model("auth", "User").objects.create(username="deck-migration")
        bank = apps.get_model("liveclassroom", "QuestionBank").objects.create(owner_id=user.id, title="Existing")
        executor = MigrationExecutor(connection)
        executor.migrate(new)
        apps = executor.loader.project_state(new).apps
        assert apps.get_model("liveclassroom", "QuestionBank").objects.filter(pk=bank.pk).exists()
        deck = apps.get_model("liveclassroom", "Deck").objects.create(owner_id=user.id, title="New deck")
        apps.get_model("liveclassroom", "DeckSlide").objects.create(deck_id=deck.id, position=1, markdown="# New")
    finally:
        MigrationExecutor(connection).migrate(final)
