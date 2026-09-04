"""Regression tests for the Phase 0 security and correctness defects."""

import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse

from liveclassroom.models import (
    ActivityDefinition,
    Course,
    CourseMembership,
    Flow,
    FlowItem,
    LiveActivity,
    LiveSession,
    SessionChannelState,
)
from liveclassroom.registry import activity_registry
from liveclassroom.services.classroom import (
    ClassroomError,
    create_activity_definition,
    create_instant_session,
    end_session,
    join_guest,
    launch_item,
    post_message,
    publish_activity_to_channel,
    result_summary,
    set_activity_state,
    set_chat_enabled,
    start_session,
    submit_answer,
    update_channel_visibility,
)
from liveclassroom.services.flows import add_flow_step, create_flow


@pytest.fixture
def teacher(db):
    return get_user_model().objects.create_user(username="p0-teacher")


@pytest.fixture
def other_teacher(db):
    return get_user_model().objects.create_user(username="p0-other-teacher")


def post_json(client, url, payload=None):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json")


@pytest.mark.django_db
def test_add_flow_step_rejects_foreign_private_activity(teacher, other_teacher):
    flow = create_flow(title="Flow", creator=teacher)
    private = create_activity_definition(
        owner=other_teacher,
        title="Private prompt",
        type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "A", "text": "Only the owner may use this"}]},
    )

    with pytest.raises(ClassroomError, match="permission to use this activity"):
        add_flow_step(flow=flow, actor=teacher, activity_definition=private)

    assert flow.steps.count() == 0


@pytest.mark.django_db
def test_add_step_api_rejects_foreign_activity_definition(teacher, other_teacher):
    flow = create_flow(title="API Flow", creator=teacher)
    private = create_activity_definition(
        owner=other_teacher,
        title="Private prompt",
        type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "A", "text": "Secret"}]},
    )

    client = Client()
    client.force_login(teacher)
    response = post_json(
        client,
        reverse("liveclassroom:api-v1-flow-add-step", args=[flow.id]),
        {"activity_definition_id": private.id},
    )

    assert response.status_code == 403
    assert flow.steps.count() == 0


@pytest.mark.django_db
def test_course_teacher_can_launch_flow_they_did_not_create():
    owner = get_user_model().objects.create_user(username="p0-flow-owner")
    course_teacher = get_user_model().objects.create_user(username="p0-course-teacher")
    course = Course.objects.create(title="Shared Course", slug="p0-shared-course", created_by=owner)
    CourseMembership.objects.create(course=course, user=course_teacher, role=CourseMembership.Role.TEACHER)
    flow = Flow.objects.create(course=course, created_by=owner, title="Shared Flow", slug="shared-flow")
    item = FlowItem.objects.create(
        flow=flow,
        position=1,
        kind=FlowItem.Kind.POLL,
        content={"options": [{"id": "A", "text": "One"}, {"id": "B", "text": "Two"}]},
    )
    session = LiveSession.objects.create(course=course, flow=flow, teacher=course_teacher, title="Shared session")

    start_session(session=session, actor=course_teacher)
    activity = launch_item(session=session, item=item, actor=course_teacher)

    assert activity.session_id == session.id


@pytest.mark.django_db
def test_launch_markdown_step_does_not_crash(teacher):
    flow = create_flow(title="Markdown Flow", creator=teacher)
    step = add_flow_step(
        flow=flow,
        actor=teacher,
        kind="markdown",
        title="Lecture Notes",
        content={"markdown": "# Welcome to class"},
    )
    session = create_instant_session(owner=teacher, title="Markdown session")
    session.flow = flow
    session.save(update_fields=["flow"])
    start_session(session=session, actor=teacher)

    activity = launch_item(session=session, item=step, actor=teacher)

    assert activity.kind == "markdown"
    assert activity.definition_snapshot["kind"] == "markdown"


@pytest.mark.django_db
def test_end_session_disables_chat_and_rejects_new_posts(teacher):
    session = create_instant_session(owner=teacher, title="Ended chat")
    start_session(session=session, actor=teacher)
    set_chat_enabled(session=session, enabled=True, actor=teacher)
    participant = join_guest(session=session, display_name="Ada")

    end_session(session=session, actor=teacher)
    session.refresh_from_db()

    assert session.chat_enabled is False
    with pytest.raises(ClassroomError, match="has ended"):
        post_message(session=session, body="Too late", participant=participant)
    with pytest.raises(ClassroomError, match="cannot be enabled"):
        set_chat_enabled(session=session, enabled=True, actor=teacher)


@pytest.mark.django_db
def test_state_aggregate_redacts_raw_word_cloud_answers(teacher):
    session = create_instant_session(owner=teacher, title="Word cloud privacy")
    definition = create_activity_definition(
        owner=teacher,
        title="One word?",
        type_key="liveclassroom.word_cloud",
        definition={"prompt": "What comes to mind?", "stop_words": []},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    first = join_guest(session=session, display_name="Ada")
    second = join_guest(session=session, display_name="Grace")
    submit_answer(activity=activity, participant=first, answer={"text": "banana"})
    submit_answer(activity=activity, participant=second, answer={"text": "apple banana"})
    publish_activity_to_channel(session=session, activity=activity, channel="participants", actor=teacher)
    update_channel_visibility(session=session, channel="participants", actor=teacher, show_aggregate=True)

    student = Client()
    joined = post_json(student, reverse("liveclassroom:api-v1-join", args=[session.join_code]), {"display_name": "Eve"})
    assert joined.status_code == 201
    state = student.get(reverse("liveclassroom:api-v1-state", args=[session.id]), {"channel": "participants"}).json()

    aggregate = state["channels"]["participants"]["aggregate"]
    assert aggregate["submission_count"] == 2
    assert "banana" in aggregate["word_frequencies"]
    assert "raw_answers" not in aggregate
    assert "values" not in aggregate


@pytest.mark.django_db
def test_result_summary_honors_custom_stop_words(teacher):
    session = create_instant_session(owner=teacher, title="Custom stop words")
    definition = create_activity_definition(
        owner=teacher,
        title="Cloud",
        type_key="liveclassroom.word_cloud",
        definition={"prompt": "Say something", "stop_words": ["ignoreme"]},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    participant = join_guest(session=session, display_name="Ada")
    submit_answer(activity=activity, participant=participant, answer={"text": "python ignoreme django"})

    summary = result_summary(activity)

    assert "python" in summary["word_frequencies"]
    assert "django" in summary["word_frequencies"]
    assert "ignoreme" not in summary["word_frequencies"]


@pytest.mark.django_db
def test_review_flag_stays_in_sync_via_channel_settings(teacher):
    session = create_instant_session(owner=teacher, title="Review sync")
    definition = create_activity_definition(
        owner=teacher,
        title="Poll",
        type_key="liveclassroom.poll",
        definition={"options": [{"id": "A", "text": "One"}]},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    publish_activity_to_channel(session=session, activity=activity, channel="participants", actor=teacher)
    assert activity.reviewable is False

    update_channel_visibility(session=session, channel="participants", actor=teacher, allow_review=True)

    activity.refresh_from_db()
    assert activity.reviewable is True


@pytest.mark.django_db
def test_launch_targets_one_channel_and_does_not_replace_the_other(teacher):
    session = create_instant_session(owner=teacher, title="Independent channels")
    first = create_activity_definition(
        owner=teacher,
        title="Display content",
        type_key="liveclassroom.markdown",
        definition={"markdown": "Display"},
    )
    second = create_activity_definition(
        owner=teacher,
        title="Participant prompt",
        type_key="liveclassroom.poll",
        definition={"options": [{"id": "A", "text": "One"}]},
    )
    start_session(session=session, actor=teacher)

    display_activity = launch_item(session=session, item=first, actor=teacher)
    participant_activity = launch_item(
        session=session,
        item=second,
        actor=teacher,
        channel="participants",
    )

    session.refresh_from_db()
    assert session.channel_states.get(channel="display").current_activity_id == display_activity.id
    assert session.channel_states.get(channel="participants").current_activity_id == participant_activity.id


@pytest.mark.django_db
def test_new_participant_publish_resets_compatibility_review_mirror(teacher):
    session = create_instant_session(owner=teacher, title="Review lifecycle")
    first = create_activity_definition(
        owner=teacher,
        title="First",
        type_key="liveclassroom.poll",
        definition={"options": [{"id": "A", "text": "One"}]},
    )
    second = create_activity_definition(
        owner=teacher,
        title="Second",
        type_key="liveclassroom.poll",
        definition={"options": [{"id": "B", "text": "Two"}]},
    )
    start_session(session=session, actor=teacher)
    first_activity = launch_item(session=session, item=first, actor=teacher, channel="participants")
    publish_activity_to_channel(
        session=session,
        activity=first_activity,
        channel="participants",
        actor=teacher,
        allow_review=True,
    )
    second_activity = launch_item(session=session, item=second, actor=teacher, channel="participants")
    publish_activity_to_channel(session=session, activity=second_activity, channel="participants", actor=teacher)

    first_activity.refresh_from_db()
    second_activity.refresh_from_db()
    state = session.channel_states.get(channel="participants")
    assert first_activity.reviewable is True
    assert second_activity.reviewable is False
    assert state.allow_review is False


@pytest.mark.django_db
def test_staff_history_uses_activity_reveal_visibility(teacher):
    session = create_instant_session(owner=teacher, title="Staff history")
    definition = create_activity_definition(
        owner=teacher,
        title="Staff answer",
        type_key="liveclassroom.single_choice",
        definition={
            "options": [{"id": "A", "text": "One"}],
            "answer": ["A"],
            "explanation_markdown": "Because it is correct.",
        },
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)

    set_activity_state(activity=activity, state="closed", actor=teacher)
    set_activity_state(activity=activity, state="revealed", actor=teacher)

    staff = Client()
    staff.force_login(teacher)
    response = staff.get(reverse("liveclassroom:api-v1-history", args=[session.id]))

    assert response.status_code == 200
    history_definition = response.json()["activities"][0]["definition"]
    assert history_definition["content"]["answer"] == ["A"]
    assert history_definition["content"]["explanation_markdown"] == "Because it is correct."


@pytest.mark.django_db
def test_media_policy_rejects_ambiguous_absolute_urls_and_credentials():
    media = activity_registry.get("liveclassroom.media")
    bad_urls = (
        "//user:pass@example.com/embed",
        "https://",
        "https://example.com:invalid/embed",
        "https://example.com/embed#fragment",
        "https:\\example.com\\embed",
    )
    with override_settings(LIVECLASSROOM={"ALLOW_IFRAME": True}):
        for url in bad_urls:
            with pytest.raises(ValueError):
                media.validate({"url": url, "media_type": "iframe"})


@pytest.mark.django_db
def test_direct_media_write_is_validated_and_legacy_media_audit_can_repair(teacher):
    with pytest.raises(ValidationError):
        ActivityDefinition.objects.create(
            owner=teacher,
            title="Unsafe direct write",
            type_key="liveclassroom.media",
            definition={"url": "https://user:pass@example.com/image.png", "media_type": "image"},
        )

    definition = create_activity_definition(
        owner=teacher,
        title="Legacy media",
        type_key="liveclassroom.media",
        definition={"url": "https://example.com/image.png", "media_type": "image"},
    )
    ActivityDefinition.objects.filter(pk=definition.pk).update(
        definition={"url": "https://example.com/image.png#unsafe", "media_type": "image"}
    )
    output = StringIO()
    call_command("audit_liveclassroom_media", stdout=output)
    assert "ActivityDefinition" in output.getvalue()
    call_command("audit_liveclassroom_media", "--repair", stdout=StringIO())
    definition.refresh_from_db()
    assert definition.status == ActivityDefinition.Status.ARCHIVED


@pytest.mark.django_db
def test_unsafe_legacy_live_activity_is_not_rendered(teacher):
    session = create_instant_session(owner=teacher, title="Legacy render")
    start_session(session=session, actor=teacher)
    activity = LiveActivity.objects.create(
        session=session,
        sequence=1,
        kind="iframe",
        definition_snapshot={
            "kind": "iframe",
            "title": "Unsafe frame",
            "content": {"url": "//user:pass@example.com/embed", "media_type": "iframe"},
        },
    )
    SessionChannelState.objects.filter(session=session, channel="display").update(current_activity=activity)
    staff = Client()
    staff.force_login(teacher)
    payload = staff.get(
        reverse("liveclassroom:api-v1-state", args=[session.id]), {"channel": "display"}
    ).json()
    definition = payload["current_activity"]["definition"]
    assert definition["media_disabled"] is True
    assert "url" not in json.dumps(definition)


@pytest.mark.django_db
def test_media_audit_repairs_malformed_live_activity_snapshot(teacher):
    session = create_instant_session(owner=teacher, title="Malformed legacy media")
    activity = LiveActivity.objects.create(session=session, sequence=1, kind="iframe", definition_snapshot=[])

    call_command("audit_liveclassroom_media", "--repair", stdout=StringIO())

    activity.refresh_from_db()
    assert activity.definition_snapshot["media_disabled"] is True
