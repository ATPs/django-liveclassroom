import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import LiveSession, SessionChannelState, Submission
from liveclassroom.services.classroom import (
    create_activity_definition,
    create_instant_session,
    end_session,
    launch_item,
    pause_session,
    publish_activity_to_channel,
    revise_activity,
    start_session,
    update_channel_visibility,
)


@pytest.fixture
def teacher(db):
    return get_user_model().objects.create_user(username="submission-boundary-teacher")


@pytest.fixture
def student(db):
    return get_user_model().objects.create_user(username="submission-boundary-student")


def post_json(client, url, payload, **headers):
    return client.post(url, data=json.dumps(payload), content_type="application/json", **headers)


def short_text_snapshot(prompt, title="Short text"):
    return {
        "schema_version": 1,
        "type_key": "liveclassroom.short_text",
        "kind": "short_text",
        "title": title,
        "content": {"prompt": prompt},
    }


@pytest.fixture
def submission_context(teacher, student):
    session = create_instant_session(
        owner=teacher,
        title="Submission boundaries",
        access_mode=LiveSession.AccessMode.BOTH,
    )
    definition = create_activity_definition(
        owner=teacher,
        title="Short text",
        type_key="liveclassroom.short_text",
        definition={"prompt": "What did you learn?"},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)

    student_client = Client()
    student_client.force_login(student)
    joined = post_json(student_client, reverse("liveclassroom:api-v1-join-account", args=[session.id]), {})
    assert joined.status_code == 201
    return session, activity, teacher, student, student_client


def publish_for_participants(session, activity, teacher, *, reviewable=False):
    return publish_activity_to_channel(
        session=session,
        activity=activity,
        channel=SessionChannelState.Channel.PARTICIPANTS,
        actor=teacher,
        allow_review=reviewable,
    )


def submit_payload(activity, answer="A learned answer"):
    return {
        "activity_revision_id": activity.current_revision_id,
        "answer": {"text": answer},
    }


@pytest.mark.django_db
def test_submit_requires_a_positive_current_activity_revision_id(submission_context):
    session, activity, teacher, _student, student_client = submission_context
    publish_for_participants(session, activity, teacher)

    missing = post_json(
        student_client,
        reverse("liveclassroom:api-v1-submit", args=[activity.id]),
        {"answer": {"text": "Missing revision"}},
    )
    boolean = post_json(
        student_client,
        reverse("liveclassroom:api-v1-submit", args=[activity.id]),
        {"activity_revision_id": True, "answer": {"text": "Boolean revision"}},
    )
    old_revision_id = activity.current_revision_id
    revision = revise_activity(
        activity=activity,
        definition_snapshot=short_text_snapshot("Current prompt"),
        actor=teacher,
    )
    activity.refresh_from_db()
    old = post_json(
        student_client,
        reverse("liveclassroom:api-v1-submit", args=[activity.id]),
        {"activity_revision_id": old_revision_id, "answer": {"text": "Old revision"}},
    )

    assert missing.status_code == boolean.status_code == old.status_code == 409
    assert missing.json()["detail"] == "activity_revision_id is required."
    assert boolean.json()["detail"] == "activity_revision_id is required."
    assert "revision changed" in old.json()["detail"]
    assert revision.id == activity.current_revision_id
    assert not Submission.objects.exists()


@pytest.mark.django_db
def test_display_only_activity_cannot_receive_student_submission(submission_context):
    _session, activity, _teacher, _student, student_client = submission_context

    response = post_json(
        student_client,
        reverse("liveclassroom:api-v1-submit", args=[activity.id]),
        submit_payload(activity),
    )

    assert response.status_code == 409
    assert "published for participant responses" in response.json()["detail"]
    assert not Submission.objects.exists()


@pytest.mark.django_db
def test_hidden_participant_prompt_rejects_submission_even_when_reviewable(submission_context):
    session, activity, teacher, _student, student_client = submission_context
    publish_for_participants(session, activity, teacher, reviewable=True)
    update_channel_visibility(
        session=session,
        channel=SessionChannelState.Channel.PARTICIPANTS,
        actor=teacher,
        show_prompt=False,
    )

    response = post_json(
        student_client,
        reverse("liveclassroom:api-v1-submit", args=[activity.id]),
        submit_payload(activity),
    )

    assert response.status_code == 409
    assert "published for participant responses" in response.json()["detail"]
    assert not Submission.objects.exists()


@pytest.mark.django_db
def test_submit_and_revise_record_student_as_actor_for_each_revision(submission_context):
    session, activity, teacher, student, student_client = submission_context
    publish_for_participants(session, activity, teacher)
    old_revision_id = activity.current_revision_id

    first = post_json(
        student_client,
        reverse("liveclassroom:api-v1-submit", args=[activity.id]),
        submit_payload(activity, "First answer"),
    )
    teacher_client = Client()
    teacher_client.force_login(teacher)
    revised = post_json(
        teacher_client,
        reverse("liveclassroom:api-v1-revise", args=[activity.id]),
        {"definition": short_text_snapshot("Updated prompt")},
    )
    activity.refresh_from_db()
    second = post_json(
        student_client,
        reverse("liveclassroom:api-v1-submit", args=[activity.id]),
        submit_payload(activity, "Second answer"),
    )

    assert first.status_code == 201
    assert revised.status_code == 201
    assert second.status_code == 201
    submission = Submission.objects.get(pk=first.json()["submission_id"])
    revisions = list(submission.revisions.order_by("revision"))
    assert len(revisions) == 2
    assert [revision.activity_revision_id for revision in revisions] == [
        old_revision_id,
        activity.current_revision_id,
    ]
    assert [revision.performed_by_id for revision in revisions] == [student.id, student.id]
    assert submission.answer == {"text": "Second answer"}
    assert submission.is_stale is False


@pytest.mark.django_db
def test_pause_and_end_reject_new_submissions(submission_context):
    session, activity, teacher, _student, student_client = submission_context
    publish_for_participants(session, activity, teacher)

    pause_session(session=session, actor=teacher)
    paused = post_json(
        student_client,
        reverse("liveclassroom:api-v1-submit", args=[activity.id]),
        submit_payload(activity, "Paused answer"),
    )
    start_session(session=session, actor=teacher)
    end_session(session=session, actor=teacher)
    ended = post_json(
        student_client,
        reverse("liveclassroom:api-v1-submit", args=[activity.id]),
        submit_payload(activity, "Ended answer"),
    )

    assert paused.status_code == ended.status_code == 409
    assert "not accepting answers" in paused.json()["detail"]
    assert "not accepting answers" in ended.json()["detail"]
    assert not Submission.objects.exists()


@pytest.mark.django_db
def test_submission_retry_with_same_key_replays_original_success_once(submission_context):
    session, activity, teacher, _student, student_client = submission_context
    publish_for_participants(session, activity, teacher)
    payload = submit_payload(activity, "Retry-safe answer")
    url = reverse("liveclassroom:api-v1-submit", args=[activity.id])

    first = post_json(student_client, url, payload, HTTP_IDEMPOTENCY_KEY="submission-once")
    retry = post_json(student_client, url, payload, HTTP_IDEMPOTENCY_KEY="submission-once")

    assert first.status_code == retry.status_code == 201
    assert retry.headers["Idempotent-Replay"] == "true"
    assert retry.json() == first.json()
    assert Submission.objects.count() == 1
    assert Submission.objects.get().revisions.count() == 1


@pytest.mark.django_db
def test_ended_session_freezes_connection_records(submission_context):
    from liveclassroom.services.classroom import mark_participant_connected, mark_participant_disconnected

    session, _activity, teacher, student, _client = submission_context
    participant = session.participants.get(user=student)
    mark_participant_connected(participant=participant, connection_id="before-end")
    end_session(session=session, actor=teacher)
    participant.refresh_from_db()
    frozen = (participant.last_seen_at, participant.disconnected_at)
    assert frozen[1] is not None
    assert not participant.connections.filter(disconnected_at=None).exists()
    mark_participant_connected(participant=participant, connection_id="review-after-end")
    mark_participant_disconnected(participant=participant, connection_id="before-end")
    participant.refresh_from_db()
    assert (participant.last_seen_at, participant.disconnected_at) == frozen
    assert participant.connections.count() == 1
