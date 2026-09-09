"""Pure, deterministic scoring helpers for objective question definitions."""

from decimal import Decimal, DecimalException
from typing import Any

_MISSING = object()


def _expected_value(definition: dict) -> Any:
    """Return the populated grading key, or ``_MISSING`` when grading is absent."""
    if "answer" in definition:
        value = definition["answer"]
    else:
        value = definition.get("correct_answer", _MISSING)
    if value is _MISSING or value is None:
        return _MISSING
    if isinstance(value, list) and not value:
        return _MISSING
    if isinstance(value, str) and not value.strip():
        return _MISSING
    return value


def _require_dicts(answer: dict, definition: dict) -> None:
    if not isinstance(answer, dict) or not isinstance(definition, dict):
        raise ValueError("Answer and definition must be dictionaries.")


def _identifier_set(value: Any, *, field: str) -> set[str]:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a string or list of strings.")
    result: set[str] = set()
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} entries must be nonblank strings.")
        result.add(item.strip())
    return result


def _choice_submission(answer: dict) -> set[str]:
    if "choices" in answer:
        value = answer["choices"]
        if not isinstance(value, list):
            raise ValueError("choices must be a list of strings.")
        return _identifier_set(value, field="choices")
    if "choice" not in answer or not isinstance(answer["choice"], str):
        raise ValueError("A choice or choices response is required.")
    return _identifier_set(answer["choice"], field="choice")


def _flag(definition: dict, name: str, *, default: bool) -> bool:
    value = definition.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean.")
    return value


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field} must be a finite number or numeric string.")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{field} must be a finite number or numeric string.")
    try:
        result = Decimal(str(value))
    except (DecimalException, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number or numeric string.") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite.")
    return result


def _result(correct: bool, score: float | None = None) -> dict:
    return {"score": float(correct) if score is None else score, "is_correct": correct}


def score_choice(answer: dict, definition: dict) -> dict:
    """Score exact or explicitly partial-credit matching of choice identifiers."""
    _require_dicts(answer, definition)
    expected = _expected_value(definition)
    if expected is _MISSING:
        return {}
    correct_ids = _identifier_set(expected, field="answer")
    partial_credit = _flag(definition, "partial_credit", default=False)
    submitted_ids = _choice_submission(answer)
    is_correct = submitted_ids == correct_ids
    if not partial_credit:
        return _result(is_correct)
    score = max(0.0, (len(submitted_ids & correct_ids) - len(submitted_ids - correct_ids)) / len(correct_ids))
    return _result(is_correct, score)


def score_numeric(answer: dict, definition: dict) -> dict:
    """Score a finite numeric response using an inclusive absolute tolerance."""
    _require_dicts(answer, definition)
    expected = _expected_value(definition)
    if expected is _MISSING:
        return {}
    expected_value = _decimal(expected, field="answer")
    if "value" not in answer:
        raise ValueError("A value response is required.")
    actual_value = _decimal(answer["value"], field="value")
    tolerance = _decimal(definition["tolerance"], field="tolerance") if "tolerance" in definition else Decimal(0)
    if tolerance < 0:
        raise ValueError("tolerance must be nonnegative.")
    return _result(abs(actual_value - expected_value) <= tolerance)


def score_short_text(answer: dict, definition: dict) -> dict:
    """Score an accepted short-text answer after explicit normalization only."""
    _require_dicts(answer, definition)
    expected = _expected_value(definition)
    if expected is _MISSING:
        return {}
    values = [expected] if isinstance(expected, str) else expected
    if not isinstance(values, list):
        raise ValueError("answer must be a string or list of strings.")
    if "text" not in answer or not isinstance(answer["text"], str):
        raise ValueError("A text response is required.")
    case_sensitive = _flag(definition, "case_sensitive", default=False)
    normalized_expected: set[str] = set()
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("answer entries must be nonblank strings.")
        normalized = item.strip()
        normalized_expected.add(normalized if case_sensitive else normalized.casefold())
    actual = answer["text"].strip()
    normalized_actual = actual if case_sensitive else actual.casefold()
    return _result(normalized_actual in normalized_expected)
