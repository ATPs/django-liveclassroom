"""Registry integration tests for deterministic objective grading."""

from copy import deepcopy

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

OPTIONS = [{"id": "A", "text": "Alpha"}, {"id": "B", "text": "Beta"}, {"id": "C", "text": "Gamma"}]


@pytest.mark.parametrize(
    ("type_key", "definition", "normalized_key"),
    [
        ("liveclassroom.single_choice", {"options": OPTIONS, "answer": " A "}, "A"),
        ("liveclassroom.multiple_choice", {"options": OPTIONS, "correct_answer": [" B ", "A", "B"]}, ["B", "A"]),
        ("liveclassroom.true_false", {"answer": ["true"]}, ["true"]),
        ("liveclassroom.numeric", {"prompt": "Value?", "answer": " 0.30 ", "tolerance": "0.1"}, " 0.30 "),
        ("liveclassroom.short_text", {"prompt": "Name it", "answer": [" RNA ", "rna", "RNA"]}, ["RNA", "rna"]),
    ],
)
def test_registry_validates_grading_fields_without_mutating_input(type_key, definition, normalized_key):
    original = deepcopy(definition)
    normalized = activity_registry.get(type_key).validate(definition)
    supplied_key = "answer" if "answer" in definition else "correct_answer"

    assert definition == original
    assert normalized[supplied_key] == normalized_key
    assert {"correctness"} <= activity_registry.get(type_key).capabilities


@pytest.mark.parametrize(
    ("type_key", "definition"),
    [
        ("liveclassroom.single_choice", {"options": OPTIONS}),
        ("liveclassroom.multiple_choice", {"options": OPTIONS, "answer": []}),
        ("liveclassroom.true_false", {"correct_answer": " "}),
        ("liveclassroom.numeric", {"prompt": "Value?", "answer": None}),
        ("liveclassroom.short_text", {"prompt": "Name it", "answer": ""}),
    ],
)
def test_missing_answer_keys_leave_objective_types_ungraded(type_key, definition):
    activity_type = activity_registry.get(type_key)
    normalized = activity_type.validate(definition)
    assert activity_type.score({}, normalized) == {}


@pytest.mark.parametrize(
    ("type_key", "definition"),
    [
        ("liveclassroom.single_choice", {"options": OPTIONS, "answer": ["A", "B"]}),
        ("liveclassroom.single_choice", {"options": OPTIONS, "answer": "Z"}),
        ("liveclassroom.single_choice", {"options": OPTIONS, "answer": "A", "partial_credit": False}),
        ("liveclassroom.multiple_choice", {"options": OPTIONS, "answer": ["A", 2]}),
        ("liveclassroom.multiple_choice", {"options": OPTIONS, "answer": ["A"], "partial_credit": 1}),
        ("liveclassroom.true_false", {"answer": "maybe"}),
        ("liveclassroom.numeric", {"prompt": "Value?", "answer": True}),
        ("liveclassroom.numeric", {"prompt": "Value?", "answer": float("nan")}),
        ("liveclassroom.numeric", {"prompt": "Value?", "answer": 1, "tolerance": -0.1}),
        ("liveclassroom.numeric", {"prompt": "Value?", "tolerance": 0.1}),
        ("liveclassroom.short_text", {"prompt": "Name it", "answer": ["RNA", ""]}),
        ("liveclassroom.short_text", {"prompt": "Name it", "answer": "RNA", "case_sensitive": 1}),
        ("liveclassroom.short_text", {"prompt": "Name it", "case_sensitive": False}),
    ],
)
def test_invalid_grading_configuration_is_rejected(type_key, definition):
    with pytest.raises(ValueError):
        activity_registry.get(type_key).validate(definition)


@pytest.mark.parametrize(
    ("type_key", "definition", "answer", "score", "correct"),
    [
        ("liveclassroom.single_choice", {"options": OPTIONS, "answer": "A"}, {"choice": "A"}, 1.0, True),
        ("liveclassroom.multiple_choice", {"options": OPTIONS, "answer": ["A", "B"]}, {"choices": ["A"]}, 0.0, False),
        (
            "liveclassroom.multiple_choice",
            {"options": OPTIONS, "answer": ["A", "B"], "partial_credit": True},
            {"choices": ["A"]},
            0.5,
            False,
        ),
        (
            "liveclassroom.multiple_choice",
            {"options": OPTIONS, "answer": ["A", "B"], "partial_credit": True},
            {"choices": ["A", "B", "C"]},
            0.5,
            False,
        ),
        (
            "liveclassroom.multiple_choice",
            {"options": OPTIONS, "answer": ["A", "B"], "partial_credit": True},
            {"choices": ["A", "C"]},
            0.0,
            False,
        ),
        ("liveclassroom.true_false", {"answer": "false"}, {"choice": "false"}, 1.0, True),
        ("liveclassroom.numeric", {"prompt": "Value?", "answer": 0.3, "tolerance": 0.1}, {"value": 0.2}, 1.0, True),
        ("liveclassroom.numeric", {"prompt": "Value?", "answer": 10, "tolerance": 0.1}, {"value": 10.11}, 0.0, False),
        ("liveclassroom.short_text", {"prompt": "Name it", "answer": "RNA"}, {"text": " rNa "}, 1.0, True),
        (
            "liveclassroom.short_text",
            {"prompt": "Name it", "answer": "RNA", "case_sensitive": True},
            {"text": "rna"},
            0.0,
            False,
        ),
    ],
)
def test_registry_scores_objective_answers(type_key, definition, answer, score, correct):
    activity_type = activity_registry.get(type_key)
    normalized_definition = activity_type.validate(definition)
    normalized_answer = activity_type.validate_answer(activity_type.normalize(answer), normalized_definition)
    assert activity_type.score(normalized_answer, normalized_definition) == {"score": score, "is_correct": correct}


@pytest.mark.django_db
def test_live_submission_persists_score_and_ungraded_nulls():
    teacher = get_user_model().objects.create_user(username="grading-adapter-teacher")
    session = create_instant_session(owner=teacher, title="Objective grading")
    start_session(session=session, actor=teacher)
    participant = join_guest(session=session, display_name="Ada")
    definition = create_activity_definition(
        owner=teacher,
        title="Numeric objective",
        type_key="liveclassroom.numeric",
        definition={"prompt": "Value?", "answer": 5, "tolerance": 0.5},
    )
    activity = launch_item(session=session, item=definition, actor=teacher)

    submission = submit_answer(activity=activity, participant=participant, answer={"value": 5.2})
    revision = SubmissionRevision.objects.get(submission=submission)
    assert (submission.score, submission.is_correct) == (1.0, True)
    assert (revision.score, revision.is_correct) == (1.0, True)

    second_session = create_instant_session(owner=teacher, title="Ungraded objective")
    start_session(session=second_session, actor=teacher)
    second_participant = join_guest(session=second_session, display_name="Lin")
    ungraded = create_activity_definition(
        owner=teacher,
        title="Ungraded text",
        type_key="liveclassroom.short_text",
        definition={"prompt": "Reflection"},
    )
    ungraded_activity = launch_item(session=second_session, item=ungraded, actor=teacher)
    ungraded_submission = submit_answer(
        activity=ungraded_activity,
        participant=second_participant,
        answer={"text": "Any response"},
    )
    assert ungraded_submission.score is None and ungraded_submission.is_correct is None
    assert ungraded_submission.current_revision.score is None
    assert ungraded_submission.current_revision.is_correct is None


@pytest.mark.django_db
def test_unknown_choice_is_rejected_before_scoring():
    teacher = get_user_model().objects.create_user(username="grading-choice-teacher")
    session = create_instant_session(owner=teacher, title="Choice validation")
    definition = create_activity_definition(
        owner=teacher,
        title="Choice objective",
        type_key="liveclassroom.single_choice",
        definition={"options": OPTIONS, "answer": "A"},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    participant = join_guest(session=session, display_name="Ada")

    with pytest.raises(ClassroomError, match="not part of this activity"):
        submit_answer(activity=activity, participant=participant, answer={"choice": "Z"})
