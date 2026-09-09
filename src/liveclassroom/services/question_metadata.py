"""Validation for optional reusable-question metadata."""

from copy import deepcopy
from decimal import Decimal, DecimalException
from typing import Any

TOPIC_MAX_LENGTH = 200
TAG_MAX_LENGTH = 80
OBJECTIVE_MAX_LENGTH = 300
FEEDBACK_MAX_LENGTH = 1000
MAX_LIST_ITEMS = 50
DIFFICULTIES = frozenset({"easy", "medium", "hard"})
_KEYS = frozenset({"topic", "difficulty", "learning_objectives", "tags", "default_points", "feedback"})


def _text(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text.")
    result = value.strip()
    if len(result) > maximum:
        raise ValueError(f"{field} is too long.")
    return result


def _text_list(value: Any, *, field: str, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
        raise ValueError(f"{field} must be a list with at most {MAX_LIST_ITEMS} items.")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _text(item, field=field, maximum=maximum)
        if not cleaned:
            continue
        identity = cleaned.casefold()
        if identity not in seen:
            seen.add(identity)
            result.append(cleaned)
    return result


def _points(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("default_points must be a finite number.")
    try:
        points = Decimal(str(value).strip())
    except (DecimalException, ValueError) as exc:
        raise ValueError("default_points must be a finite number.") from exc
    if not points.is_finite() or points <= 0 or points > 1000:
        raise ValueError("default_points must be greater than zero and at most 1000.")
    return format(points.normalize(), "f")


def validate_question_metadata(value: Any) -> dict[str, Any]:
    """Return normalized metadata without mutating caller-owned values."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object.")
    value = deepcopy(value)
    unknown = set(value) - _KEYS
    if unknown:
        raise ValueError(f"Unsupported metadata fields: {', '.join(sorted(map(str, unknown)))}.")
    result: dict[str, Any] = {}
    if "topic" in value:
        topic = _text(value["topic"], field="topic", maximum=TOPIC_MAX_LENGTH)
        if topic:
            result["topic"] = topic
    if "difficulty" in value:
        difficulty = _text(value["difficulty"], field="difficulty", maximum=20).casefold()
        if difficulty and difficulty not in DIFFICULTIES:
            raise ValueError("difficulty must be easy, medium, or hard.")
        if difficulty:
            result["difficulty"] = difficulty
    if "learning_objectives" in value:
        objectives = _text_list(
            value["learning_objectives"], field="learning_objectives", maximum=OBJECTIVE_MAX_LENGTH
        )
        if objectives:
            result["learning_objectives"] = objectives
    if "tags" in value:
        tags = _text_list(value["tags"], field="tags", maximum=TAG_MAX_LENGTH)
        if tags:
            result["tags"] = tags
    if "default_points" in value:
        result["default_points"] = _points(value["default_points"])
    if "feedback" in value:
        feedback = value["feedback"]
        if not isinstance(feedback, dict) or set(feedback) - {"correct", "incorrect"}:
            raise ValueError("feedback accepts only correct and incorrect text.")
        normalized_feedback = {
            key: cleaned
            for key in ("correct", "incorrect")
            if key in feedback
            and (cleaned := _text(feedback[key], field=f"feedback.{key}", maximum=FEEDBACK_MAX_LENGTH))
        }
        if normalized_feedback:
            result["feedback"] = normalized_feedback
    return result
