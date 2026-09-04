from django.db import migrations, models
import django.db.models.deletion


def _question_payload(question):
    data = question.data if isinstance(question.data, dict) else {}
    return {
        "prompt": question.stem_markdown,
        "stem_markdown": question.stem_markdown,
        "options": data.get("options", data.get("choices", [])),
        "answer": question.answer,
        "explanation": question.explanation_markdown,
    }


def _legacy_owner_id(flow, sessions):
    if flow.created_by_id:
        return flow.created_by_id
    if flow.course_id:
        course_owner = flow.course.created_by_id
        if course_owner:
            return course_owner
    return sessions.filter(flow_id=flow.id).order_by("id").values_list("teacher_id", flat=True).first()


def migrate_legacy_content(apps, schema_editor):
    ActivityDefinition = apps.get_model("liveclassroom", "ActivityDefinition")
    ActivityDefinitionRevision = apps.get_model("liveclassroom", "ActivityDefinitionRevision")
    ActivityRunRevision = apps.get_model("liveclassroom", "ActivityRunRevision")
    FlowItem = apps.get_model("liveclassroom", "FlowItem")
    FlowStep = apps.get_model("liveclassroom", "FlowStep")
    LiveActivity = apps.get_model("liveclassroom", "LiveActivity")
    LiveSession = apps.get_model("liveclassroom", "LiveSession")
    SessionChannelState = apps.get_model("liveclassroom", "SessionChannelState")
    Submission = apps.get_model("liveclassroom", "Submission")
    SubmissionRevision = apps.get_model("liveclassroom", "SubmissionRevision")

    step_by_legacy_item = {}
    for item in FlowItem.objects.select_related("flow", "flow__course", "question", "activity_definition").order_by(
        "flow_id", "position", "id"
    ):
        step = FlowStep.objects.filter(flow_id=item.flow_id, position=item.position).first()
        if step is None:
            step = FlowStep.objects.create(
                flow_id=item.flow_id,
                position=item.position,
                activity_definition_id=item.activity_definition_id,
                kind=item.kind,
                title=item.title,
                content=item.content,
                legacy_item_id=item.id,
            )
        else:
            updates = {}
            if not step.legacy_item_id:
                updates["legacy_item_id"] = item.id
            if not step.activity_definition_id and item.activity_definition_id:
                updates["activity_definition_id"] = item.activity_definition_id
            if updates:
                FlowStep.objects.filter(pk=step.pk).update(**updates)
                for key, value in updates.items():
                    setattr(step, key, value)

        if not step.activity_definition_id and item.question_id:
            owner_id = _legacy_owner_id(item.flow, LiveSession.objects)
            if owner_id:
                type_key = f"liveclassroom.{item.question.question_type}"
                definition = ActivityDefinition.objects.create(
                    owner_id=owner_id,
                    course_id=item.flow.course_id,
                    type_key=type_key,
                    title=item.title or item.question.stem_markdown[:200] or "Legacy activity",
                    definition=_question_payload(item.question),
                    status="ready",
                )
                revision = ActivityDefinitionRevision.objects.create(
                    definition_id=definition.id,
                    revision=1,
                    schema_version=definition.schema_version,
                    payload=definition.definition,
                    changed_by_id=owner_id,
                    change_note="Migrated from legacy question.",
                )
                ActivityDefinition.objects.filter(pk=definition.pk).update(current_revision_id=revision.id)
                FlowStep.objects.filter(pk=step.pk).update(activity_definition_id=definition.id)
                step.activity_definition_id = definition.id
        step_by_legacy_item[item.id] = step

    for session in LiveSession.objects.exclude(current_item_id=None):
        step = step_by_legacy_item.get(session.current_item_id)
        if step is not None and not session.current_step_id:
            LiveSession.objects.filter(pk=session.pk).update(current_step_id=step.id)

    run_revision_by_activity = {}
    for activity in LiveActivity.objects.select_related("source_item").order_by("id"):
        step = step_by_legacy_item.get(activity.source_item_id)
        if step is not None and not activity.source_step_id:
            LiveActivity.objects.filter(pk=activity.pk).update(source_step_id=step.id)
        revision = ActivityRunRevision.objects.filter(activity_id=activity.id).order_by("-revision").first()
        if revision is None:
            source_revision_id = None
            if step is not None and step.activity_definition_id:
                source_revision_id = ActivityDefinition.objects.filter(pk=step.activity_definition_id).values_list(
                    "current_revision_id", flat=True
                ).first()
            revision = ActivityRunRevision.objects.create(
                activity_id=activity.id,
                revision=1,
                definition_snapshot=activity.definition_snapshot,
                source_revision_id=source_revision_id,
            )
        if not activity.current_revision_id:
            LiveActivity.objects.filter(pk=activity.pk).update(current_revision_id=revision.id)
        run_revision_by_activity[activity.id] = revision.id

    for submission in Submission.objects.order_by("id"):
        revision = SubmissionRevision.objects.filter(submission_id=submission.id).order_by("-revision").first()
        if revision is None:
            revision = SubmissionRevision.objects.create(
                submission_id=submission.id,
                revision=1,
                activity_revision_id=run_revision_by_activity.get(submission.activity_id),
                answer=submission.answer,
                score=submission.score,
                is_correct=submission.is_correct,
                response_ms=submission.response_ms,
            )
        if not submission.current_revision_id:
            Submission.objects.filter(pk=submission.pk).update(current_revision_id=revision.id)

    for session in LiveSession.objects.order_by("id"):
        for channel in ("display", "participants"):
            SessionChannelState.objects.get_or_create(session_id=session.id, channel=channel)


class Migration(migrations.Migration):
    dependencies = [("liveclassroom", "0009_authoringmessage_authoringattachment_authoringthread_and_more")]

    operations = [
        migrations.AddField(
            model_name="flowstep",
            name="legacy_item",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="canonical_step",
                to="liveclassroom.flowitem",
            ),
        ),
        migrations.AddField(
            model_name="livesession",
            name="current_step",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="current_in_sessions",
                to="liveclassroom.flowstep",
            ),
        ),
        migrations.AddField(
            model_name="liveactivity",
            name="source_step",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="live_activities",
                to="liveclassroom.flowstep",
            ),
        ),
        migrations.RunPython(migrate_legacy_content, migrations.RunPython.noop),
    ]
