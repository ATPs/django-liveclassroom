import json
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.importers import import_markdown_flow
from liveclassroom.models import ActivityDefinition, Course, CourseMembership, Flow, FlowItem, FlowStep
from liveclassroom.services.classroom import (
    ClassroomError,
    create_activity_definition,
    create_instant_session,
    launch_item,
    start_session,
)
from liveclassroom.services.flows import (
    add_flow_step,
    can_edit_flow,
    create_flow,
    duplicate_flow,
    remove_flow_step,
    reorder_flow_steps,
    save_session_as_flow,
    update_flow,
)


def post_json(client, url, payload=None, **headers):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json", **headers)


def patch_json(client, url, payload=None, **headers):
    return client.patch(url, data=json.dumps(payload or {}), content_type="application/json", **headers)


def put_json(client, url, payload=None, **headers):
    return client.put(url, data=json.dumps(payload or {}), content_type="application/json", **headers)


def delete_json(client, url, payload=None, **headers):
    return client.delete(url, data=json.dumps(payload or {}), content_type="application/json", **headers)


@pytest.fixture
def teacher(db):
    return get_user_model().objects.create_user(username="teacher1")


@pytest.fixture
def other_teacher(db):
    return get_user_model().objects.create_user(username="teacher2")


@pytest.mark.django_db
def test_create_and_update_flow_service(teacher, other_teacher):
    flow = create_flow(title="Intro to Biology", creator=teacher, description="Basics")
    assert flow.title == "Intro to Biology"
    assert flow.slug == "intro-to-biology"
    assert flow.description == "Basics"
    assert can_edit_flow(teacher, flow) is True
    assert can_edit_flow(other_teacher, flow) is False

    updated = update_flow(flow=flow, actor=teacher, title="Advanced Biology", description="Updated")
    assert updated.title == "Advanced Biology"
    assert updated.description == "Updated"

    with pytest.raises(ClassroomError, match="permission"):
        update_flow(flow=flow, actor=other_teacher, title="Hacked")


@pytest.mark.django_db
def test_add_reorder_remove_flow_steps(teacher):
    flow = create_flow(title="Test Steps Flow", creator=teacher)

    act1 = create_activity_definition(
        owner=teacher,
        title="Activity One",
        type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "A", "text": "Choice A"}, {"id": "B", "text": "Choice B"}]},
    )
    act2 = create_activity_definition(
        owner=teacher,
        title="Activity Two",
        type_key="liveclassroom.poll",
        definition={"options": [{"id": "A", "text": "Option 1"}, {"id": "B", "text": "Option 2"}]},
    )

    step1 = add_flow_step(flow=flow, actor=teacher, activity_definition=act1)
    step2 = add_flow_step(flow=flow, actor=teacher, activity_definition=act2)
    step3 = add_flow_step(
        flow=flow,
        actor=teacher,
        kind="markdown",
        title="Lecture Note",
        content={"markdown": "# Welcome to class"},
    )

    assert step1.position == 1
    assert step2.position == 2
    assert step3.position == 3
    assert flow.steps.count() == 3
    assert flow.items.count() == 3

    # Reorder steps: [3, 1, 2]
    reordered = reorder_flow_steps(flow=flow, actor=teacher, step_ids=[step3.id, step1.id, step2.id])
    assert [s.id for s in reordered] == [step3.id, step1.id, step2.id]
    assert [s.position for s in reordered] == [1, 2, 3]

    # Verify positions in DB
    step3.refresh_from_db()
    step1.refresh_from_db()
    step2.refresh_from_db()
    assert step3.position == 1
    assert step1.position == 2
    assert step2.position == 3

    # Remove the middle step (step1)
    remove_flow_step(flow=flow, actor=teacher, step_id=step1.id)
    assert flow.steps.count() == 2
    assert flow.items.count() == 2

    # Remaining steps should be re-indexed to 1 and 2
    step3.refresh_from_db()
    step2.refresh_from_db()
    assert step3.position == 1
    assert step2.position == 2


@pytest.mark.django_db
def test_duplicate_flow(teacher):
    flow = create_flow(title="Original Flow", creator=teacher)
    act = create_activity_definition(
        owner=teacher,
        title="Question",
        type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "A", "text": "Yes"}, {"id": "B", "text": "No"}]},
    )
    add_flow_step(flow=flow, actor=teacher, activity_definition=act)
    add_flow_step(flow=flow, actor=teacher, kind="markdown", title="Notes", content={"markdown": "# Notes"})

    duplicated = duplicate_flow(flow=flow, creator=teacher)
    assert duplicated.id != flow.id
    assert duplicated.title == "Original Flow (Copy)"
    assert duplicated.slug != flow.slug
    assert duplicated.steps.count() == 2
    assert duplicated.items.count() == 2

    orig_step_kinds = list(flow.steps.values_list("kind", flat=True))
    dup_step_kinds = list(duplicated.steps.values_list("kind", flat=True))
    assert orig_step_kinds == dup_step_kinds


@pytest.mark.django_db
def test_save_session_as_flow(teacher):
    session = create_instant_session(owner=teacher, title="Session to save")
    start_session(session=session, actor=teacher)

    act_def = create_activity_definition(
        owner=teacher,
        title="Live Poll",
        type_key="liveclassroom.poll",
        definition={"options": [{"id": "A", "text": "Option 1"}]},
    )
    launch_item(session=session, item=act_def, actor=teacher)

    flow = save_session_as_flow(session=session, creator=teacher, title="Saved Lesson Flow")
    assert flow.title == "Saved Lesson Flow"
    assert flow.steps.count() == 1
    step = flow.steps.first()
    assert step.position == 1
    assert step.activity_definition.title == "Live Poll"
    assert step.activity_definition.type_key == "liveclassroom.poll"


@pytest.mark.django_db
def test_flow_authoring_api_crud_and_auth(teacher, other_teacher):
    anon_client = Client()
    teacher_client = Client()
    teacher_client.force_login(teacher)
    other_client = Client()
    other_client.force_login(other_teacher)

    # 1. Unauthenticated request rejected
    assert anon_client.get(reverse("liveclassroom:api-v1-flows")).status_code == 401

    # 2. List flows
    res = teacher_client.get(reverse("liveclassroom:api-v1-flows"))
    assert res.status_code == 200
    assert res.json()["flows"] == []

    # 3. Create flow
    created = post_json(
        teacher_client,
        reverse("liveclassroom:api-v1-flows"),
        {"title": "Genetics 101", "description": "Introductory Genetics"},
    )
    assert created.status_code == 201
    flow_id = created.json()["id"]

    # 4. Other teacher cannot view private flow
    assert other_client.get(reverse("liveclassroom:api-v1-flow-detail", args=[flow_id])).status_code == 403

    # 5. Teacher views flow details
    details = teacher_client.get(reverse("liveclassroom:api-v1-flow-detail", args=[flow_id]))
    assert details.status_code == 200
    assert details.json()["title"] == "Genetics 101"
    assert details.json()["steps"] == []

    # 6. Update flow metadata
    patch_res = patch_json(
        teacher_client,
        reverse("liveclassroom:api-v1-flow-detail", args=[flow_id]),
        {"title": "Genetics 101 - Spring"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["title"] == "Genetics 101 - Spring"

    # 7. Add step with inline activity definition
    step1_res = post_json(
        teacher_client,
        reverse("liveclassroom:api-v1-flow-add-step", args=[flow_id]),
        {
            "activity_definition": {
                "title": "Mendel's Peas",
                "type_key": "liveclassroom.single_choice",
                "definition": {
                    "options": [{"id": "A", "text": "Smooth"}, {"id": "B", "text": "Wrinkled"}],
                    "answer": ["A"],
                },
            }
        },
    )
    assert step1_res.status_code == 201
    step1_id = step1_res.json()["id"]

    # 8. Add step with existing activity definition ID
    existing_def = create_activity_definition(
        owner=teacher,
        title="DNA Structure",
        type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "A", "text": "Double helix"}]},
    )
    step2_res = post_json(
        teacher_client,
        reverse("liveclassroom:api-v1-flow-add-step", args=[flow_id]),
        {"activity_definition_id": existing_def.id},
    )
    assert step2_res.status_code == 201
    step2_id = step2_res.json()["id"]

    # Verify 2 steps
    details = teacher_client.get(reverse("liveclassroom:api-v1-flow-detail", args=[flow_id]))
    assert len(details.json()["steps"]) == 2

    # 9. Reorder steps
    reorder_res = put_json(
        teacher_client,
        reverse("liveclassroom:api-v1-flow-reorder-steps", args=[flow_id]),
        {"step_ids": [step2_id, step1_id]},
    )
    assert reorder_res.status_code == 200
    assert [s["id"] for s in reorder_res.json()["steps"]] == [step2_id, step1_id]

    # 10. Duplicate flow
    dup_res = post_json(
        teacher_client,
        reverse("liveclassroom:api-v1-flow-duplicate", args=[flow_id]),
        {"title": "Duplicated Genetics"},
    )
    assert dup_res.status_code == 201
    assert dup_res.json()["title"] == "Duplicated Genetics"
    assert len(dup_res.json()["steps"]) == 2

    # 11. Delete step
    del_res = delete_json(
        teacher_client,
        reverse("liveclassroom:api-v1-flow-delete-step", args=[flow_id, step1_id]),
    )
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    details_after_del = teacher_client.get(reverse("liveclassroom:api-v1-flow-detail", args=[flow_id]))
    assert len(details_after_del.json()["steps"]) == 1


@pytest.mark.django_db
def test_flow_authoring_api_idempotency(teacher):
    client = Client()
    client.force_login(teacher)

    payload = {"title": "Idempotent Flow", "description": "Desc"}
    first = post_json(
        client,
        reverse("liveclassroom:api-v1-flows"),
        payload,
        HTTP_IDEMPOTENCY_KEY="flow-create-unique-key",
    )
    assert first.status_code == 201
    first_id = first.json()["id"]

    # Replaying with exact same key and payload should return the exact same response
    replay = post_json(
        client,
        reverse("liveclassroom:api-v1-flows"),
        payload,
        HTTP_IDEMPOTENCY_KEY="flow-create-unique-key",
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first_id
    assert Flow.objects.filter(title="Idempotent Flow").count() == 1


@pytest.mark.django_db
def test_save_session_flow_api(teacher, other_teacher):
    session = create_instant_session(owner=teacher, title="Session to save via API")
    start_session(session=session, actor=teacher)
    act = create_activity_definition(
        owner=teacher,
        title="Live Question",
        type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "A", "text": "True"}, {"id": "B", "text": "False"}]},
    )
    launch_item(session=session, item=act, actor=teacher)

    teacher_client = Client()
    teacher_client.force_login(teacher)
    other_client = Client()
    other_client.force_login(other_teacher)

    # Unauthorized teacher cannot save session as flow
    assert (
        other_client.post(
            reverse("liveclassroom:api-v1-session-save-flow", args=[session.id]),
            data=json.dumps({"title": "Saved Flow"}),
            content_type="application/json",
        ).status_code
        == 403
    )

    # Authorized teacher can save session as flow
    res = post_json(
        teacher_client,
        reverse("liveclassroom:api-v1-session-save-flow", args=[session.id]),
        {"title": "Saved Session Flow"},
    )
    assert res.status_code == 201
    assert res.json()["title"] == "Saved Session Flow"
    assert len(res.json()["steps"]) == 1
    assert res.json()["steps"][0]["activity_definition"]["title"] == "Live Question"


@pytest.mark.django_db
def test_markdown_importer_creates_flow_step_and_activity_definition():
    user = get_user_model().objects.create_user(username="md-teacher")
    course = Course.objects.create(title="Biology Course", slug="bio-course", created_by=user)

    markdown_source = """---
title: Genetics Flow
slug: genetics-flow
---
# Welcome
:::quiz
type: single_choice
question: What is DNA?
choices: ["Molecule", "Organism"]
answer: ["Molecule"]
:::
"""
    flow = import_markdown_flow(course=course, source=markdown_source, creator=user)
    assert flow.slug == "genetics-flow"

    # Verify FlowStep was created and linked to ActivityDefinition
    steps = list(flow.steps.all().order_by("position"))
    assert len(steps) == 2
    assert steps[0].kind == "markdown"
    assert steps[0].activity_definition is None
    assert steps[1].kind == "activity"
    assert steps[1].activity_definition is not None

    act_def = steps[1].activity_definition
    assert act_def.type_key == "liveclassroom.single_choice"
    assert act_def.title == "What is DNA?"

    # Verify FlowItem is also linked to the ActivityDefinition
    items = list(flow.items.all().order_by("position"))
    assert items[1].activity_definition_id == act_def.id
    assert items[1].question is not None
