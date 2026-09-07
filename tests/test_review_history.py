import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core import signing
from django.test import Client, RequestFactory
from django.urls import reverse

from liveclassroom.api_assets import _can_read_session_asset
from liveclassroom.api_review import review_settings
from liveclassroom.models import ActivityRunRevision, LiveActivity, LiveSession, SessionChannelState, SessionEvent
from liveclassroom.services.classroom import (
    create_activity_definition,
    create_instant_session,
    end_session,
    join_guest,
    launch_item,
    start_session,
    submit_answer,
)


def post_json(client, url, payload=None, **headers):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json", **headers)


@pytest.fixture
def review_teacher(db):
    return get_user_model().objects.create_user(username="review-teacher")


@pytest.fixture
def review_classroom(review_teacher):
    session = create_instant_session(owner=review_teacher, title="Review classroom")
    definition = create_activity_definition(
        owner=review_teacher,
        title="Review question",
        type_key="liveclassroom.single_choice",
        definition={
            "prompt": "Which answer is correct?",
            "options": [{"id": "A", "text": "Correct"}, {"id": "B", "text": "Other"}],
            "answer": ["A"],
            "explanation_markdown": "A is correct.",
        },
    )
    start_session(session=session, actor=review_teacher)
    activity = launch_item(session=session, item=definition, actor=review_teacher)
    return session, activity


def review_request(user, activity_id, payload, **headers):
    request = RequestFactory().post(
        f"/api/v1/activities/{activity_id}/review/",
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )
    request.user = user
    return review_settings(request, activity_id)


def asset_request(user, session, participant=None, token=None):
    query = {"act_as_token": token} if token else None
    request = RequestFactory().get("/asset/", query)
    request.user = user
    request.session = {}
    if participant is not None:
        request.session[f"liveclassroom.participant.{session.id}"] = participant.id
    return request


@pytest.mark.django_db
def test_participant_history_filters_and_redacts_per_activity(review_classroom):
    session, activity = review_classroom
    hidden = LiveActivity.objects.create(
        session=session,
        sequence=activity.sequence + 1,
        kind="single_choice",
        definition_snapshot=activity.definition_snapshot,
    )
    activity.reviewable = True
    activity.review_visibility = {"show_answer": True, "show_explanation": False}
    activity.save(update_fields=["reviewable", "review_visibility"])

    student = Client()
    joined = post_json(student, reverse("liveclassroom:api-v1-join", args=[session.join_code]), {"display_name": "Ada"})
    assert joined.status_code == 201

    response = student.get(reverse("liveclassroom:api-v1-history", args=[session.id]))

    assert response.status_code == 200
    activities = response.json()["activities"]
    assert [item["id"] for item in activities] == [activity.id]
    item = activities[0]
    assert item["revision_id"] == activity.current_revision_id
    assert item["definition"]["content"]["answer"] == ["A"]
    assert "explanation_markdown" not in item["definition"]["content"]
    assert "reviewable" not in item
    assert "review_visibility" not in item
    assert item["own_submission"] is None
    assert hidden.id not in [entry["id"] for entry in activities]


@pytest.mark.django_db
def test_history_limits_own_submission_and_act_as_scope(review_classroom, review_teacher):
    session, activity = review_classroom
    activity.reviewable = True
    activity.save(update_fields=["reviewable"])
    first = join_guest(session=session, display_name="Ada", guest_id="ada-review")
    second = join_guest(session=session, display_name="Grace", guest_id="grace-review")
    submit_answer(activity=activity, participant=first, answer={"choice": "A"})
    submit_answer(activity=activity, participant=second, answer={"choice": "B"})

    student = Client()
    student_session = student.session
    student_session[f"liveclassroom.guest.{session.id}"] = "ada-review"
    student_session.save()
    assert post_json(
        student,
        reverse("liveclassroom:api-v1-join", args=[session.join_code]),
        {"display_name": "Ada"},
    ).status_code == 201
    history = student.get(reverse("liveclassroom:api-v1-history", args=[session.id])).json()["activities"]
    assert history[0]["own_submission"] == {"answer": {"choice": "A"}, "is_stale": False}
    assert "participant_id" not in history[0]["own_submission"]

    token = signing.dumps(
        {"session_id": session.id, "participant_id": second.id, "actor_id": review_teacher.pk, "active": False},
        salt="liveclassroom.act-as",
        compress=True,
    )
    staff = Client()
    staff.force_login(review_teacher)
    act_as = staff.get(
        reverse("liveclassroom:api-v1-history", args=[session.id]),
        {"act_as_token": token},
    )
    assert act_as.status_code == 200
    act_as_item = act_as.json()["activities"][0]
    assert act_as_item["own_submission"] == {"answer": {"choice": "B"}, "is_stale": False}
    assert "reviewable" not in act_as_item
    assert "review_visibility" not in act_as_item


@pytest.mark.django_db
def test_staff_history_includes_all_activities_and_review_metadata(review_classroom, review_teacher):
    session, activity = review_classroom
    activity.reviewable = True
    activity.review_visibility = {"show_answer": False, "show_explanation": True}
    activity.save(update_fields=["reviewable", "review_visibility"])
    hidden = LiveActivity.objects.create(
        session=session,
        sequence=activity.sequence + 1,
        kind="markdown",
        definition_snapshot={"type_key": "liveclassroom.markdown", "kind": "markdown", "title": "Hidden"},
    )

    staff = Client()
    staff.force_login(review_teacher)
    response = staff.get(reverse("liveclassroom:api-v1-history", args=[session.id]))

    assert response.status_code == 200
    activities = response.json()["activities"]
    assert [item["id"] for item in activities] == [activity.id, hidden.id]
    item = activities[0]
    assert item["reviewable"] is True
    assert item["review_visibility"] == {"show_answer": False, "show_explanation": True}
    assert item["definition"]["content"]["answer"] == ["A"]
    assert item["definition"]["content"]["explanation_markdown"] == "A is correct."
    assert "own_submission" not in item


@pytest.mark.django_db
def test_review_settings_manager_can_update_after_end_and_audits(review_classroom, review_teacher):
    session, activity = review_classroom
    participant_channel = session.channel_states.get(channel="participants")
    before_channel_flags = (participant_channel.show_answer, participant_channel.show_explanation)
    end_session(session=session, actor=review_teacher)
    session.refresh_from_db()
    ended_version = session.state_version
    before_review_events = SessionEvent.objects.count()

    with patch("liveclassroom.api_review.notify_session_after_commit") as notify:
        response = review_request(
            review_teacher,
            activity.id,
            {"reviewable": True, "show_answer": True, "show_explanation": True},
        )

    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload["reviewable"] is True
    assert payload["review_visibility"] == {"show_answer": True, "show_explanation": True}
    activity.refresh_from_db()
    session.refresh_from_db()
    participant_channel.refresh_from_db()
    assert activity.reviewable is True
    assert activity.review_visibility == payload["review_visibility"]
    assert session.state_version == ended_version + 1
    assert (participant_channel.show_answer, participant_channel.show_explanation) == before_channel_flags
    event = SessionEvent.objects.order_by("-sequence").first()
    assert SessionEvent.objects.count() == before_review_events + 1
    assert event.event_type == "activity.review.updated"
    assert event.actor_id == review_teacher.id
    assert event.payload["activity_id"] == activity.id
    notify.assert_called_once()


@pytest.mark.django_db
def test_review_settings_requires_manager_and_boolean_fields(review_classroom):
    session, activity = review_classroom
    other = get_user_model().objects.create_user(username="review-other")
    denied = review_request(other, activity.id, {"reviewable": True})
    assert denied.status_code == 403

    malformed = review_request(session.teacher, activity.id, {"show_answer": "yes"})
    assert malformed.status_code == 400
    unknown = review_request(session.teacher, activity.id, {"show_prompt": True})
    assert unknown.status_code == 400
    assert SessionEvent.objects.filter(event_type="activity.review.updated").count() == 0


@pytest.mark.django_db
def test_session_asset_access_respects_current_revision_prompt_and_act_as_scope(review_classroom, review_teacher):
    session, activity = review_classroom
    participant = join_guest(session=session, display_name="Ada", guest_id="asset-review")
    current = activity.current_revision
    old = ActivityRunRevision.objects.create(
        activity=activity,
        revision=0,
        definition_snapshot=activity.definition_snapshot,
    )
    participant_state = session.channel_states.get(channel=SessionChannelState.Channel.PARTICIPANTS)
    participant_state.current_activity = activity
    participant_state.current_revision = current
    participant_state.show_prompt = True
    participant_state.save(update_fields=["current_activity", "current_revision", "show_prompt"])

    student_request = asset_request(AnonymousUser(), session, participant)
    assert _can_read_session_asset(student_request, session, current) is True
    participant_state.show_prompt = False
    participant_state.save(update_fields=["show_prompt"])
    assert _can_read_session_asset(student_request, session, current) is False

    token = signing.dumps(
        {"session_id": session.id, "participant_id": participant.id, "actor_id": review_teacher.pk, "active": False},
        salt="liveclassroom.act-as",
        compress=True,
    )
    act_as_request = asset_request(review_teacher, session, token=token)
    assert _can_read_session_asset(act_as_request, session, old) is False
    assert _can_read_session_asset(act_as_request, session, current) is False

    end_session(session=session, actor=review_teacher)
    activity.reviewable = True
    activity.save(update_fields=["reviewable"])
    refreshed_session = LiveSession.objects.get(pk=session.pk)
    refreshed_current = ActivityRunRevision.objects.select_related("activity").get(pk=current.pk)
    assert _can_read_session_asset(student_request, refreshed_session, refreshed_current) is True
    assert _can_read_session_asset(student_request, refreshed_session, old) is False
