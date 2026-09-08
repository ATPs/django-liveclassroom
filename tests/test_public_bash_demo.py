import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse

from liveclassroom.models import ClassroomAsset, DemoLesson, Flow, LiveSession
from liveclassroom.services.classroom import ClassroomError, join_authenticated, join_guest
from liveclassroom.services.flows import create_flow
from liveclassroom.services.permissions import can_teach, can_use_flow
from liveclassroom.services.presentation import presentation_title


def test_legacy_bash_machine_prefix_is_removed_only_for_recognized_demo_steps():
    assert presentation_title("[bash-demo:en:simulator] Guided Bash practice") == "Guided Bash practice"
    assert presentation_title("[bash-demo:en:custom] Keep this title") == "[bash-demo:en:custom] Keep this title"


@pytest.mark.django_db
def test_bash_demo_seed_is_idempotent_and_contains_the_full_course():
    call_command("seed_liveclassroom_bash_demo")
    call_command("seed_liveclassroom_bash_demo")

    demos = list(DemoLesson.objects.select_related("flow", "ready_session", "live_session", "ended_session"))
    assert {demo.language for demo in demos} == {"en", "zh-Hans"}
    assert all(demo.is_public for demo in demos)
    assert all(demo.flow.steps.count() == 14 for demo in demos)
    assert all(demo.ready_session.status == LiveSession.Status.DRAFT for demo in demos)
    assert all(demo.live_session.status == LiveSession.Status.LIVE for demo in demos)
    assert all(demo.ended_session.status == LiveSession.Status.ENDED for demo in demos)
    demo_sessions = [
        session
        for demo in demos
        for session in (demo.ready_session, demo.live_session, demo.ended_session)
    ]
    assert all(session.access_mode == LiveSession.AccessMode.AUTHENTICATED for session in demo_sessions)
    assert all(session.admission_mode == LiveSession.AdmissionMode.ROSTER for session in demo_sessions)
    assert all(session.chat_enabled is False for session in demo_sessions)
    assert all(demo.ended_session.participants.count() == 1 for demo in demos)
    assert all(demo.ended_session.activities.first().submissions.count() == 1 for demo in demos)
    assert all(
        not step.activity_definition.title.startswith("[bash-demo:")
        for demo in demos
        for step in demo.flow.steps.select_related("activity_definition")
    )
    assert {
        step.activity_definition.type_key for step in demos[0].flow.steps.select_related("activity_definition")
    } == {
        "liveclassroom.markdown",
        "liveclassroom.poll",
        "liveclassroom.word_cloud",
        "liveclassroom.media",
        "liveclassroom.file",
        "liveclassroom.bash_simulator",
        "liveclassroom.timer",
        "liveclassroom.true_false",
        "liveclassroom.multiple_choice",
        "liveclassroom.single_choice",
        "liveclassroom.numeric",
        "liveclassroom.rating",
        "liveclassroom.ranking",
        "liveclassroom.short_text",
    }
    chinese = next(demo for demo in demos if demo.language == "zh-Hans")
    steps = {step.position: step for step in chinese.flow.steps.select_related("activity_definition")}
    assert "显示当前目录" in steps[9].activity_definition.definition["options"][0]["text"]
    assert "查看当前位置" in steps[13].activity_definition.definition["options"][0]["text"]
    assert steps[4].activity_definition.definition["url"].endswith("bash-command-flow-zh-Hans.svg")

    with pytest.raises(ClassroomError, match="requires a Django account"):
        join_guest(session=demos[0].live_session, display_name="Unexpected visitor")
    visitor = get_user_model().objects.create_user(username="demo-uninvited-visitor")
    with pytest.raises(ClassroomError, match="not on this classroom's roster"):
        join_authenticated(session=demos[0].live_session, user=visitor)


@pytest.mark.django_db
def test_seed_refreshes_reusable_definition_through_a_new_revision_only():
    call_command("seed_liveclassroom_bash_demo", language="en")
    demo = DemoLesson.objects.get(language="en")
    activity = demo.flow.steps.get(position=2).activity_definition
    original_revisions = activity.revisions.count()
    activity.definition = {"prompt": "outdated", "options": [{"id": "old", "text": "Old"}]}
    activity.save(update_fields=["definition", "updated_at"])

    call_command("seed_liveclassroom_bash_demo", language="en")
    activity.refresh_from_db()
    assert activity.revisions.count() == original_revisions + 1
    assert activity.current_revision.payload == activity.definition
    call_command("seed_liveclassroom_bash_demo", language="en")
    assert activity.revisions.count() == original_revisions + 1


@pytest.mark.django_db
def test_seed_refreshes_an_existing_bash_cheat_sheet_asset():
    call_command("seed_liveclassroom_bash_demo", language="en")
    asset = ClassroomAsset.objects.get(original_name="bash-starter-cheatsheet-en.md")
    asset.sha256 = "0" * 64
    asset.byte_size = 1
    asset.save(update_fields=["sha256", "byte_size", "updated_at"])

    call_command("seed_liveclassroom_bash_demo", language="en")

    asset.refresh_from_db()
    assert asset.sha256 != "0" * 64
    assert asset.byte_size > 1
    with asset.content_file.open("rb") as content:
        assert b"Bash starter cheat sheet" in content.read()


@pytest.mark.django_db
def test_teacher_can_create_an_independent_classroom_from_public_demo_but_not_edit_it():
    call_command("seed_liveclassroom_bash_demo", language="en")
    teacher = get_user_model().objects.create_user(username="demo-teacher")
    demo = DemoLesson.objects.get(language="en")
    client = Client()
    client.force_login(teacher)

    listed = client.get(reverse("liveclassroom:api-v1-flows"))
    assert listed.status_code == 200
    public_flow = next(flow for flow in listed.json()["flows"] if flow["id"] == demo.flow_id)
    assert public_flow["demo"] is True
    assert public_flow["can_edit"] is False
    assert can_use_flow(teacher, demo.flow)

    detail = client.get(reverse("liveclassroom:api-v1-flow-detail", args=[demo.flow_id]))
    assert detail.status_code == 200
    assert detail.json()["demo"] is True
    assert detail.json()["can_edit"] is False

    denied = client.patch(
        reverse("liveclassroom:api-v1-flow-detail", args=[demo.flow_id]),
        data=json.dumps({"title": "Changed common demo"}),
        content_type="application/json",
    )
    assert denied.status_code == 403

    created = client.post(
        reverse("liveclassroom:api-v1-session-create"),
        data=json.dumps({"title": "My Bash class", "flow_id": demo.flow_id}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="demo-session-create",
    )
    assert created.status_code == 201
    classroom = LiveSession.objects.get(pk=created.json()["id"])
    assert classroom.teacher_id == teacher.id
    assert classroom.flow_id == demo.flow_id
    assert classroom.source_snapshot is not None
    assert classroom.plan_steps.count() == demo.flow.steps.count()


@pytest.mark.django_db
def test_teacher_authorizer_fails_closed_and_preserves_public_demo_for_authorized_teachers():
    call_command("seed_liveclassroom_bash_demo", language="en")
    teacher = get_user_model().objects.create_user(username="allowed")
    learner = get_user_model().objects.create_user(username="learner")

    def only_allowed(user):
        return user.get_username() == "allowed"

    with override_settings(LIVECLASSROOM={"TEACHER_AUTHORIZER": only_allowed}):
        demo = DemoLesson.objects.get(language="en")
        assert can_teach(teacher) is True
        assert can_teach(learner) is False
        assert can_use_flow(teacher, demo.flow) is True
        assert can_use_flow(learner, demo.flow) is False
        with pytest.raises(ClassroomError, match="authorized teacher"):
            create_flow(title="Not allowed", creator=learner)

    with override_settings(LIVECLASSROOM={"TEACHER_AUTHORIZER": lambda _user: "yes"}):
        assert can_teach(teacher) is False


@pytest.mark.django_db
def test_public_demo_sessions_are_marked_in_teacher_workspace():
    call_command("seed_liveclassroom_bash_demo", language="en")
    teacher = get_user_model().objects.create_user(username="workspace-demo-teacher")
    client = Client()
    client.force_login(teacher)

    response = client.get(reverse("liveclassroom:api-v1-workspace"))
    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert len([session for session in sessions if session["demo"]]) == 3


@pytest.mark.django_db
def test_authorized_teacher_can_preview_a_file_in_a_public_demo():
    call_command("seed_liveclassroom_bash_demo", language="en")
    teacher = get_user_model().objects.create_user(username="demo-file-teacher")
    asset = ClassroomAsset.objects.get(original_name="bash-starter-cheatsheet-en.md")
    client = Client()
    client.force_login(teacher)

    response = client.get(reverse("liveclassroom:api-v1-asset-content", args=[asset.public_id]))

    assert response.status_code == 200
    assert b"Bash starter cheat sheet" in b"".join(response.streaming_content)


@pytest.mark.django_db
def test_private_flows_stay_private_after_demo_seed():
    owner = get_user_model().objects.create_user(username="private-owner")
    other = get_user_model().objects.create_user(username="private-other")
    private_flow = Flow.objects.create(title="Private", slug="private", created_by=owner)
    call_command("seed_liveclassroom_bash_demo", language="en")
    assert can_use_flow(other, private_flow) is False


@pytest.mark.django_db
def test_host_teacher_authorizer_blocks_teacher_surfaces_and_workspace_api():
    user = get_user_model().objects.create_user(username="not-a-teacher")
    client = Client()
    client.force_login(user)

    with override_settings(LIVECLASSROOM={"TEACHER_AUTHORIZER": lambda _user: False}):
        assert client.get(reverse("liveclassroom:teacher-dashboard")).status_code == 403
        assert client.get(reverse("liveclassroom:flow-builder")).status_code == 403
        assert client.get(reverse("liveclassroom:api-v1-workspace")).status_code == 403
