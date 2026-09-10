"""Populated migration-history checks for the current additive schema."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

CURRENT = "0021_authoringjob_artifact_type_authoringdraft"


def _target(name: str):
    return [("liveclassroom", name)]


@pytest.mark.django_db(transaction=True)
def test_populated_history_from_metadata_leaf_reaches_current_leaf_without_rewriting_snapshots():
    previous = _target("0006_activity_question_metadata")
    current = _target(CURRENT)
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(previous)
        old_apps = executor.loader.project_state(previous).apps
        User = old_apps.get_model("auth", "User")
        ActivityDefinition = old_apps.get_model("liveclassroom", "ActivityDefinition")
        ActivityRevision = old_apps.get_model("liveclassroom", "ActivityDefinitionRevision")
        Flow = old_apps.get_model("liveclassroom", "Flow")
        FlowStep = old_apps.get_model("liveclassroom", "FlowStep")
        LiveSession = old_apps.get_model("liveclassroom", "LiveSession")
        LiveActivity = old_apps.get_model("liveclassroom", "LiveActivity")
        ActivityRunRevision = old_apps.get_model("liveclassroom", "ActivityRunRevision")
        Participant = old_apps.get_model("liveclassroom", "Participant")
        Submission = old_apps.get_model("liveclassroom", "Submission")
        SubmissionRevision = old_apps.get_model("liveclassroom", "SubmissionRevision")

        teacher = User.objects.create(username="history-teacher")
        learner = User.objects.create(username="history-learner")
        definition = ActivityDefinition.objects.create(
            owner_id=teacher.id,
            title="Historical question",
            type_key="liveclassroom.short_text",
            definition={"prompt": "Before migration"},
            metadata={"topic": "history"},
            status="ready",
        )
        source_revision = ActivityRevision.objects.create(
            definition_id=definition.id,
            revision=1,
            payload={"prompt": "Before migration"},
            metadata={"topic": "history"},
            changed_by_id=teacher.id,
        )
        ActivityDefinition.objects.filter(pk=definition.pk).update(current_revision_id=source_revision.id)
        flow = Flow.objects.create(title="Historical lesson", slug="historical-lesson", created_by_id=teacher.id)
        step = FlowStep.objects.create(flow_id=flow.id, position=1, activity_definition_id=definition.id)
        session = LiveSession.objects.create(title="Historical live class", teacher_id=teacher.id, flow_id=flow.id)
        activity = LiveActivity.objects.create(
            session_id=session.id,
            source_step_id=step.id,
            sequence=1,
            kind="short_text",
            definition_snapshot={"prompt": "Before migration"},
        )
        run_revision = ActivityRunRevision.objects.create(
            activity_id=activity.id,
            revision=1,
            source_revision_id=source_revision.id,
            definition_snapshot={"prompt": "Before migration"},
            created_by_id=teacher.id,
        )
        LiveActivity.objects.filter(pk=activity.pk).update(current_revision_id=run_revision.id)
        participant = Participant.objects.create(
            session_id=session.id,
            user_id=learner.id,
            display_name="Historical learner",
        )
        submission = Submission.objects.create(
            activity_id=activity.id,
            participant_id=participant.id,
            answer={"text": "kept"},
            attempt=1,
        )
        submission_revision = SubmissionRevision.objects.create(
            submission_id=submission.id,
            revision=1,
            answer={"text": "kept"},
            activity_revision_id=run_revision.id,
        )
        Submission.objects.filter(pk=submission.pk).update(current_revision_id=submission_revision.id)
        preserved_ids = {
            "definition": definition.id,
            "revision": source_revision.id,
            "flow": flow.id,
            "session": session.id,
            "activity": activity.id,
            "run_revision": run_revision.id,
            "submission": submission.id,
            "submission_revision": submission_revision.id,
        }

        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        migrated_definition = apps.get_model("liveclassroom", "ActivityDefinition").objects.get(
            pk=preserved_ids["definition"]
        )
        migrated_revision = apps.get_model("liveclassroom", "ActivityDefinitionRevision").objects.get(
            pk=preserved_ids["revision"]
        )
        migrated_snapshot = apps.get_model("liveclassroom", "ActivityRunRevision").objects.get(
            pk=preserved_ids["run_revision"]
        )
        assert migrated_definition.metadata == {"topic": "history"}
        assert migrated_revision.payload == {"prompt": "Before migration"}
        assert migrated_snapshot.definition_snapshot == {"prompt": "Before migration"}

        migrated_definition.definition = {"prompt": "Edited source after migration"}
        migrated_definition.save(update_fields=["definition"])
        assert (
            apps.get_model("liveclassroom", "ActivityRunRevision")
            .objects.get(pk=preserved_ids["run_revision"])
            .definition_snapshot
            == {"prompt": "Before migration"}
        )

        Deck = apps.get_model("liveclassroom", "Deck")
        DeckSlide = apps.get_model("liveclassroom", "DeckSlide")
        deck = Deck.objects.create(owner_id=teacher.id, title="Retained deck")
        DeckSlide.objects.create(deck_id=deck.id, position=1, markdown="# Retained")
        AssessmentRun = apps.get_model("liveclassroom", "AssessmentRun")
        run = AssessmentRun.objects.create(
            owner_id=teacher.id,
            source_version=1,
            audience="authenticated_link",
            title="Retained assessment run",
            manifest={"items": [{"key": "item-1", "prompt": "Retained"}]},
        )
        Attempt = apps.get_model("liveclassroom", "AssessmentAttempt")
        attempt = Attempt.objects.create(run_id=run.id, user_id=learner.id, attempt_number=1)
        AttemptItem = apps.get_model("liveclassroom", "AssessmentAttemptItem")
        item = AttemptItem.objects.create(
            attempt_id=attempt.id,
            position=1,
            points="2",
            manifest={"key": "item-1", "type_key": "liveclassroom.short_text"},
        )
        AnswerRevision = apps.get_model("liveclassroom", "AnswerRevision")
        answer = AnswerRevision.objects.create(
            item_id=item.id,
            version=1,
            answer={"text": "retained"},
            request_id=uuid4(),
            request_hash="a" * 64,
            actor_id=learner.id,
        )
        AttemptGrade = apps.get_model("liveclassroom", "AssessmentAttemptGrade")
        AttemptGrade.objects.create(
            attempt_id=attempt.id,
            status="graded",
            possible_points="2",
            awarded_points="2",
            graded_count=1,
        )
        ItemGrade = apps.get_model("liveclassroom", "AssessmentItemGrade")
        ItemGrade.objects.create(
            item_id=item.id,
            status="graded",
            normalized_score="1",
            possible_points="2",
            awarded_points="2",
            retained_answer={"text": "retained"},
        )
        Decision = apps.get_model("liveclassroom", "AssessmentGradeDecision")
        decision = Decision.objects.create(
            attempt_id=attempt.id,
            item_id=item.id,
            status="graded",
            normalized_score="1",
            possible_points="2",
            awarded_points="2",
            retained_answer={"text": "retained"},
            actor_id=teacher.id,
            reason="history acceptance",
        )
        Share = apps.get_model("liveclassroom", "ContentShare")
        share = Share.objects.create(
            owner_id=teacher.id,
            recipient_id=learner.id,
            kind="deck",
            resource_id=deck.id,
            source_fingerprint="b" * 64,
        )
        share.revoked_at = datetime.now(UTC)
        share.save(update_fields=["revoked_at"])

        assert apps.get_model("liveclassroom", "DeckSlide").objects.get(deck_id=deck.id).markdown == "# Retained"
        assert (
            apps.get_model("liveclassroom", "AnswerRevision").objects.get(pk=answer.id).answer
            == {"text": "retained"}
        )
        assert (
            apps.get_model("liveclassroom", "AssessmentGradeDecision").objects.get(pk=decision.id).awarded_points
            == 2
        )
        assert apps.get_model("liveclassroom", "ContentShare").objects.get(pk=share.id).revoked_at is not None
    finally:
        MigrationExecutor(connection).migrate(current)


@pytest.mark.django_db(transaction=True)
def test_postgres_acceptance_requires_task_named_disposable_database():
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL for cross-connection acceptance")
    database_name = str(connection.settings_dict.get("NAME", ""))
    if "task51" not in database_name.casefold():
        pytest.skip("requires LIVECLASSROOM_POSTGRES_TEST_NAME containing task51")
    assert connection.vendor == "postgresql"
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_setting('server_version')")
        current_database, server_version = cursor.fetchone()
    assert "task51" in str(current_database).casefold()
    assert server_version
