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
def test_populated_intermediate_history_retains_deck_attempt_grade_and_release_rows():
    """Exercise real rows while each additive history feature is the leaf.

    The older migration checks mostly prove that empty tables can be upgraded.
    This fixture deliberately advances through the deck snapshot, answer
    revision, and result-release leaves with populated rows before checking
    the current schema.  The final source edits/deletes also prove that the
    retained rows do not follow mutable authoring objects.
    """

    deck_leaf = _target("0009_deck_snapshots")
    answer_leaf = _target("0013_attempt_answer_revisions")
    release_leaf = _target("0017_assessmentresultrelease")
    current = _target(CURRENT)
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(deck_leaf)
        deck_apps = executor.loader.project_state(deck_leaf).apps
        User = deck_apps.get_model("auth", "User")
        teacher = User.objects.create(username=f"history-deck-{uuid4().hex[:8]}")
        learner = User.objects.create(username=f"history-learner-{uuid4().hex[:8]}")
        manual_release_policy = {
            dimension: "manual"
            for dimension in ("scores", "answers", "explanations", "comments")
        }
        Deck = deck_apps.get_model("liveclassroom", "Deck")
        DeckSlide = deck_apps.get_model("liveclassroom", "DeckSlide")
        DeckSnapshot = deck_apps.get_model("liveclassroom", "DeckSnapshot")
        deck = Deck.objects.create(owner_id=teacher.id, title="Historical deck", theme="light", version=1)
        slide = DeckSlide.objects.create(
            deck_id=deck.id,
            position=1,
            markdown="# Before upgrade",
            notes="Private pre-upgrade note",
        )
        snapshot = DeckSnapshot.objects.create(
            source_deck_id=deck.id,
            source_version=deck.version,
            title=deck.title,
            theme=deck.theme,
            public_manifest=[
                {"key": str(slide.key), "position": 1, "markdown": slide.markdown, "asset_ids": []}
            ],
            private_notes={str(slide.key): slide.notes},
            fingerprint="d" * 64,
        )
        deck_id, snapshot_id = deck.id, snapshot.id

        # Refresh migration-recorder state after every intermediate leaf.
        # Reusing the executor initialized at the current leaf makes SQLite
        # attempt an invalid reverse plan for unrelated later tables.
        executor = MigrationExecutor(connection)
        executor.migrate(answer_leaf)
        answer_apps = executor.loader.project_state(answer_leaf).apps
        AssessmentDefinition = answer_apps.get_model("liveclassroom", "AssessmentDefinition")
        source = AssessmentDefinition.objects.create(
            owner_id=teacher.id,
            title="Historical assessment source",
            settings={"release_policy": manual_release_policy},
        )
        AssessmentRun = answer_apps.get_model("liveclassroom", "AssessmentRun")
        run = AssessmentRun.objects.create(
            owner_id=teacher.id,
            source_assessment_id=source.id,
            source_version=1,
            audience="authenticated_link",
            title="Historical assessment run",
            manifest={
                "settings": {"release_policy": manual_release_policy},
                "items": [
                    {
                        "key": "retained-item",
                        "type_key": "liveclassroom.single_choice",
                        "payload": {
                            "prompt": "Retained prompt",
                            "options": [{"id": "A", "text": "A"}],
                            "answer": "A",
                        },
                    }
                ],
            },
        )
        Attempt = answer_apps.get_model("liveclassroom", "AssessmentAttempt")
        attempt = Attempt.objects.create(
            run_id=run.id,
            user_id=learner.id,
            attempt_number=1,
            status="submitted",
        )
        AttemptItem = answer_apps.get_model("liveclassroom", "AssessmentAttemptItem")
        item = AttemptItem.objects.create(
            attempt_id=attempt.id,
            position=1,
            points="2",
            manifest={
                "key": "retained-item",
                "type_key": "liveclassroom.single_choice",
                "payload": {"prompt": "Retained prompt", "answer": "A"},
            },
        )
        AnswerRevision = answer_apps.get_model("liveclassroom", "AnswerRevision")
        answer_v1 = AnswerRevision.objects.create(
            item_id=item.id,
            version=1,
            answer={"choice": "B"},
            request_id=uuid4(),
            request_hash="a" * 64,
            actor_id=learner.id,
        )
        answer_v2 = AnswerRevision.objects.create(
            item_id=item.id,
            version=2,
            answer={"choice": "A"},
            request_id=uuid4(),
            request_hash="b" * 64,
            actor_id=learner.id,
        )
        run_id, attempt_id, item_id = run.id, attempt.id, item.id
        answer_ids = (answer_v1.id, answer_v2.id)

        executor = MigrationExecutor(connection)
        executor.migrate(release_leaf)
        release_apps = executor.loader.project_state(release_leaf).apps
        AttemptGrade = release_apps.get_model("liveclassroom", "AssessmentAttemptGrade")
        AttemptGrade.objects.create(
            attempt_id=attempt_id,
            status="graded",
            possible_points="2",
            awarded_points="2",
            graded_count=1,
        )
        ItemGrade = release_apps.get_model("liveclassroom", "AssessmentItemGrade")
        ItemGrade.objects.create(
            item_id=item_id,
            status="graded",
            normalized_score="1",
            possible_points="2",
            awarded_points="2",
            retained_answer={"choice": "A"},
        )
        Decision = release_apps.get_model("liveclassroom", "AssessmentGradeDecision")
        for awarded, reason in (("0", "initial decision"), ("2", "corrected decision")):
            Decision.objects.create(
                attempt_id=attempt_id,
                item_id=item_id,
                status="graded",
                normalized_score="1" if awarded == "2" else "0",
                possible_points="2",
                awarded_points=awarded,
                retained_answer={"choice": "A"},
                actor_id=teacher.id,
                reason=reason,
            )
        Release = release_apps.get_model("liveclassroom", "AssessmentResultRelease")
        Release.objects.create(
            run_id=run_id,
            attempt_id=attempt_id,
            dimension="scores",
            released=True,
            actor_id=teacher.id,
            released_at=datetime.now(UTC),
        )
        Release.objects.create(
            run_id=run_id,
            dimension="answers",
            released=True,
            actor_id=teacher.id,
            released_at=datetime.now(UTC),
        )

        executor = MigrationExecutor(connection)
        executor.migrate(current)
        from django.contrib.auth import get_user_model

        from liveclassroom.models import (
            AnswerRevision as CurrentAnswerRevision,
        )
        from liveclassroom.models import (
            AssessmentAttempt,
            AssessmentAttemptGrade,
            AssessmentGradeDecision,
            AssessmentItemGrade,
            AssessmentResultRelease,
            AssessmentRun,
        )
        from liveclassroom.models import (
            Deck as CurrentDeck,
        )
        from liveclassroom.models import (
            DeckSnapshot as CurrentDeckSnapshot,
        )
        from liveclassroom.services.assessment_review import review_own_attempt
        from liveclassroom.services.decks import copy_deck, replace_deck_slides

        CurrentUser = get_user_model()
        current_teacher = CurrentUser.objects.get(pk=teacher.id)
        current_learner = CurrentUser.objects.get(pk=learner.id)
        migrated_snapshot = CurrentDeckSnapshot.objects.get(pk=snapshot_id)
        assert migrated_snapshot.public_manifest[0]["markdown"] == "# Before upgrade"
        assert migrated_snapshot.private_notes[str(slide.key)] == "Private pre-upgrade note"
        assert list(
            CurrentAnswerRevision.objects.filter(item_id=item_id)
            .order_by("version")
            .values_list("pk", "version", "answer")
        ) == [
            (answer_ids[0], 1, {"choice": "B"}),
            (answer_ids[1], 2, {"choice": "A"}),
        ]
        assert list(
            AssessmentGradeDecision.objects.filter(attempt_id=attempt_id)
            .order_by("created_at", "id")
            .values_list("awarded_points", "reason")
        ) == [(0, "initial decision"), (2, "corrected decision")]
        assert AssessmentAttemptGrade.objects.get(attempt_id=attempt_id).awarded_points == 2
        assert AssessmentItemGrade.objects.get(item_id=item_id).retained_answer == {"choice": "A"}
        assert set(
            AssessmentResultRelease.objects.filter(run_id=run_id).values_list("attempt_id", "dimension", "released")
        ) == {(attempt_id, "scores", True), (None, "answers", True)}

        current_deck = CurrentDeck.objects.get(pk=deck_id)
        replace_deck_slides(
            actor=current_teacher,
            deck=current_deck,
            expected_version=1,
            slides=[{"markdown": "# Edited source after upgrade", "notes": "New note"}],
        )
        copied_deck = copy_deck(actor=current_teacher, deck=current_deck, title="Copied historical deck")
        assert copied_deck.slides.get().markdown == "# Edited source after upgrade"
        assert migrated_snapshot.public_manifest[0]["markdown"] == "# Before upgrade"
        current_deck.delete()
        migrated_snapshot.refresh_from_db()
        copied_deck.refresh_from_db()
        assert migrated_snapshot.source_deck_id is None
        assert copied_deck.slides.get().markdown == "# Edited source after upgrade"

        current_source = AssessmentRun.objects.get(pk=run_id).source_assessment
        current_source.title = "Edited source after upgrade"
        current_source.save(update_fields=["title"])
        retained_run = AssessmentRun.objects.get(pk=run_id)
        assert retained_run.manifest["items"][0]["payload"]["prompt"] == "Retained prompt"
        current_source.delete()
        retained_run.refresh_from_db()
        assert retained_run.source_assessment_id is None
        retained_attempt = AssessmentAttempt.objects.get(pk=attempt_id)
        assert retained_attempt.items.get(pk=item_id).answer_revisions.get(version=2).answer == {"choice": "A"}
        review = review_own_attempt(actor=current_learner, public_id=retained_attempt.public_id)
        assert review["items"][0]["saved_answer"] == {"choice": "A"}
        assert review["items"][0]["result"]["score"] == {
            "status": "graded",
            "normalized_score": "1.0000000000",
            "possible_points": "2.000000",
            "awarded_points": "2.00",
        }
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
