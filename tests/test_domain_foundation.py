import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from liveclassroom.models import (
    ActivityRunRevision,
    LiveActivity,
    LiveSession,
    Participant,
    SessionChannelState,
    SessionStaff,
    SubmissionRevision,
)
from liveclassroom.services.classroom import (
    ClassroomError,
    archive_session,
    can_manage_admission,
    can_manage_session,
    can_view_display,
    can_view_session,
    close_and_show_answer,
    create_activity_definition,
    create_instant_session,
    delete_session,
    end_session,
    join_authenticated,
    join_guest,
    launch_item,
    pause_session,
    publish_activity_to_audiences,
    publish_activity_to_channel,
    purge_expired_sessions,
    revise_activity,
    start_session,
    submit_answer,
)


@pytest.fixture
def teacher(db):
    return get_user_model().objects.create_user(username="foundation-teacher")


@pytest.mark.django_db
def test_instant_session_has_independent_channels_and_reusable_activity(teacher):
    session = create_instant_session(owner=teacher, title="RNA-seq live class")
    assert session.course_id is None
    assert session.flow_id is None
    assert set(session.channel_states.values_list("channel", flat=True)) == {
        SessionChannelState.Channel.DISPLAY,
        SessionChannelState.Channel.PARTICIPANTS,
    }

    definition = create_activity_definition(
        owner=teacher,
        title="Choose a count matrix",
        type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "A", "text": "Raw counts"}]},
    )
    assert definition.current_revision.revision == 1

    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    display = session.channel_states.get(channel=SessionChannelState.Channel.DISPLAY)
    participants = session.channel_states.get(channel=SessionChannelState.Channel.PARTICIPANTS)
    assert activity.current_revision.revision == 1
    assert display.current_activity_id == activity.id
    assert participants.current_activity_id is None

    publish_activity_to_channel(
        session=session,
        activity=activity,
        channel=SessionChannelState.Channel.DISPLAY,
        actor=teacher,
        allow_review=True,
    )
    assert activity.reviewable is True


@pytest.mark.django_db
def test_start_session_can_publish_a_selected_starting_item(teacher):
    from liveclassroom.models import SessionPlanStep
    from liveclassroom.services.flows import add_flow_step, create_flow
    from liveclassroom.services.plans import create_session

    flow = create_flow(title="Starting item", creator=teacher)
    definition = create_activity_definition(
        owner=teacher, title="Welcome", type_key="liveclassroom.markdown", definition={"markdown": "Welcome"},
    )
    add_flow_step(flow=flow, actor=teacher, activity_definition=definition)
    session = create_session(owner=teacher, title="Start selected", flow=flow)
    step = SessionPlanStep.objects.get(session=session, position=1)

    start_session(session=session, actor=teacher, starting_item=step)

    assert session.status == LiveSession.Status.LIVE
    assert {state.current_activity_id for state in session.channel_states.all()} == {session.activities.get().id}


@pytest.mark.django_db
def test_start_prepared_session_publishes_the_first_plan_step_by_default(teacher):
    from liveclassroom.services.flows import add_flow_step, create_flow
    from liveclassroom.services.plans import create_session

    flow = create_flow(title="Default start", creator=teacher)
    welcome = create_activity_definition(
        owner=teacher, title="Welcome", type_key="liveclassroom.markdown", definition={"markdown": "Welcome"},
    )
    add_flow_step(flow=flow, actor=teacher, activity_definition=welcome)
    session = create_session(owner=teacher, title="Default item", flow=flow)

    start_session(session=session, actor=teacher)

    activity = session.activities.get()
    assert activity.plan_step.position == 1
    assert set(session.channel_states.values_list("current_activity_id", flat=True)) == {activity.id}


@pytest.mark.django_db
def test_publishing_a_new_activity_resets_feedback_without_resetting_same_activity(teacher):
    session = create_instant_session(owner=teacher, title="Visibility reset")
    first = create_activity_definition(
        owner=teacher, title="First", type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "a", "text": "A"}]},
    )
    second = create_activity_definition(
        owner=teacher, title="Second", type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "b", "text": "B"}]},
    )
    start_session(session=session, actor=teacher)
    first_run = launch_item(session=session, item=first, actor=teacher)
    state = session.channel_states.get(channel=SessionChannelState.Channel.DISPLAY)
    state.show_aggregate = state.show_answer = state.show_explanation = True
    state.save(update_fields=["show_aggregate", "show_answer", "show_explanation"])
    publish_activity_to_channel(session=session, activity=first_run, channel="display", actor=teacher)
    state.refresh_from_db()
    assert state.show_answer and state.show_explanation
    second_run = launch_item(session=session, item=second, actor=teacher)
    state.refresh_from_db()
    assert state.current_activity_id == second_run.id
    assert state.show_prompt is True
    assert state.show_aggregate is state.show_answer is state.show_explanation is False


@pytest.mark.django_db
def test_two_audience_publication_rolls_back_if_the_second_channel_fails(teacher, monkeypatch):
    """A failed participant update must not strand the display on another item."""
    import liveclassroom.services.classroom as classroom_service

    session = create_instant_session(owner=teacher, title="Atomic audience publication")
    first = create_activity_definition(
        owner=teacher, title="First", type_key="liveclassroom.markdown", definition={"markdown": "First"},
    )
    second = create_activity_definition(
        owner=teacher, title="Second", type_key="liveclassroom.markdown", definition={"markdown": "Second"},
    )
    start_session(session=session, actor=teacher)
    first_run = launch_item(session=session, item=first, actor=teacher)
    publish_activity_to_audiences(
        session=session,
        activity=first_run,
        channels=[SessionChannelState.Channel.DISPLAY, SessionChannelState.Channel.PARTICIPANTS],
        actor=teacher,
    )
    second_run = launch_item(session=session, item=second, actor=teacher)
    # `launch_item()` preserves its legacy display-launch behavior. Restore a
    # common baseline before testing the two-audience publisher in isolation.
    publish_activity_to_audiences(
        session=session,
        activity=first_run,
        channels=[SessionChannelState.Channel.DISPLAY, SessionChannelState.Channel.PARTICIPANTS],
        actor=teacher,
    )
    original_publish = classroom_service.publish_activity_to_channel

    def fail_participants(*, channel, **kwargs):
        if channel == SessionChannelState.Channel.PARTICIPANTS:
            raise ClassroomError("simulated participant publication failure")
        return original_publish(channel=channel, **kwargs)

    monkeypatch.setattr(classroom_service, "publish_activity_to_channel", fail_participants)
    with pytest.raises(ClassroomError, match="simulated participant publication failure"):
        publish_activity_to_audiences(
            session=session,
            activity=second_run,
            channels=[SessionChannelState.Channel.DISPLAY, SessionChannelState.Channel.PARTICIPANTS],
            actor=teacher,
        )

    states = SessionChannelState.objects.filter(session=session)
    assert set(states.values_list("current_activity_id", flat=True)) == {first_run.id}


@pytest.mark.django_db
def test_close_and_show_answer_is_atomic_and_only_affects_active_audiences(teacher):
    session = create_instant_session(owner=teacher, title="Answer reveal")
    definition = create_activity_definition(
        owner=teacher, title="Scored", type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "a", "text": "A"}], "answer": "a"},
    )
    other_definition = create_activity_definition(
        owner=teacher, title="Held", type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "b", "text": "B"}]},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    other = launch_item(session=session, item=other_definition, actor=teacher)
    publish_activity_to_channel(session=session, activity=activity, channel="display", actor=teacher)
    publish_activity_to_channel(session=session, activity=other, channel="participants", actor=teacher)

    close_and_show_answer(activity=activity, actor=teacher)

    activity.refresh_from_db()
    display = session.channel_states.get(channel="display")
    participants = session.channel_states.get(channel="participants")
    assert activity.state == LiveActivity.State.REVEALED
    assert display.show_answer is True
    assert participants.current_activity_id == other.id
    assert participants.show_answer is False


@pytest.mark.django_db
def test_close_and_show_answer_api_replays_without_a_second_transition(client, teacher):
    session = create_instant_session(owner=teacher, title="Replay answer reveal")
    definition = create_activity_definition(
        owner=teacher, title="Scored", type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "a", "text": "A"}], "answer": "a"},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    publish_activity_to_channel(session=session, activity=activity, channel="display", actor=teacher)
    client.force_login(teacher)
    url = reverse("liveclassroom:api-v1-close-and-show-answer", args=[activity.id])

    first = client.post(url, data="{}", content_type="application/json", HTTP_IDEMPOTENCY_KEY="show-once")
    replay = client.post(url, data="{}", content_type="application/json", HTTP_IDEMPOTENCY_KEY="show-once")

    assert first.status_code == replay.status_code == 200
    assert replay.headers["Idempotent-Replay"] == "true"
    assert first.json() == replay.json()
    assert first.json()["state"] == LiveActivity.State.REVEALED


@pytest.mark.django_db
def test_same_activity_review_change_advances_version_once(teacher):
    session = create_instant_session(owner=teacher, title="Review publication")
    definition = create_activity_definition(
        owner=teacher, title="Reviewable", type_key="liveclassroom.markdown", definition={"markdown": "Review"},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    state = session.channel_states.get(channel=SessionChannelState.Channel.DISPLAY)
    session.refresh_from_db()
    before = session.state_version

    publish_activity_to_channel(
        session=session,
        activity=activity,
        channel=SessionChannelState.Channel.DISPLAY,
        actor=teacher,
        allow_review=True,
    )
    session.refresh_from_db()
    state.refresh_from_db()
    assert activity.reviewable is True
    assert session.state_version == before + 1
    assert state.version == session.state_version
    assert session.events.order_by("-sequence").first().event_type == "activity.review.updated"

    publish_activity_to_channel(
        session=session,
        activity=activity,
        channel=SessionChannelState.Channel.DISPLAY,
        actor=teacher,
        allow_review=True,
    )
    session.refresh_from_db()
    assert session.state_version == before + 1


@pytest.mark.django_db
def test_publish_both_api_returns_authoritative_session_version(client, teacher):
    session = create_instant_session(owner=teacher, title="Both publication")
    definition = create_activity_definition(
        owner=teacher, title="Published", type_key="liveclassroom.markdown", definition={"markdown": "Published"},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    client.force_login(teacher)

    response = client.post(
        reverse("liveclassroom:api-v1-publish-channel", args=[session.id]),
        data=json.dumps({"activity_id": activity.id, "channel": "both"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    session.refresh_from_db()
    assert response.json()["version"] == session.state_version


@pytest.mark.django_db
def test_session_staff_roles_control_access_without_course(teacher):
    assistant = get_user_model().objects.create_user(username="assistant")
    observer = get_user_model().objects.create_user(username="observer")
    session = create_instant_session(owner=teacher, title="Staff test")
    SessionStaff.objects.create(session=session, user=assistant, role=SessionStaff.Role.ASSISTANT)
    SessionStaff.objects.create(session=session, user=observer, role=SessionStaff.Role.OBSERVER)

    assert not can_manage_session(assistant, session)
    assert can_manage_admission(assistant, session)
    assert not can_manage_session(observer, session)
    assert not can_view_display(observer, session)
    assert can_view_session(observer, session)


@pytest.mark.django_db
def test_guest_waiting_room_and_authenticated_access_modes(teacher):
    waiting = create_instant_session(
        owner=teacher,
        title="Waiting room",
        admission_mode=LiveSession.AdmissionMode.WAITING_ROOM,
    )
    start_session(session=waiting, actor=teacher)
    participant = join_guest(session=waiting, display_name="Ada")
    assert participant.admission_state == Participant.AdmissionState.PENDING
    with pytest.raises(ClassroomError, match="not admitted"):
        # A lightweight object is enough to exercise admission in this service test.
        from liveclassroom.models import LiveActivity

        activity = LiveActivity.objects.create(session=waiting, sequence=1, kind="poll", definition_snapshot={})
        submit_answer(activity=activity, participant=participant, answer={"choice": "A"})

    authenticated = create_instant_session(
        owner=teacher,
        title="Account only",
        access_mode=LiveSession.AccessMode.AUTHENTICATED,
    )
    start_session(session=authenticated, actor=teacher)
    with pytest.raises(ClassroomError, match="requires a Django account"):
        join_guest(session=authenticated, display_name="Guest")


@pytest.mark.django_db
def test_guest_retry_preserves_waiting_room_admission(teacher):
    session = create_instant_session(
        owner=teacher,
        title="Retry admission",
        admission_mode=LiveSession.AdmissionMode.WAITING_ROOM,
    )
    start_session(session=session, actor=teacher)
    participant = join_guest(session=session, display_name="Ada", guest_id="stable-guest")
    participant.admission_state = Participant.AdmissionState.ADMITTED
    participant.save(update_fields=["admission_state"])

    retried = join_guest(session=session, display_name="Ada", guest_id="stable-guest")

    assert retried.pk == participant.pk
    assert retried.admission_state == Participant.AdmissionState.ADMITTED


@pytest.mark.django_db
def test_authenticated_retry_preserves_waiting_room_admission(teacher):
    student = get_user_model().objects.create_user(username="authenticated-retry-student")
    session = create_instant_session(
        owner=teacher,
        title="Authenticated retry admission",
        access_mode=LiveSession.AccessMode.AUTHENTICATED,
        admission_mode=LiveSession.AdmissionMode.WAITING_ROOM,
    )
    start_session(session=session, actor=teacher)
    participant = join_authenticated(session=session, user=student)
    participant.admission_state = Participant.AdmissionState.ADMITTED
    participant.save(update_fields=["admission_state"])

    retried = join_authenticated(session=session, user=student)

    assert retried.pk == participant.pk
    assert retried.admission_state == Participant.AdmissionState.ADMITTED


@pytest.mark.django_db
def test_submission_refetches_authoritative_activity_state(teacher):
    session = create_instant_session(owner=teacher, title="Authoritative submission state")
    definition = create_activity_definition(
        owner=teacher,
        title="Poll",
        type_key="liveclassroom.poll",
        definition={"options": [{"id": "A", "text": "One"}]},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    participant = join_guest(session=session, display_name="Ada")
    LiveActivity.objects.filter(pk=activity.pk).update(state=LiveActivity.State.CLOSED)

    with pytest.raises(ClassroomError, match="no longer accepting answers"):
        submit_answer(activity=activity, participant=participant, answer={"choice": "A"})


@pytest.mark.django_db
def test_activity_and_submission_revisions_preserve_history(teacher):
    session = create_instant_session(owner=teacher, title="Revision test")
    definition = create_activity_definition(
        owner=teacher,
        title="Poll",
        type_key="liveclassroom.poll",
        definition={"options": [{"id": "A", "text": "A"}, {"id": "B", "text": "B"}]},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    participant = join_guest(session=session, display_name="Ada")

    submission = submit_answer(activity=activity, participant=participant, answer={"choice": "A"})
    submit_answer(activity=activity, participant=participant, answer={"choice": "B"})
    submission.refresh_from_db()
    assert submission.revisions.count() == 2
    assert submission.current_revision.answer == {"choice": "B"}

    run_revision = revise_activity(
        activity=activity,
        definition_snapshot={"kind": "poll", "content": {"options": [{"id": "C", "text": "C"}]}},
        actor=teacher,
    )
    submission.refresh_from_db()
    assert run_revision.revision == 2
    assert ActivityRunRevision.objects.filter(activity=activity).count() == 2
    assert submission.is_stale is True

    submit_answer(activity=activity, participant=participant, answer={"choice": "C"})
    submission.refresh_from_db()
    assert submission.is_stale is False
    assert submission.revisions.count() == 3
    assert SubmissionRevision.objects.filter(submission=submission, activity_revision=run_revision).exists()


@pytest.mark.django_db
def test_activity_submission_is_checked_against_definition_and_session_can_pause_end(teacher):
    session = create_instant_session(owner=teacher, title="Controls")
    definition = create_activity_definition(
        owner=teacher,
        title="Bounded number",
        type_key="numeric",
        definition={"prompt": "How many?", "minimum": 1, "maximum": 5},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    participant = join_guest(session=session, display_name="Ada")

    with pytest.raises(ClassroomError, match="above the allowed maximum"):
        submit_answer(activity=activity, participant=participant, answer={"value": 6})

    pause_session(session=session, actor=teacher)
    session.refresh_from_db()
    assert session.status == LiveSession.Status.PAUSED
    with pytest.raises(ClassroomError, match="Start the session"):
        launch_item(session=session, item=definition, actor=teacher)

    start_session(session=session, actor=teacher)
    end_session(session=session, actor=teacher)
    session.refresh_from_db()
    activity.refresh_from_db()
    assert session.status == LiveSession.Status.ENDED
    assert activity.state == "closed"


@pytest.mark.django_db
def test_ended_session_archive_delete_and_retention_cleanup(teacher):
    session = create_instant_session(owner=teacher, title="Retention")
    start_session(session=session, actor=teacher)
    end_session(session=session, actor=teacher)

    delete_session(session=session, actor=teacher)
    assert not LiveSession.objects.filter(pk=session.pk).exists()

    session = create_instant_session(owner=teacher, title="Retention archive")
    start_session(session=session, actor=teacher)
    end_session(session=session, actor=teacher)
    archive_session(session=session, actor=teacher)
    session.refresh_from_db()
    assert session.archived_at is not None
    archive_session(session=session, actor=teacher, archived=False)
    session.refresh_from_db()
    assert session.archived_at is None

    archive_session(session=session, actor=teacher)
    LiveSession.objects.filter(pk=session.pk).update(ended_at=timezone.now() - timedelta(days=31))
    assert purge_expired_sessions(days=30) == 1
    assert not LiveSession.objects.filter(pk=session.pk).exists()
