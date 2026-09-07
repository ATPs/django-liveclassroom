"""Teacher-facing cohort, sharing and creation contracts under a mount prefix."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from liveclassroom.models import Course, FlowShare, LiveSession
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.flows import add_flow_step, create_flow


def post(client, name, body, args=(), key=None):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return client.post(reverse(name, args=args), json.dumps(body), content_type="application/json", **headers)


@pytest.mark.django_db
def test_workspace_creates_cohort_and_resolves_defaults_without_linking_live_config(client):
    teacher = get_user_model().objects.create_user(username="workspace-teacher")
    client.force_login(teacher)
    created = post(client, "liveclassroom:api-v1-courses", {"title": "Group A"}, key="class-create")
    assert created.status_code == 201
    course_id = created.json()["id"]
    assert (
        post(client, "liveclassroom:api-v1-courses", {"title": "Group A"}, key="class-create").json() == created.json()
    )
    changed = post(
        client,
        "liveclassroom:api-v1-course-detail",
        {
            "defaults": {"access_mode": "both", "admission_mode": "waiting_room", "chat_enabled": True},
        },
        [course_id],
    )
    assert changed.status_code == 200
    first = post(
        client, "liveclassroom:api-v1-session-create", {"title": "First", "course_id": course_id}, key="session-create"
    )
    assert first.status_code == 201
    assert (
        post(
            client,
            "liveclassroom:api-v1-session-create",
            {"title": "First", "course_id": course_id},
            key="session-create",
        ).json()
        == first.json()
    )
    session = LiveSession.objects.get(pk=first.json()["id"])
    assert (session.access_mode, session.admission_mode, session.chat_enabled) == ("both", "waiting_room", True)
    post(client, "liveclassroom:api-v1-course-detail", {"defaults": {"chat_enabled": False}}, [course_id])
    session.refresh_from_db()
    assert session.chat_enabled is True
    assert session.channel_states.filter(current_activity__isnull=False).count() == 0
    assert session.events.filter(event_type="session.created").exists()
    assert client.get(reverse("liveclassroom:api-v1-workspace")).json()["sessions"][0]["id"] == session.pk


@pytest.mark.django_db
def test_shared_lesson_api_allows_creation_copy_and_blocks_source_writes(client):
    users = get_user_model()
    owner = users.objects.create_user(username="lesson-owner")
    colleague = users.objects.create_user(username="colleague")
    flow = create_flow(title="Reusable", creator=owner)
    definition = create_activity_definition(
        owner=owner, title="Prompt", type_key="liveclassroom.short_text", definition={"prompt": "What changed?"}
    )
    add_flow_step(flow=flow, actor=owner, activity_definition=definition)
    client.force_login(owner)
    assert post(client, "liveclassroom:api-v1-flow-shares", {"username": "colleague"}, [flow.pk]).status_code == 200
    client.force_login(colleague)
    listing = client.get(reverse("liveclassroom:api-v1-flows")).json()["flows"]
    assert listing[0]["shared"] and not listing[0]["can_edit"]
    assert client.get(reverse("liveclassroom:api-v1-flow-detail", args=[flow.pk])).status_code == 200
    denied = client.patch(
        reverse("liveclassroom:api-v1-flow-detail", args=[flow.pk]),
        json.dumps({"title": "Unauthorized"}),
        content_type="application/json",
    )
    assert denied.status_code == 403
    copy = post(client, "liveclassroom:api-v1-flow-duplicate", {"title": "My copy"}, [flow.pk])
    assert copy.status_code == 201
    created = post(client, "liveclassroom:api-v1-session-create", {"title": "My classroom", "flow_id": flow.pk})
    assert created.status_code == 201
    FlowShare.objects.filter(flow=flow, user=colleague).delete()
    assert client.get(reverse("liveclassroom:api-v1-flow-detail", args=[flow.pk])).status_code == 403
    assert client.get(reverse("liveclassroom:api-v1-session-plan", args=[created.json()["id"]])).status_code == 200
    assert client.get(reverse("liveclassroom:api-v1-flow-detail", args=[copy.json()["id"]])).status_code == 200


@pytest.mark.django_db
def test_roster_defaults_reject_guest_only_and_unauthorized_course(client):
    teacher = get_user_model().objects.create_user(username="roster-teacher")
    other = get_user_model().objects.create_user(username="roster-other")
    course = Course.objects.create(title="Roster", slug="roster", created_by=teacher)
    client.force_login(teacher)
    assert (
        post(
            client,
            "liveclassroom:api-v1-course-detail",
            {
                "defaults": {"access_mode": "guest", "admission_mode": "roster"},
            },
            [course.pk],
        ).status_code
        == 400
    )
    client.force_login(other)
    assert (
        post(client, "liveclassroom:api-v1-session-create", {"title": "Forbidden", "course_id": course.pk}).status_code
        == 400
    )
    assert not LiveSession.objects.exists()
