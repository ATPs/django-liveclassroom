"""The section migration backfills legacy fixed assessments without rewriting them."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_section_migration_backfills_default_section_and_preserves_item_order():
    previous = [("liveclassroom", "0013_attempt_answer_revisions")]
    current = [("liveclassroom", "0014_assessment_sections")]
    final = [("liveclassroom", "0021_authoringjob_artifact_type_authoringdraft")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(previous)
        apps = executor.loader.project_state(previous).apps
        user = apps.get_model("auth", "User").objects.create(username="section-migration")
        definitions = apps.get_model("liveclassroom", "ActivityDefinition")
        revisions = apps.get_model("liveclassroom", "ActivityDefinitionRevision")
        assessment_model = apps.get_model("liveclassroom", "AssessmentDefinition")
        item_model = apps.get_model("liveclassroom", "AssessmentItem")
        assessment = assessment_model.objects.create(owner_id=user.id, title="Legacy")
        keys = []
        for position in (2, 1):
            definition = definitions.objects.create(
                owner_id=user.id,
                title=f"Question {position}",
                type_key="liveclassroom.short_text",
                definition={"prompt": str(position)},
            )
            revision = revisions.objects.create(
                definition_id=definition.id,
                revision=1,
                payload={"prompt": str(position)},
                changed_by_id=user.id,
            )
            item = item_model.objects.create(
                assessment_id=assessment.id,
                position=position,
                question_revision_id=revision.id,
                points="1",
            )
            keys.append((position, item.id))
        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        section = apps.get_model("liveclassroom", "AssessmentSection").objects.get(assessment_id=assessment.id)
        entries = list(
            apps.get_model("liveclassroom", "AssessmentSectionEntry")
            .objects.filter(section_id=section.id)
            .order_by("position")
            .values_list("position", "kind", "item_id")
        )
        assert section.title == "Section 1"
        assert entries == [(1, "fixed", keys[1][1]), (2, "fixed", keys[0][1])]
    finally:
        MigrationExecutor(connection).migrate(final)
