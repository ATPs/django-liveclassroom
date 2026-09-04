from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from liveclassroom.models import (
    ActivityRunRevision,
    Course,
    Flow,
    FlowItem,
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
    create_activity_definition,
    create_instant_session,
    delete_session,
    end_session,
    join_guest,
    launch_item,
    pause_session,
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
    assert session.channel_states.get(channel=SessionChannelState.Channel.DISPLAY).allow_review is True


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
def test_activity_and_submission_revisions_preserve_history(teacher):
    course = Course.objects.create(title="Course", slug="foundation", created_by=teacher)
    flow = Flow.objects.create(course=course, created_by=teacher, title="Flow", slug="flow")
    item = FlowItem.objects.create(
        flow=flow,
        position=1,
        kind=FlowItem.Kind.POLL,
        content={"options": [{"id": "A"}, {"id": "B"}]},
    )
    session = LiveSession.objects.create(course=course, flow=flow, teacher=teacher, title="Revision test")
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=item, actor=teacher)
    participant = join_guest(session=session, display_name="Ada")

    submission = submit_answer(activity=activity, participant=participant, answer={"choice": "A"})
    submit_answer(activity=activity, participant=participant, answer={"choice": "B"})
    submission.refresh_from_db()
    assert submission.revisions.count() == 2
    assert submission.current_revision.answer == {"choice": "B"}

    run_revision = revise_activity(
        activity=activity,
        definition_snapshot={"kind": "poll", "content": {"options": [{"id": "C"}]}},
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

    with pytest.raises(ClassroomError, match="Archive"):
        delete_session(session=session, actor=teacher)
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
