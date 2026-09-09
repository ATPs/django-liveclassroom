import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_answer_revision_migration_is_additive_and_preserves_attempts():
    previous = [("liveclassroom", "0012_assessment_attempts")]
    current = [("liveclassroom", "0014_assessment_sections")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(previous)
        apps = executor.loader.project_state(previous).apps
        user = apps.get_model("auth", "User").objects.create(username="answer-migration")
        run = apps.get_model("liveclassroom", "AssessmentRun").objects.create(
            owner_id=user.id,
            source_version=1,
            audience="authenticated_link",
            title="Existing run",
            manifest={"items": []},
        )
        attempt = apps.get_model("liveclassroom", "AssessmentAttempt").objects.create(
            run_id=run.id, user_id=user.id, attempt_number=1
        )
        item = apps.get_model("liveclassroom", "AssessmentAttemptItem").objects.create(
            attempt_id=attempt.id, position=1, points="1", manifest={"type_key": "short_text"}
        )

        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        assert apps.get_model("liveclassroom", "AssessmentAttempt").objects.filter(pk=attempt.pk).exists()
        revision = apps.get_model("liveclassroom", "AnswerRevision").objects.create(
            item_id=item.id,
            version=1,
            answer={"text": "kept"},
            request_id="11111111-1111-4111-8111-111111111111",
            request_hash="a" * 64,
            actor_id=user.id,
        )
        assert revision.item_id == item.id
    finally:
        MigrationExecutor(connection).migrate(current)
