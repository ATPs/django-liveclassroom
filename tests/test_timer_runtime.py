import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from liveclassroom.models import LiveSession
from liveclassroom.services.classroom import (
    command_timer,
    create_activity_definition,
    create_instant_session,
    launch_item,
    pause_session,
    start_session,
    timer_runtime_state,
)


@pytest.mark.django_db
def test_timer_uses_server_runtime_and_only_starts_when_commanded(client):
    teacher = get_user_model().objects.create_user(username="timer-teacher")
    session = create_instant_session(owner=teacher, title="Timer class")
    definition = create_activity_definition(
        owner=teacher,
        title="Two minutes",
        type_key="liveclassroom.timer",
        definition={"duration_seconds": 120, "auto_start": False},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    activity.refresh_from_db()

    assert timer_runtime_state(activity)["status"] == "idle"
    assert timer_runtime_state(activity)["remaining_seconds"] == 120
    running = command_timer(activity=activity, action="start", actor=teacher)
    assert running["status"] == "running"
    assert running["deadline"] is not None

    paused = command_timer(activity=activity, action="pause", actor=teacher)
    assert paused["status"] == "paused"
    assert paused["deadline"] is None
    assert 0 < paused["remaining_seconds"] <= 120

    client.force_login(teacher)
    state = client.get(reverse("liveclassroom:api-v1-state", args=[session.id])).json()
    assert isinstance(state["server_time"], float)
    assert state["current_activity"]["runtime"]["status"] == "paused"


@pytest.mark.django_db
def test_classroom_pause_only_resumes_timers_it_paused():
    teacher = get_user_model().objects.create_user(username="timer-pause-teacher")
    session = create_instant_session(owner=teacher, title="Timer pause")
    definition = create_activity_definition(
        owner=teacher,
        title="Timer",
        type_key="liveclassroom.timer",
        definition={"duration_seconds": 60, "auto_start": True},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    assert timer_runtime_state(activity)["status"] == "running"

    pause_session(session=session, actor=teacher)
    activity.refresh_from_db()
    assert activity.runtime_state["status"] == "paused"
    assert activity.runtime_state["paused_by_classroom"] is True

    start_session(session=session, actor=teacher)
    activity.refresh_from_db()
    assert session.status == LiveSession.Status.LIVE
    assert activity.runtime_state["status"] == "running"
    assert activity.runtime_state["paused_by_classroom"] is False


@pytest.mark.django_db
def test_timer_api_requires_manager_and_replays_the_same_command(client):
    teacher = get_user_model().objects.create_user(username="timer-api-teacher")
    other = get_user_model().objects.create_user(username="timer-api-other")
    session = create_instant_session(owner=teacher, title="Timer API")
    definition = create_activity_definition(
        owner=teacher, title="Timer", type_key="liveclassroom.timer", definition={"duration_seconds": 30},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    url = reverse("liveclassroom:api-v1-timer", args=[activity.id])

    client.force_login(other)
    assert client.post(url, data=json.dumps({"action": "start"}), content_type="application/json").status_code == 403
    client.force_login(teacher)
    first = client.post(
        url, data=json.dumps({"action": "start"}), content_type="application/json", HTTP_IDEMPOTENCY_KEY="timer-once",
    )
    replay = client.post(
        url, data=json.dumps({"action": "start"}), content_type="application/json", HTTP_IDEMPOTENCY_KEY="timer-once",
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["runtime"] == replay.json()["runtime"]
    session.refresh_from_db()
    assert first.json()["version"] == session.state_version
