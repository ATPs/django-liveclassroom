"""Upgrade databases that recorded the pre-cleanup initial schema.

``0001_initial`` was rebuilt after FlowItem and Question were retired. Existing
installations have already recorded the old initial migration, so this migration
converts any remaining authoring records before removing its unused tables and
columns. Fresh installations reach this migration with none of those structures.
"""

import json

from django.db import migrations


LEGACY_COLUMNS = {
    "liveclassroom_activitydefinition": ("legacy_question_id",),
    "liveclassroom_flowstep": ("legacy_item_id", "kind", "title", "content"),
    "liveclassroom_liveactivity": ("source_item_id",),
    "liveclassroom_livesession": ("current_item_id", "current_step_id", "mode"),
    "liveclassroom_participant": ("role",),
    "liveclassroom_sessionchannelstate": ("allow_review",),
}


def _columns(connection, table):
    with connection.cursor() as cursor:
        return {column.name for column in connection.introspection.get_table_description(cursor, table)}


def _rows(connection, table):
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {quote(table)}")
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def _as_dict(value):
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def _clean_text(value):
    return value.strip() if isinstance(value, str) else ""


def _options(value):
    if not isinstance(value, list):
        return []
    options = []
    seen = set()
    for index, option in enumerate(value):
        if isinstance(option, str):
            option = {"id": chr(ord("A") + index), "text": option}
        if not isinstance(option, dict):
            continue
        option_id = _clean_text(option.get("id"))
        text = _clean_text(option.get("text"))
        if option_id and text and option_id not in seen:
            options.append({"id": option_id, "text": text})
            seen.add(option_id)
    return options


def _legacy_payload(kind, title, content, question):
    content = _as_dict(content)
    question = _as_dict(question)
    if question:
        question_type = _clean_text(question.get("question_type"))
        if question_type not in {"single_choice", "multiple_choice", "true_false", "poll", "short_text"}:
            question_type = "short_text"
        source_data = _as_dict(question.get("data"))
        prompt = _clean_text(question.get("stem_markdown")) or title or "Response"
        payload = {"prompt": prompt}
        if question_type in {"single_choice", "multiple_choice", "poll"}:
            options = _options(source_data.get("options", source_data.get("choices")))
            if not options:
                question_type = "short_text"
            else:
                payload["options"] = options
                answer = question.get("answer")
                if isinstance(answer, (str, list)):
                    payload["answer"] = answer
                explanation = _clean_text(question.get("explanation_markdown"))
                if explanation:
                    payload["explanation"] = explanation
        if question_type == "true_false":
            answer = question.get("answer")
            if isinstance(answer, (str, list)):
                payload["answer"] = answer
        return f"liveclassroom.{question_type}", payload

    kind = _clean_text(kind)
    title = title or _clean_text(content.get("title"))
    if kind in {"question", "poll"}:
        options = _options(content.get("options", content.get("choices")))
        if options:
            payload = {"options": options}
            prompt = _clean_text(content.get("prompt")) or title
            if prompt:
                payload["prompt"] = prompt
            if isinstance(content.get("answer"), (str, list)):
                payload["answer"] = content["answer"]
            return "liveclassroom.poll" if kind == "poll" else "liveclassroom.single_choice", payload
        return "liveclassroom.short_text", {"prompt": title or "Response"}
    if kind == "timer":
        duration = content.get("duration_seconds", content.get("duration", 60))
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            duration = 60
        if duration <= 0:
            duration = 60
        payload = {"duration_seconds": int(duration) if duration.is_integer() else duration}
        label = _clean_text(content.get("label")) or title
        if label:
            payload["label"] = label
        return "liveclassroom.timer", payload
    if kind in {"image", "video", "url", "iframe"}:
        url = _clean_text(content.get("url")) or _clean_text(content.get("src"))
        if url:
            media_type = "iframe" if kind in {"url", "iframe"} else kind
            payload = {"url": url, "media_type": media_type}
            caption = _clean_text(content.get("caption")) or title
            if caption:
                payload["caption"] = caption
            return "liveclassroom.media", payload
    markdown = _clean_text(content.get("markdown")) or _clean_text(content.get("text")) or title
    return "liveclassroom.markdown", {"markdown": markdown or "Legacy content"}


def forward(apps, schema_editor):
    connection = schema_editor.connection
    tables = set(connection.introspection.table_names())
    flow_item_table = "liveclassroom_flowitem"
    question_table = "liveclassroom_question"

    ActivityDefinition = apps.get_model("liveclassroom", "ActivityDefinition")
    ActivityDefinitionRevision = apps.get_model("liveclassroom", "ActivityDefinitionRevision")
    Course = apps.get_model("liveclassroom", "Course")
    Flow = apps.get_model("liveclassroom", "Flow")
    FlowStep = apps.get_model("liveclassroom", "FlowStep")
    LiveActivity = apps.get_model("liveclassroom", "LiveActivity")
    LiveSession = apps.get_model("liveclassroom", "LiveSession")
    SessionChannelState = apps.get_model("liveclassroom", "SessionChannelState")
    Submission = apps.get_model("liveclassroom", "Submission")

    submission_table = Submission._meta.db_table
    if submission_table in tables and "performed_by_id" not in _columns(connection, submission_table):
        schema_editor.add_field(Submission, Submission._meta.get_field("performed_by"))

    def owner_for_flow(flow_id):
        flow = Flow.objects.filter(pk=flow_id).values("created_by_id", "course_id").first()
        if not flow:
            return None, None
        owner_id = flow["created_by_id"]
        course_id = flow["course_id"]
        if owner_id is None and course_id is not None:
            owner_id = Course.objects.filter(pk=course_id).values_list("created_by_id", flat=True).first()
        if owner_id is None:
            owner_id = LiveSession.objects.filter(flow_id=flow_id).values_list("teacher_id", flat=True).first()
        return owner_id, course_id

    def ensure_revision(definition):
        if definition.current_revision_id:
            return definition
        revision = ActivityDefinitionRevision.objects.filter(definition_id=definition.id).order_by("-revision", "-id").first()
        if revision is None:
            revision = ActivityDefinitionRevision.objects.create(
                definition_id=definition.id,
                revision=1,
                schema_version=definition.schema_version,
                payload=definition.definition,
                changed_by_id=definition.owner_id,
                change_note="Legacy authoring cleanup",
            )
        ActivityDefinition.objects.filter(pk=definition.id, current_revision__isnull=True).update(current_revision_id=revision.id)
        definition.current_revision_id = revision.id
        return definition

    def create_definition(flow_id, kind, title, content, question):
        owner_id, course_id = owner_for_flow(flow_id)
        if owner_id is None:
            return None
        type_key, payload = _legacy_payload(kind, title, content, question)
        definition = ActivityDefinition.objects.create(
            owner_id=owner_id,
            course_id=course_id,
            type_key=type_key,
            title=title or _clean_text(payload.get("prompt"))[:200] or "Legacy activity",
            definition=payload,
            status="draft",
        )
        return ensure_revision(definition)

    questions = {}
    if question_table in tables:
        questions = {row["id"]: row for row in _rows(connection, question_table)}

    step_table = FlowStep._meta.db_table
    step_rows = _rows(connection, step_table) if step_table in tables else []
    session_table = LiveSession._meta.db_table
    legacy_sessions = {row["id"]: row for row in _rows(connection, session_table)}
    activity_table = LiveActivity._meta.db_table
    activity_rows = _rows(connection, activity_table) if activity_table in tables else []
    steps_by_id = {step.id: step for step in FlowStep.objects.all()}
    steps_by_item = {row.get("legacy_item_id"): row for row in step_rows if row.get("legacy_item_id")}
    steps_by_position = {(row["flow_id"], row["position"]): row for row in step_rows}
    occupied_positions = {}
    for row in step_rows:
        occupied_positions.setdefault(row["flow_id"], set()).add(row["position"])

    def assign_step(item_row, definition):
        if definition is None:
            return
        target_row = steps_by_item.get(item_row.get("id")) or steps_by_position.get(
            (item_row["flow_id"], item_row["position"])
        )
        if target_row is not None:
            step = steps_by_id[target_row["id"]]
            if step.activity_definition_id is None:
                step.activity_definition_id = definition.id
                step.save(update_fields=["activity_definition"])
            return
        flow_id = item_row["flow_id"]
        position = item_row["position"]
        used = occupied_positions.setdefault(flow_id, set())
        if position in used:
            position = max(used, default=0) + 1
        step = FlowStep.objects.create(flow_id=flow_id, position=position, activity_definition_id=definition.id)
        steps_by_id[step.id] = step
        used.add(position)

    if flow_item_table in tables:
        for item in sorted(_rows(connection, flow_item_table), key=lambda row: (row["flow_id"], row["position"], row["id"])):
            existing = item.get("activity_definition_id")
            definition = ActivityDefinition.objects.filter(pk=existing).first() if existing else None
            if definition is not None:
                definition = ensure_revision(definition)
            else:
                definition = create_definition(
                    item["flow_id"], item.get("kind"), item.get("title", ""), item.get("content"), questions.get(item.get("question_id"))
                )
            assign_step(item, definition)

    for row in step_rows:
        step = steps_by_id[row["id"]]
        if step.activity_definition_id is not None:
            ensure_revision(step.activity_definition)
            continue
        legacy_item_id = row.get("legacy_item_id")
        if legacy_item_id and flow_item_table in tables:
            continue
        definition = create_definition(
            row["flow_id"], row.get("kind"), row.get("title", ""), row.get("content"), None
        )
        if definition is None:
            step.delete()
        else:
            step.activity_definition_id = definition.id
            step.save(update_fields=["activity_definition"])

    activities_by_id = {activity.id: activity for activity in LiveActivity.objects.all()}
    activities_by_session = {}
    for row in activity_rows:
        activities_by_session.setdefault(row["session_id"], []).append(row)
    for session in LiveSession.objects.all():
        legacy = legacy_sessions[session.id]
        current_step_id = legacy.get("current_step_id")
        current_item_id = legacy.get("current_item_id")
        candidates = activities_by_session.get(session.id, [])
        matching = [
            row
            for row in candidates
            if row.get("source_step_id") == current_step_id or row.get("source_item_id") == current_item_id
        ]
        selected = matching or candidates
        activity = activities_by_id.get(max(selected, key=lambda row: row["sequence"])["id"]) if selected else None
        for channel in ("display", "participants"):
            state, _ = SessionChannelState.objects.get_or_create(session_id=session.id, channel=channel)
            if state.current_activity_id or activity is None:
                continue
            state.current_activity_id = activity.id
            state.current_revision_id = activity.current_revision_id
            state.version = session.state_version
            state.save(update_fields=["current_activity", "current_revision", "version", "updated_at"])

    quote = connection.ops.quote_name
    for table, columns in LEGACY_COLUMNS.items():
        if table not in tables:
            continue
        existing = _columns(connection, table)
        for column in columns:
            if column in existing:
                schema_editor.execute(f"ALTER TABLE {quote(table)} DROP COLUMN {quote(column)}")

    for table in (flow_item_table, question_table):
        if table in tables:
            schema_editor.execute(f"DROP TABLE {quote(table)}")


class Migration(migrations.Migration):
    dependencies = [("liveclassroom", "0002_classroom_file_assets")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
