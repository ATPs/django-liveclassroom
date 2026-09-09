"""Long-text activity validation and live submission contracts."""

import json

import pytest
from django.contrib.auth import get_user_model

from liveclassroom.models import SubmissionRevision
from liveclassroom.registry import activity_registry
from liveclassroom.services.classroom import (
    ClassroomError,
    create_activity_definition,
    create_instant_session,
    join_guest,
    launch_item,
    start_session,
    submit_answer,
)
from liveclassroom.services.exports import json_archive


def test_essay_definition_is_manual_and_has_a_bounded_default():
    essay = activity_registry.get("liveclassroom.essay")
    definition = essay.validate({"prompt": "  Explain the result.  "})

    assert definition == {"prompt": "Explain the result.", "max_length": 10000}
    assert "manual" in essay.capabilities
    assert essay.score({"text": "A considered answer."}, definition) == {}

    custom = essay.validate({"prompt": "Prompt", "max_length": 50000})
    assert custom["max_length"] == 50000
    for invalid in (True, 0, 50001, "10000"):
        with pytest.raises(ValueError, match="max_length"):
            essay.validate({"prompt": "Prompt", "max_length": invalid})


@pytest.mark.parametrize("key", [
    "answer",
    "correct_answer",
    "case_sensitive",
    "partial_credit",
    "tolerance",
    "auto_grade",
    "automatic_grading",
])
def test_essay_rejects_objective_grading_fields(key):
    with pytest.raises(ValueError, match="grading field"):
        activity_registry.get("liveclassroom.essay").validate({"prompt": "Prompt", key: None})


def test_essay_preserves_internal_and_outer_whitespace():
    essay = activity_registry.get("liveclassroom.essay")
    definition = essay.validate({"prompt": "Prompt", "max_length": 50})
    text = "  First line\n\n  indented second line  "
    normalized = essay.normalize({"text": text})

    assert normalized == {"text": text}
    assert essay.validate_answer(normalized, definition) == normalized
    with pytest.raises(ValueError, match="cannot be empty"):
        essay.normalize({"text": " \n\t "})
    with pytest.raises(ValueError, match="exceeds"):
        essay.validate_answer({"text": "x" * 51}, definition)


@pytest.mark.django_db
def test_essay_live_submission_revisions_remain_ungraded_and_exported():
    teacher = get_user_model().objects.create_user(username="essay-activity-teacher")
    session = create_instant_session(owner=teacher, title="Essay classroom")
    definition = create_activity_definition(
        owner=teacher,
        title="Explain",
        type_key="liveclassroom.essay",
        definition={"prompt": "Explain the observation."},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    participant = join_guest(session=session, display_name="Ada")
    first_text = "First line\n\nSecond line"
    first = submit_answer(activity=activity, participant=participant, answer={"text": first_text})
    second_text = "Updated answer\nwith line breaks"
    second = submit_answer(activity=activity, participant=participant, answer={"text": second_text})

    assert first.id == second.id
    assert second.answer == {"text": second_text}
    assert second.score is None
    assert second.is_correct is None
    revisions = list(SubmissionRevision.objects.filter(submission=second).order_by("revision"))
    assert [revision.answer for revision in revisions] == [{"text": first_text}, {"text": second_text}]
    archive = json.loads("".join(json_archive(session)))
    assert archive["responses"][0]["answer"] == {"text": second_text}
    assert [revision["answer"] for revision in archive["responses"][0]["revisions"]] == [
        {"text": first_text},
        {"text": second_text},
    ]


@pytest.mark.django_db
def test_essay_submit_rejects_empty_and_definition_limit():
    teacher = get_user_model().objects.create_user(username="essay-validation-teacher")
    session = create_instant_session(owner=teacher, title="Essay validation")
    definition = create_activity_definition(
        owner=teacher,
        title="Short essay",
        type_key="liveclassroom.essay",
        definition={"prompt": "Prompt", "max_length": 3},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    participant = join_guest(session=session, display_name="Lin")

    with pytest.raises(ClassroomError, match="cannot be empty"):
        submit_answer(activity=activity, participant=participant, answer={"text": "  "})
    with pytest.raises(ClassroomError, match="exceeds"):
        submit_answer(activity=activity, participant=participant, answer={"text": "four"})
