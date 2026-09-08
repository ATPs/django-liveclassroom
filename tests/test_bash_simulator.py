"""Focused contracts for the browser-only declarative Bash simulator."""

from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from liveclassroom.models import LiveSession, SessionChannelState
from liveclassroom.registry import BASH_SIMULATOR_COMMANDS, activity_registry
from liveclassroom.services.classroom import (
    ClassroomError,
    create_activity_definition,
    create_instant_session,
    join_authenticated,
    launch_item,
    publish_activity_to_channel,
    start_session,
    submit_answer,
)


def simulator_definition(**overrides):
    definition = {
        "prompt": "Find the note and report its contents.",
        "filesystem": {"/work/note.txt": "hello from the virtual shell"},
        "initial_directory": "/",
        "completion": {"required_commands": ["cd", "cat"], "required_directory": "/work"},
        "max_transcript_entries": 10,
    }
    definition.update(overrides)
    return definition


def valid_answer():
    return {
        "completed": True,
        "transcript": [
            {"command": "cd /work", "output": "", "cwd": "/work"},
            {"command": "cat note.txt", "output": "hello from the virtual shell", "cwd": "/work"},
        ],
    }


def test_bash_simulator_definition_is_strict_and_declarative():
    activity_type = activity_registry.get("liveclassroom.bash_simulator")
    assert BASH_SIMULATOR_COMMANDS == {"pwd", "ls", "cd", "cat", "echo", "help", "clear", "reset"}
    normalized = activity_type.validate(simulator_definition())
    assert normalized["filesystem"] == {"/work/note.txt": "hello from the virtual shell"}
    assert normalized["initial_directory"] == "/"

    with pytest.raises(ValueError, match="Unsupported bash simulator definition fields"):
        activity_type.validate(simulator_definition(allow_commands=["pwd"]))
    with pytest.raises(ValueError, match="normalized"):
        activity_type.validate(simulator_definition(filesystem={"/work/../secret.txt": "nope"}))
    with pytest.raises(ValueError, match="must exist"):
        activity_type.validate(simulator_definition(initial_directory="/missing"))
    with pytest.raises(ValueError, match="required_commands"):
        activity_type.validate(simulator_definition(completion={"required_commands": ["rm"]}))


def test_ranking_rejects_duplicate_items_instead_of_silently_deduplicating():
    activity_type = activity_registry.get("liveclassroom.ranking")
    definition = activity_type.validate({"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]})
    with pytest.raises(ValueError, match="more than once"):
        activity_type.validate_answer(activity_type.normalize({"ranking": ["a", "a", "b"]}), definition)


def test_bash_simulator_submission_is_bounded_and_requires_explicit_completion():
    activity_type = activity_registry.get("liveclassroom.bash_simulator")
    definition = activity_type.validate(simulator_definition())
    assert activity_type.validate_answer(activity_type.normalize(valid_answer()), definition)["completed"] is True

    with pytest.raises(ValueError, match="explicit completion"):
        activity_type.normalize({"completed": False, "transcript": []})
    with pytest.raises(ValueError, match="only completed and transcript"):
        activity_type.normalize({"completed": True, "transcript": [], "score": 1})
    with pytest.raises(ValueError, match="unsupported command"):
        activity_type.normalize(
            {"completed": True, "transcript": [{"command": "rm -rf /", "output": "", "cwd": "/"}]}
        )
    with pytest.raises(ValueError, match="Completion is missing"):
        activity_type.validate_answer(
            activity_type.normalize({"completed": True, "transcript": [{"command": "pwd", "output": "/", "cwd": "/"}]}),
            definition,
        )
    with pytest.raises(ValueError, match="entry limit"):
        activity_type.validate_answer(
            activity_type.normalize(
                {
                    "completed": True,
                    "transcript": [
                        {"command": "pwd", "output": "/", "cwd": "/"},
                        {"command": "pwd", "output": "/", "cwd": "/"},
                    ],
                }
            ),
            activity_type.validate(simulator_definition(max_transcript_entries=1, completion={})),
        )


def test_bash_simulator_aggregate_and_export_do_not_leak_unbounded_state():
    activity_type = activity_registry.get("liveclassroom.bash_simulator")
    answer = valid_answer()
    assert activity_type.aggregate([answer, answer]) == {"submission_count": 2, "completed_count": 2}
    assert activity_type.aggregate_public([answer]) == {"submission_count": 1, "completed_count": 1}
    assert activity_type.export(answer) == answer


@pytest.mark.django_db
def test_bash_simulator_service_accepts_only_a_completed_transcript():
    teacher = get_user_model().objects.create_user(username="bash-simulator-teacher")
    student = get_user_model().objects.create_user(username="bash-simulator-student")
    session = create_instant_session(
        owner=teacher,
        title="Bash simulator",
        access_mode=LiveSession.AccessMode.BOTH,
    )
    activity_definition = create_activity_definition(
        owner=teacher,
        title="Find the note",
        type_key="liveclassroom.bash_simulator",
        definition=simulator_definition(),
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=activity_definition, actor=teacher)
    publish_activity_to_channel(
        session=session,
        activity=activity,
        channel=SessionChannelState.Channel.PARTICIPANTS,
        actor=teacher,
    )
    participant = join_authenticated(session=session, user=student)

    submission = submit_answer(
        activity=activity,
        participant=participant,
        answer=valid_answer(),
        actor=student,
        activity_revision_id=activity.current_revision_id,
        require_published=True,
    )
    assert submission.answer == valid_answer()

    with pytest.raises(ClassroomError, match="explicit completion"):
        submit_answer(
            activity=activity,
            participant=participant,
            answer={"completed": False, "transcript": valid_answer()["transcript"]},
            actor=student,
            activity_revision_id=activity.current_revision_id,
            require_published=True,
        )


def test_bash_simulator_renderer_is_browser_only_and_completion_explicit():
    renderer = Path("src/liveclassroom/static/liveclassroom/plugins/bash_simulator.v1.js").read_text(encoding="utf-8")
    assert 'const COMMANDS = ["pwd", "ls", "cd", "cat", "echo", "help", "clear", "reset"]' in renderer
    assert "currentContext.submit({ completed: true, transcript })" in renderer
    assert renderer.count("currentContext.submit(") == 1
    assert "submission.is_stale" in renderer
    assert "fetch(" not in renderer
    assert "subprocess" not in renderer
    assert "eval(" not in renderer
    assert "new Function" not in renderer
    assert "liveclassroom.bash.v1:" in renderer
    assert "sessionStorage" in renderer
    assert "lc-bash-simulator-checklist" in renderer
    assert "input.focus()" in renderer
    assert "inputLabel.htmlFor = input.id" in renderer
    assert "update(nextContext)" in renderer
    assert "Try commands" in renderer
    assert "Reset practice" in renderer
    assert 'if (name === "ls") return { cwd, ...listDirectory(' in renderer


def test_plugin_runtime_keeps_plugins_mounted_during_ordinary_state_polling():
    runtime = Path("frontend/src/plugin_runtime.ts").read_text(encoding="utf-8")
    activity_view = Path("frontend/src/activities/ActivityView.tsx").read_text(encoding="utf-8")
    assert "update?: (context: PluginRenderContext)" in runtime
    assert "Normal state polling must not recreate a plugin" in runtime
    assert "state?.state_version" not in activity_view
