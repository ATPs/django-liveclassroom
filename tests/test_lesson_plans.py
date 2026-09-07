import pytest
from django.contrib.auth import get_user_model

from liveclassroom.models import (
    Course,
    FlowShare,
    FlowStep,
    LiveActivity,
    Submission,
)
from liveclassroom.services.classroom import (
    ClassroomError,
    create_activity_definition,
    join_guest,
    post_message,
    revise_activity_definition,
    start_session,
    submit_answer,
)
from liveclassroom.services.flows import add_flow_step, create_flow, remove_flow_step, reorder_flow_steps, update_flow
from liveclassroom.services.plan_changes import apply_changes, compare_changes
from liveclassroom.services.plans import (
    add_plan_step,
    copy_lesson,
    create_session,
    edit_plan_step,
    launch_plan_step,
    reorder_plan,
    save_lesson,
)


@pytest.fixture
def teacher(db):
    return get_user_model().objects.create_user(username="lesson-plan-teacher")


@pytest.fixture
def other_teacher(db):
    return get_user_model().objects.create_user(username="lesson-plan-other")


def short_text_snapshot(title, prompt):
    return {
        "schema_version": 1,
        "type_key": "liveclassroom.short_text",
        "kind": "short_text",
        "title": title,
        "content": {"prompt": prompt},
    }


def make_flow(teacher, prompts=("First question", "Second question")):
    flow = create_flow(title="Reusable lesson", creator=teacher)
    definitions = []
    steps = []
    for position, prompt in enumerate(prompts, 1):
        definition = create_activity_definition(
            owner=teacher,
            title=f"Question {position}",
            type_key="liveclassroom.short_text",
            definition={"prompt": prompt},
        )
        definitions.append(definition)
        steps.append(add_flow_step(flow=flow, actor=teacher, activity_definition=definition))
    return flow, definitions, steps


@pytest.mark.django_db
def test_prepared_sessions_keep_independent_snapshots_when_source_changes(teacher):
    flow, definitions, _ = make_flow(teacher, ("Before",))
    first = create_session(owner=teacher, title="First class", flow=flow)
    second = create_session(owner=teacher, title="Second class", flow=flow)
    old_snapshot = first.plan_steps.get().snapshot

    revise_activity_definition(
        activity=definitions[0],
        definition={"prompt": "After"},
        actor=teacher,
    )

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.source_snapshot_id != second.source_snapshot_id
    assert first.plan_steps.get().snapshot == old_snapshot
    assert second.plan_steps.get().snapshot == old_snapshot

    later = create_session(owner=teacher, title="Later class", flow=flow)
    assert later.plan_steps.get().snapshot["content"] == {"prompt": "After"}


@pytest.mark.django_db
def test_save_and_reuse_preserve_unlaunched_steps_without_classroom_data(teacher):
    _flow, _, _ = make_flow(teacher)
    session = create_session(owner=teacher, title="Source class", flow=_flow)
    start_session(session=session, actor=teacher)
    launched = launch_plan_step(session=session, step=session.plan_steps.get(position=1), actor=teacher)
    participant = join_guest(session=session, display_name="Ada", guest_id="source-guest")
    submit_answer(activity=launched, participant=participant, answer={"text": "Answer"})
    session.chat_enabled = True
    session.save(update_fields=["chat_enabled"])
    post_message(session=session, participant=participant, body="Keep this in source only")

    saved = save_lesson(session=session, actor=teacher, title="Saved lesson")
    reused = create_session(owner=teacher, title="Reused class", source=session)

    assert saved.steps.count() == 2
    assert [step.activity_definition.definition for step in saved.steps.order_by("position")] == [
        {"prompt": "First question"},
        {"prompt": "Second question"},
    ]
    assert reused.plan_steps.filter(removed=False).count() == 2
    assert reused.plan_steps.get(position=2).snapshot["content"] == {"prompt": "Second question"}
    assert reused.activities.count() == 0
    assert reused.participants.count() == 0
    assert reused.messages.count() == 0
    assert reused.chat_enabled is False
    assert reused.channel_states.filter(current_activity__isnull=False).count() == 0


@pytest.mark.django_db
def test_copy_lesson_owns_independent_activity_definitions(teacher):
    flow, definitions, _ = make_flow(teacher, ("Original",))
    copied = copy_lesson(flow=flow, actor=teacher, title="Copied lesson")
    copied_definition = copied.steps.get().activity_definition

    assert copied_definition.pk != definitions[0].pk
    revise_activity_definition(
        activity=definitions[0],
        definition={"prompt": "Edited original"},
        actor=teacher,
    )

    copied_definition.refresh_from_db()
    assert copied_definition.definition == {"prompt": "Original"}


@pytest.mark.django_db
def test_personal_flow_can_be_used_for_two_courses(teacher):
    course_one = Course.objects.create(title="Course One", slug="course-one", created_by=teacher)
    course_two = Course.objects.create(title="Course Two", slug="course-two", created_by=teacher)
    flow, _, _ = make_flow(teacher, ("Shared prompt",))

    first = create_session(owner=teacher, title="Course one session", course=course_one, flow=flow)
    second = create_session(owner=teacher, title="Course two session", course=course_two, flow=flow)

    assert flow.course_id is None
    assert (first.course_id, second.course_id) == (course_one.id, course_two.id)
    assert first.flow_id == second.flow_id == flow.id
    assert first.plan_steps.get().snapshot == second.plan_steps.get().snapshot


@pytest.mark.django_db
def test_share_allows_use_and_copy_but_not_edit_and_revocation_preserves_existing_session(
    teacher, other_teacher
):
    flow, _, _ = make_flow(teacher, ("Shared prompt",))
    FlowShare.objects.create(flow=flow, user=other_teacher)

    existing = create_session(owner=other_teacher, title="Shared session", flow=flow)
    copied = copy_lesson(flow=flow, actor=other_teacher, title="Personal copy")
    assert copied.created_by_id == other_teacher.id
    assert copied.steps.get().activity_definition.owner_id == other_teacher.id

    with pytest.raises(ClassroomError, match="edit"):
        update_flow(flow=flow, actor=other_teacher, title="Unauthorized edit")

    FlowShare.objects.filter(flow=flow, user=other_teacher).delete()
    with pytest.raises(ClassroomError, match="use this lesson"):
        create_session(owner=other_teacher, title="After revoke", flow=flow)
    with pytest.raises(ClassroomError, match="use this lesson"):
        copy_lesson(flow=flow, actor=other_teacher, title="After revoke copy")

    start_session(session=existing, actor=other_teacher)
    activity = launch_plan_step(session=existing, step=existing.plan_steps.get(), actor=other_teacher)
    assert activity.plan_step_id == existing.plan_steps.get().id


@pytest.mark.django_db
def test_selective_saveback_updates_only_selected_lesson_step(teacher):
    flow, definitions, steps = make_flow(teacher)
    session = create_session(owner=teacher, title="Editable class", flow=flow)
    historical = LiveActivity.objects.create(
        session=session,
        sequence=1,
        kind="short_text",
        source_step=steps[0],
        definition_snapshot=steps[0].activity_definition.definition,
    )
    second = session.plan_steps.get(key=steps[1].key)
    local = short_text_snapshot("Question 2", "Classroom-only revision")
    edit_plan_step(session=session, step=second, actor=teacher, snapshot=local)

    comparison = compare_changes(session=session, actor=teacher, direction="to_lesson")
    assert [change["key"] for change in comparison["changes"]] == [str(second.key)]
    apply_changes(
        session=session,
        actor=teacher,
        direction="to_lesson",
        token=comparison["token"],
        keys=[str(second.key)],
    )

    first_source = flow.steps.get(key=steps[0].key).activity_definition
    second_source = flow.steps.get(key=steps[1].key).activity_definition
    first_source.refresh_from_db()
    second_source.refresh_from_db()
    historical.refresh_from_db()
    assert first_source.pk == definitions[0].pk
    assert flow.steps.get(key=steps[0].key).pk == steps[0].pk
    assert historical.source_step_id == steps[0].pk
    assert first_source.definition == {"prompt": "First question"}
    assert second_source.definition == {"prompt": "Classroom-only revision"}


@pytest.mark.django_db
def test_stale_comparison_token_rejects_edit_between_compare_and_apply(teacher):
    flow, _, steps = make_flow(teacher)
    session = create_session(owner=teacher, title="Conflict class", flow=flow)
    second = session.plan_steps.get(key=steps[1].key)
    edit_plan_step(
        session=session,
        step=second,
        actor=teacher,
        snapshot=short_text_snapshot("Question 2", "First local edit"),
    )
    comparison = compare_changes(session=session, actor=teacher, direction="to_lesson")

    edit_plan_step(
        session=session,
        step=second,
        actor=teacher,
        snapshot=short_text_snapshot("Question 2", "Second local edit"),
    )
    with pytest.raises(ClassroomError, match="refresh and compare again"):
        apply_changes(
            session=session,
            actor=teacher,
            direction="to_lesson",
            token=comparison["token"],
            keys=[str(second.key)],
        )

    assert flow.steps.get(key=steps[1].key).activity_definition.definition == {"prompt": "Second question"}


@pytest.mark.django_db
def test_pull_skips_launched_steps_and_keeps_old_submissions(teacher):
    _flow, definitions, steps = make_flow(teacher)
    session = create_session(owner=teacher, title="Pull class", flow=_flow)
    start_session(session=session, actor=teacher)
    first_activity = launch_plan_step(session=session, step=session.plan_steps.get(position=1), actor=teacher)
    participant = join_guest(session=session, display_name="Ada", guest_id="pull-guest")
    submission = submit_answer(activity=first_activity, participant=participant, answer={"text": "Old answer"})
    first_step = session.plan_steps.get(key=steps[0].key)
    second_step = session.plan_steps.get(key=steps[1].key)

    revise_activity_definition(activity=definitions[0], definition={"prompt": "New first"}, actor=teacher)
    revise_activity_definition(activity=definitions[1], definition={"prompt": "New second"}, actor=teacher)
    comparison = compare_changes(session=session, actor=teacher, direction="to_session")

    assert [change["key"] for change in comparison["changes"]] == [str(second_step.key)]
    apply_changes(
        session=session,
        actor=teacher,
        direction="to_session",
        token=comparison["token"],
        keys=[str(second_step.key)],
    )

    first_step.refresh_from_db()
    second_step.refresh_from_db()
    first_activity.refresh_from_db()
    submission.refresh_from_db()
    assert first_step.snapshot["content"] == {"prompt": "First question"}
    assert second_step.snapshot["content"] == {"prompt": "New second"}
    assert first_activity.definition_snapshot["content"] == {"prompt": "First question"}
    assert submission.answer == {"text": "Old answer"}
    assert submission.is_stale is False
    assert submission.revisions.count() == 1
    assert Submission.objects.filter(pk=submission.pk).count() == 1


@pytest.mark.django_db
def test_pull_does_not_offer_or_accept_order_changes_after_a_step_launches(teacher):
    flow, _, steps = make_flow(teacher)
    session = create_session(owner=teacher, title="Order class", flow=flow)
    start_session(session=session, actor=teacher)
    launch_plan_step(session=session, step=session.plan_steps.get(key=steps[0].key), actor=teacher)
    reorder_flow_steps(flow=flow, actor=teacher, step_ids=[steps[1].id, steps[0].id])

    comparison = compare_changes(session=session, actor=teacher, direction="to_session")

    assert comparison["changes"] == []
    with pytest.raises(ClassroomError, match="Select changes from the current comparison"):
        apply_changes(
            session=session,
            actor=teacher,
            direction="to_session",
            token=comparison["token"],
            keys=["__order__"],
        )


@pytest.mark.django_db
def test_saveback_keeps_original_step_pks_with_many_reordered_local_steps(teacher):
    flow, _definitions, source_steps = make_flow(teacher)
    session = create_session(owner=teacher, title="Many local steps", flow=flow)
    original_pks = [step.pk for step in source_steps]
    local_steps = []
    for position in range(1, 7):
        session.refresh_from_db()
        local_steps.append(
            add_plan_step(
                session=session,
                actor=teacher,
                snapshot=short_text_snapshot(f"Local question {position}", f"Local prompt {position}"),
                expected_version=session.plan_version,
            )
        )

    session.refresh_from_db()
    original_second = session.plan_steps.get(key=source_steps[1].key)
    edit_plan_step(
        session=session,
        step=original_second,
        actor=teacher,
        snapshot=short_text_snapshot("Changed original question 2", "Changed original prompt 2"),
        expected_version=session.plan_version,
    )
    session.refresh_from_db()
    desired_keys = [str(step.key) for step in local_steps] + [str(step.key) for step in source_steps]
    reorder_plan(session=session, actor=teacher, keys=desired_keys, expected_version=session.plan_version)
    revise_activity_definition(
        activity=_definitions[1], definition={"prompt": "Concurrent original prompt"}, actor=teacher
    )

    comparison = compare_changes(session=session, actor=teacher, direction="to_lesson")
    changed_keys = [change["key"] for change in comparison["changes"]]
    assert "__order__" in changed_keys
    assert all(str(step.key) in changed_keys for step in local_steps)
    assert str(source_steps[1].key) in changed_keys
    conflicts = [change["key"] for change in comparison["changes"] if change["conflict"]]
    assert conflicts == [str(source_steps[1].key)]

    apply_changes(
        session=session,
        actor=teacher,
        direction="to_lesson",
        token=comparison["token"],
        keys=changed_keys,
        confirmed_conflicts=conflicts,
    )

    session.refresh_from_db()
    plan_rows = list(session.plan_steps.filter(removed=False).order_by("position"))
    source_rows = list(
        FlowStep.objects.filter(flow=flow).select_related("activity_definition").order_by("position")
    )
    source_by_key = {row.key: row for row in source_rows}
    assert [source_by_key[step.key].pk for step in source_steps] == original_pks
    assert [str(row.key) for row in source_rows] == [str(row.key) for row in plan_rows]
    assert [(str(row.key), row.activity_definition.title) for row in source_rows] == [
        (str(row.key), row.snapshot["title"]) for row in plan_rows
    ]
    assert [row.activity_definition.definition for row in source_rows] == [
        row.snapshot["content"] for row in plan_rows
    ]


@pytest.mark.django_db
def test_remove_original_flow_step_reindexes_remaining_source(teacher):
    flow, _definitions, steps = make_flow(teacher)

    remove_flow_step(flow=flow, actor=teacher, step_id=steps[0].pk)

    remaining = list(flow.steps.order_by("position"))
    assert [(step.pk, step.position) for step in remaining] == [(steps[1].pk, 1)]
