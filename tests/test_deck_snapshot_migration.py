import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_deck_snapshot_migration_preserves_native_decks():
    old = [("liveclassroom", "0008_native_decks")]
    new = [("liveclassroom", "0009_deck_snapshots")]
    final = [("liveclassroom", "0021_authoringjob_artifact_type_authoringdraft")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        user = apps.get_model("auth", "User").objects.create(username="snapshot-migration")
        deck = apps.get_model("liveclassroom", "Deck").objects.create(owner_id=user.id, title="Existing")
        executor = MigrationExecutor(connection)
        executor.migrate(new)
        apps = executor.loader.project_state(new).apps
        assert apps.get_model("liveclassroom", "Deck").objects.filter(pk=deck.pk).exists()
        apps.get_model("liveclassroom", "DeckSnapshot").objects.create(
            source_deck_id=deck.pk,
            source_version=1,
            title="Frozen",
            public_manifest=[],
            private_notes={},
            fingerprint="a" * 64,
        )
    finally:
        MigrationExecutor(connection).migrate(final)
