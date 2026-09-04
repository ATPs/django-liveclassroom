import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_legacy_flow_data_migrates_to_canonical_steps_and_revisions():
    old_target = ("liveclassroom", "0001_initial")
    current_target = ("liveclassroom", "0010_canonical_flow_steps")
    executor = MigrationExecutor(connection)
    executor.migrate([old_target])
    old_apps = executor.loader.project_state([old_target]).apps

    User = old_apps.get_model("auth", "User")
    Course = old_apps.get_model("liveclassroom", "Course")
    Flow = old_apps.get_model("liveclassroom", "Flow")
    FlowItem = old_apps.get_model("liveclassroom", "FlowItem")
    LiveActivity = old_apps.get_model("liveclassroom", "LiveActivity")
    LiveSession = old_apps.get_model("liveclassroom", "LiveSession")
    Participant = old_apps.get_model("liveclassroom", "Participant")
    Question = old_apps.get_model("liveclassroom", "Question")
    Submission = old_apps.get_model("liveclassroom", "Submission")

    teacher = User.objects.create(username="legacy-teacher")
    course = Course.objects.create(title="Legacy course", slug="legacy-course", created_by=teacher)
    flow = Flow.objects.create(course=course, title="Legacy flow", slug="legacy-flow")
    question = Question.objects.create(
        question_type="single_choice",
        stem_markdown="Legacy question",
        data={"options": [{"id": "A", "text": "One"}, {"id": "B", "text": "Two"}]},
        answer=["A"],
    )
    item = FlowItem.objects.create(flow=flow, position=1, kind="question", title="Legacy", question=question)
    session = LiveSession.objects.create(course=course, flow=flow, teacher=teacher, current_item=item)
    activity = LiveActivity.objects.create(
        session=session,
        sequence=1,
        kind="question",
        source_item=item,
        definition_snapshot={"kind": "question", "question": {"id": question.id}},
    )
    participant = Participant.objects.create(session=session, guest_id="legacy-guest", display_name="Ada")
    submission = Submission.objects.create(activity=activity, participant=participant, answer={"choice": "A"})

    try:
        executor = MigrationExecutor(connection)
        executor.migrate([current_target])
        apps = executor.loader.project_state([current_target]).apps
        ActivityDefinition = apps.get_model("liveclassroom", "ActivityDefinition")
        FlowStep = apps.get_model("liveclassroom", "FlowStep")
        LiveActivity = apps.get_model("liveclassroom", "LiveActivity")
        LiveSession = apps.get_model("liveclassroom", "LiveSession")
        SessionChannelState = apps.get_model("liveclassroom", "SessionChannelState")
        Submission = apps.get_model("liveclassroom", "Submission")

        step = FlowStep.objects.get(legacy_item_id=item.id)
        definition = ActivityDefinition.objects.get(pk=step.activity_definition_id)
        migrated_session = LiveSession.objects.get(pk=session.id)
        migrated_activity = LiveActivity.objects.get(pk=activity.id)
        migrated_submission = Submission.objects.get(pk=submission.id)

        assert step.position == 1
        assert definition.type_key == "liveclassroom.single_choice"
        assert definition.current_revision_id is not None
        assert migrated_session.current_step_id == step.id
        assert migrated_activity.source_step_id == step.id
        assert migrated_activity.current_revision_id is not None
        assert migrated_submission.current_revision_id is not None
        assert SessionChannelState.objects.filter(session_id=session.id).count() == 2
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
