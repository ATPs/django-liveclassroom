"""Optional PostgreSQL acceptance for simultaneous, revision-bound HTTP answers."""

import json
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import Client
from django.urls import reverse

from liveclassroom.models import SubmissionRevision
from liveclassroom.services.classroom import (
    create_activity_definition,
    join_guest,
    launch_item,
    publish_activity_to_channel,
    start_session,
    update_channel_visibility,
)
from liveclassroom.services.plans import create_session


@pytest.mark.django_db(transaction=True)
def test_one_hundred_concurrent_students_keep_every_accepted_answer():
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL for concurrent write acceptance")
    teacher = get_user_model().objects.create_user(username="load-teacher")
    session = create_session(owner=teacher, title="100-student acceptance")
    definition = create_activity_definition(
        owner=teacher,
        title="Check understanding",
        type_key="liveclassroom.short_text",
        definition={"prompt": "One observation"},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    publish_activity_to_channel(session=session, activity=activity, channel="participants", actor=teacher)
    update_channel_visibility(session=session, channel="participants", actor=teacher, show_aggregate=True)
    clients = []
    for index in range(100):
        participant = join_guest(session=session, display_name=f"Student {index}", guest_id=f"load-{index}")
        client = Client()
        cookie = client.session
        cookie[f"liveclassroom.participant.{session.pk}"] = participant.pk
        cookie.save()
        clients.append(client)
    endpoint = reverse("liveclassroom:api-v1-submit", args=[activity.pk])

    def submit(index):
        try:
            payload = json.dumps(
                {"activity_revision_id": activity.current_revision_id, "answer": {"text": f"observation-{index}"}}
            )
            client = clients[index]
            headers = {"HTTP_IDEMPOTENCY_KEY": f"load-response-{index}"}
            first = client.post(endpoint, payload, content_type="application/json", **headers)
            replay = client.post(endpoint, payload, content_type="application/json", **headers)
            return first.status_code, replay.status_code, first.json(), replay.json()
        finally:
            connections.close_all()

    started = monotonic()
    with ThreadPoolExecutor(max_workers=16) as pool:
        responses = list(pool.map(submit, range(100)))
    assert all(
        first == replay == 201 and first_body == replay_body for first, replay, first_body, replay_body in responses
    ), responses
    assert activity.submissions.count() == 100
    assert SubmissionRevision.objects.filter(submission__activity=activity).count() == 100
    assert set(activity.submissions.values_list("answer__text", flat=True)) == {
        f"observation-{index}" for index in range(100)
    }
    state = clients[0].get(reverse("liveclassroom:api-v1-state", args=[session.pk]), {"channel": "participants"}).json()
    assert state["aggregate"]["submission_count"] == 100
    assert state["my_submission"]["answer"] == {"text": "observation-0"}
    print(f"100 students, 200 HTTP submissions including retries: {monotonic() - started:.2f}s")
