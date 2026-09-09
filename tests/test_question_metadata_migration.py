import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_metadata_migration_preserves_existing_definition_revision_and_flow():
    old_target = [("liveclassroom", "0005_teaching_course_organization")]
    new_target = [("liveclassroom", "0006_activity_question_metadata")]
    final_target = [("liveclassroom", "0010_assessmentdefinition_assessmentitem_and_more")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(old_target)
        old_apps = executor.loader.project_state(old_target).apps
        user = old_apps.get_model("auth", "User").objects.create(username="metadata-migration")
        activity = old_apps.get_model("liveclassroom", "ActivityDefinition").objects.create(
            owner_id=user.id,
            type_key="liveclassroom.short_text",
            title="Existing",
            definition={"prompt": "Existing prompt"},
        )
        revision = old_apps.get_model("liveclassroom", "ActivityDefinitionRevision").objects.create(
            definition_id=activity.id,
            revision=1,
            payload=activity.definition,
            changed_by_id=user.id,
        )
        flow = old_apps.get_model("liveclassroom", "Flow").objects.create(
            created_by_id=user.id,
            title="Existing flow",
            slug="existing-flow",
        )
        old_apps.get_model("liveclassroom", "FlowStep").objects.create(
            flow_id=flow.id,
            activity_definition_id=activity.id,
            position=1,
        )
        session = old_apps.get_model("liveclassroom", "LiveSession").objects.create(
            teacher_id=user.id,
            title="Existing classroom",
            join_code="META01",
        )
        participant = old_apps.get_model("liveclassroom", "Participant").objects.create(
            session_id=session.id,
            guest_id="metadata-guest",
            display_name="Existing learner",
        )
        run = old_apps.get_model("liveclassroom", "LiveActivity").objects.create(
            session_id=session.id,
            sequence=1,
            kind="short_text",
            definition_snapshot={"prompt": "Existing prompt"},
        )
        submission = old_apps.get_model("liveclassroom", "Submission").objects.create(
            activity_id=run.id,
            participant_id=participant.id,
            answer={"text": "Existing answer"},
        )

        executor = MigrationExecutor(connection)
        executor.migrate(new_target)
        apps = executor.loader.project_state(new_target).apps
        migrated = apps.get_model("liveclassroom", "ActivityDefinition").objects.get(pk=activity.id)
        migrated_revision = apps.get_model("liveclassroom", "ActivityDefinitionRevision").objects.get(pk=revision.id)
        assert migrated.definition == {"prompt": "Existing prompt"}
        assert migrated.metadata == migrated_revision.metadata == {}
        assert apps.get_model("liveclassroom", "FlowStep").objects.filter(flow_id=flow.id).exists()
        assert apps.get_model("liveclassroom", "LiveSession").objects.filter(pk=session.id).exists()
        assert apps.get_model("liveclassroom", "Submission").objects.filter(pk=submission.id).exists()
    finally:
        MigrationExecutor(connection).migrate(final_target)
