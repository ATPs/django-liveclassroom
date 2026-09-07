"""PostgreSQL-only races for lesson snapshot and comparison locking."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import Client
from django.urls import reverse

from liveclassroom.models import ActivityDefinition, LiveSession, Submission, SubmissionRevision
from liveclassroom.services.classroom import (
    ClassroomError,
    create_activity_definition,
    create_instant_session,
    join_authenticated,
    launch_item,
    publish_activity_to_channel,
    revise_activity_definition,
    start_session,
)
from liveclassroom.services.flows import add_flow_step, create_flow
from liveclassroom.services.plan_changes import apply_changes, compare_changes
from liveclassroom.services.plans import create_session, edit_plan_step


def _make_flow(teacher):
    flow = create_flow(title="Concurrent lesson", creator=teacher)
    definitions = []
    steps = []
    for position in (1, 2):
        definition = create_activity_definition(
            owner=teacher,
            title=f"Question {position}",
            type_key="liveclassroom.short_text",
            definition={"prompt": f"Before {position}"},
        )
        definitions.append(definition)
        steps.append(add_flow_step(flow=flow, actor=teacher, activity_definition=definition))
    return flow, definitions, steps


def _close_worker_connection():
    connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_revision_and_session_snapshot_race_is_consistent_on_postgres():
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL for concurrent plan locking")

    teacher = get_user_model().objects.create_user(username="postgres-plan-snapshot-teacher")
    flow, definitions, steps = _make_flow(teacher)
    before_revision_id = definitions[0].current_revision_id
    before_snapshot = {
        "schema_version": definitions[0].schema_version,
        "type_key": definitions[0].type_key,
        "kind": definitions[0].type_key.rsplit(".", 1)[-1],
        "title": definitions[0].title,
        "content": {"prompt": "Before 1"},
        "activity_definition_id": definitions[0].id,
        "activity_definition_revision_id": before_revision_id,
    }
    barrier = Barrier(2, timeout=15)

    def revise():
        _close_worker_connection()
        try:
            barrier.wait()
            definition = ActivityDefinition.objects.get(pk=definitions[0].pk)
            revision = revise_activity_definition(
                activity=definition,
                definition={"prompt": "After 1"},
                actor=get_user_model().objects.get(pk=teacher.pk),
            )
            return revision.id
        finally:
            _close_worker_connection()

    def create():
        _close_worker_connection()
        try:
            barrier.wait()
            session = create_session(
                owner=get_user_model().objects.get(pk=teacher.pk),
                title="Raced classroom",
                flow=flow,
            )
            return session.plan_steps.get(key=steps[0].key).snapshot
        finally:
            _close_worker_connection()

    with ThreadPoolExecutor(max_workers=2) as pool:
        revision_future = pool.submit(revise)
        snapshot_future = pool.submit(create)
        revision_id = revision_future.result(timeout=30)
        raced_snapshot = snapshot_future.result(timeout=30)

    after_snapshot = {
        **before_snapshot,
        "content": {"prompt": "After 1"},
        "activity_definition_revision_id": revision_id,
    }
    assert raced_snapshot in (before_snapshot, after_snapshot)


@pytest.mark.django_db(transaction=True)
def test_comparison_apply_race_rejects_stale_token_or_serializes_saveback():
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL for concurrent plan locking")

    teacher = get_user_model().objects.create_user(username="postgres-plan-compare-teacher")
    flow, definitions, steps = _make_flow(teacher)
    session = create_session(owner=teacher, title="Comparison classroom", flow=flow)
    local_step = session.plan_steps.get(key=steps[1].key)
    edit_plan_step(
        session=session,
        step=local_step,
        actor=teacher,
        snapshot={
            "schema_version": 1,
            "type_key": "liveclassroom.short_text",
            "kind": "short_text",
            "title": "Question 2",
            "content": {"prompt": "Local improvement"},
        },
    )
    comparison = compare_changes(session=session, actor=teacher, direction="to_lesson")
    barrier = Barrier(2, timeout=15)

    def apply():
        _close_worker_connection()
        try:
            barrier.wait()
            try:
                apply_changes(
                    session=session,
                    actor=get_user_model().objects.get(pk=teacher.pk),
                    direction="to_lesson",
                    token=comparison["token"],
                    keys=[str(steps[1].key)],
                )
            except ClassroomError as exc:
                return "rejected", str(exc)
            return "applied", None
        finally:
            _close_worker_connection()

    def revise_source():
        _close_worker_connection()
        try:
            barrier.wait()
            revise_activity_definition(
                activity=ActivityDefinition.objects.get(pk=definitions[0].pk),
                definition={"prompt": "Concurrent source edit"},
                actor=get_user_model().objects.get(pk=teacher.pk),
            )
            return "revised", None
        finally:
            _close_worker_connection()

    with ThreadPoolExecutor(max_workers=2) as pool:
        apply_future = pool.submit(apply)
        revision_future = pool.submit(revise_source)
        apply_result = apply_future.result(timeout=30)
        revision_result = revision_future.result(timeout=30)

    assert revision_result == ("revised", None)
    assert apply_result[0] in {"applied", "rejected"}
    if apply_result[0] == "rejected":
        assert "refresh and compare again" in apply_result[1]
        assert flow.steps.get(key=steps[1].key).activity_definition.definition == {"prompt": "Before 2"}
    else:
        assert flow.steps.get(key=steps[1].key).activity_definition.definition == {"prompt": "Local improvement"}
    assert flow.steps.get(key=steps[0].key).activity_definition.definition == {"prompt": "Concurrent source edit"}


@pytest.mark.django_db(transaction=True)
def test_same_submission_key_race_replays_one_committed_submission_on_postgres():
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL for concurrent idempotency locking")

    users = get_user_model()
    teacher = users.objects.create_user(username="postgres-submit-race-teacher")
    student = users.objects.create_user(username="postgres-submit-race-student")
    session = create_instant_session(
        owner=teacher,
        title="Submission race classroom",
        access_mode=LiveSession.AccessMode.AUTHENTICATED,
    )
    definition = create_activity_definition(
        owner=teacher,
        title="Race prompt",
        type_key="liveclassroom.short_text",
        definition={"prompt": "Answer once"},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    publish_activity_to_channel(session=session, activity=activity, channel="participants", actor=teacher)
    join_authenticated(session=session, user=student)

    authenticated = Client()
    authenticated.force_login(student)
    clients = [Client(), Client()]
    for client in clients:
        client.cookies.update(authenticated.cookies)

    url = reverse("liveclassroom:api-v1-submit", args=[activity.pk])
    payload = json.dumps(
        {"activity_revision_id": activity.current_revision_id, "answer": {"text": "one answer"}}
    )
    barrier = Barrier(2, timeout=15)

    def submit(client):
        connections.close_all()
        try:
            barrier.wait()
            response = client.post(
                url,
                data=payload,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="same-submission-key",
            )
            return response.status_code, response.json(), response.headers.get("Idempotent-Replay")
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, clients))

    assert [result[0] for result in results] == [201, 201]
    assert results[0][1] == results[1][1]
    assert "true" in {result[2] for result in results}
    assert Submission.objects.filter(activity=activity).count() == 1
    assert SubmissionRevision.objects.filter(submission__activity=activity).count() == 1
