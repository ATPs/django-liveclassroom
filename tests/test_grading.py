"""Tests for the isolated objective-grading contract."""

from copy import deepcopy

import pytest

from liveclassroom.services.grading import score_choice, score_numeric, score_short_text


@pytest.mark.parametrize(
    ("answer", "definition", "expected"),
    [
        ({"choice": "A"}, {"answer": ["A", "B"]}, {"score": 0.0, "is_correct": False}),
        ({"choices": ["A"]}, {"answer": ["A", "B"], "partial_credit": True}, {"score": 0.5, "is_correct": False}),
        ({"choices": ["A", "C"]}, {"answer": ["A", "B"], "partial_credit": True}, {"score": 0.0, "is_correct": False}),
        (
            {"choices": ["A", "B", "C"]},
            {"answer": ["A", "B"], "partial_credit": True},
            {"score": 0.5, "is_correct": False},
        ),
        (
            {"choices": ["B", " A ", "A"]},
            {"answer": ["A", "B"], "partial_credit": True},
            {"score": 1.0, "is_correct": True},
        ),
        ({"choices": []}, {"answer": "A"}, {"score": 0.0, "is_correct": False}),
        ({"choice": " A "}, {"answer": "A"}, {"score": 1.0, "is_correct": True}),
        ({"choices": ["B", "A"]}, {"answer": ["A", "B"]}, {"score": 1.0, "is_correct": True}),
        ({"choices": ["A", "C"]}, {"answer": ["A", "B"]}, {"score": 0.0, "is_correct": False}),
        ({"choices": ["A"], "choice": None}, {"answer": "A"}, {"score": 1.0, "is_correct": True}),
    ],
)
def test_score_choice(answer, definition, expected):
    assert score_choice(answer, definition) == expected


@pytest.mark.parametrize("empty", [{}, {"answer": None}, {"answer": []}, {"answer": "  "}])
@pytest.mark.parametrize("function, response", [(score_choice, {}), (score_numeric, {}), (score_short_text, {})])
def test_empty_expected_answer_is_ungraded_before_response_validation(function, response, empty):
    definition = {**empty, "partial_credit": "invalid", "case_sensitive": "invalid"}
    if empty:
        definition["correct_answer"] = "fallback"
    assert function(response, definition) == {}


@pytest.mark.parametrize("function, response, fallback", [
    (score_choice, {"choice": "A"}, "A"),
    (score_numeric, {"value": "1.0"}, "1"),
    (score_short_text, {"text": "RNA"}, "rna"),
])
def test_correct_answer_is_only_used_when_answer_key_is_absent(function, response, fallback):
    assert function(response, {"correct_answer": fallback}) == {"score": 1.0, "is_correct": True}


@pytest.mark.parametrize(
    ("answer", "definition", "expected"),
    [
        ({"value": 0.2}, {"answer": 0.3, "tolerance": 0.1}, {"score": 1.0, "is_correct": True}),
        ({"value": 10.11}, {"answer": 10, "tolerance": 0.1}, {"score": 0.0, "is_correct": False}),
        ({"value": "1.00"}, {"answer": "1", "tolerance": "0"}, {"score": 1.0, "is_correct": True}),
        ({"value": "1.101"}, {"answer": "1", "tolerance": "0.1"}, {"score": 0.0, "is_correct": False}),
    ],
)
def test_score_numeric(answer, definition, expected):
    assert score_numeric(answer, definition) == expected


@pytest.mark.parametrize(
    ("answer", "definition", "expected"),
    [
        ({"text": " rNa "}, {"answer": ["RNA", "ribonucleic acid"]}, {"score": 1.0, "is_correct": True}),
        ({"text": "rna"}, {"answer": "RNA", "case_sensitive": True}, {"score": 0.0, "is_correct": False}),
        ({"text": "STRASSE"}, {"answer": "Straße"}, {"score": 1.0, "is_correct": True}),
        ({"text": " 中文 "}, {"answer": ["中文"]}, {"score": 1.0, "is_correct": True}),
        ({"text": "a  b"}, {"answer": "a b"}, {"score": 0.0, "is_correct": False}),
        ({"text": "   "}, {"answer": "RNA"}, {"score": 0.0, "is_correct": False}),
    ],
)
def test_score_short_text(answer, definition, expected):
    assert score_short_text(answer, definition) == expected


@pytest.mark.parametrize(
    ("function", "answer", "definition"),
    [
        (score_choice, {"choices": "A"}, {"answer": "A"}),
        (score_choice, {"choice": " "}, {"answer": "A"}),
        (score_choice, {"choices": ["A", 1]}, {"answer": "A"}),
        (score_choice, {"choice": "A"}, {"answer": ["A", ""]}),
        (score_choice, {"choice": "A"}, {"answer": "A", "partial_credit": 1}),
        (score_numeric, {}, {"answer": 1}),
        (score_numeric, {"value": True}, {"answer": 1}),
        (score_numeric, {"value": "not a number"}, {"answer": 1}),
        (score_numeric, {"value": "NaN"}, {"answer": 1}),
        (score_numeric, {"value": "Infinity"}, {"answer": 1}),
        (score_numeric, {"value": 1}, {"answer": float("nan")}),
        (score_numeric, {"value": 1}, {"answer": False}),
        (score_numeric, {"value": 1}, {"answer": 1, "tolerance": -0.1}),
        (score_numeric, {"value": 1}, {"answer": 1, "tolerance": True}),
        (score_numeric, {"value": 1}, {"answer": 1, "tolerance": float("inf")}),
        (score_short_text, {}, {"answer": "RNA"}),
        (score_short_text, {"text": 1}, {"answer": "RNA"}),
        (score_short_text, {"text": "RNA"}, {"answer": ["RNA", "  "]}),
        (score_short_text, {"text": "RNA"}, {"answer": "RNA", "case_sensitive": None}),
    ],
)
def test_malformed_populated_values_raise_value_error(function, answer, definition):
    with pytest.raises(ValueError):
        function(answer, definition)


@pytest.mark.parametrize("function", [score_choice, score_numeric, score_short_text])
@pytest.mark.parametrize("answer, definition", [(None, {}), ({}, None), ([], {})])
def test_non_dictionary_arguments_raise_value_error(function, answer, definition):
    with pytest.raises(ValueError):
        function(answer, definition)


@pytest.mark.parametrize(
    ("function", "answer", "definition"),
    [
        (score_choice, {"choices": [" A ", "A"], "nested": {"ids": ["A"]}}, {"answer": [" A "], "nested": {"x": []}}),
        (score_numeric, {"value": "1.0", "nested": {"values": ["1"]}}, {"answer": "1", "nested": {"x": []}}),
        (score_short_text, {"text": " RNA ", "nested": {"values": ["RNA"]}}, {"answer": ["RNA"], "nested": {"x": []}}),
        (score_choice, {"choice": "A", "nested": {"x": []}}, {"answer": [""], "nested": {"x": []}}),
    ],
)
def test_grading_never_mutates_nested_inputs_and_is_repeatable(function, answer, definition):
    answer_before = deepcopy(answer)
    definition_before = deepcopy(definition)
    try:
        first = function(answer, definition)
        second = function(answer, definition)
        assert first == second
    except ValueError:
        with pytest.raises(ValueError):
            function(answer, definition)
    assert answer == answer_before
    assert definition == definition_before
