"""Small, stable registry for third-party activity types."""

import math
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActivityType:
    key: str
    validate_definition: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    normalize_submission: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    validate_submission: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None
    aggregate_submissions: Callable[[Iterable[dict[str, Any]]], dict[str, Any]] | None = None
    score_submission: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None
    export_submission: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)
    migrate_definition: Callable[[dict[str, Any], int], dict[str, Any]] | None = None

    def validate(self, definition: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(definition, dict):
            raise ValueError("An activity definition must be an object.")
        return self.validate_definition(definition) if self.validate_definition else definition

    def normalize(self, submission: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(submission, dict):
            raise ValueError("A submission must be an object.")
        return self.normalize_submission(submission) if self.normalize_submission else submission

    def migrate(self, definition: dict[str, Any], from_version: int) -> dict[str, Any]:
        """Upgrade an older definition through the plugin-owned migration hook."""
        if self.migrate_definition is None:
            return definition
        return self.migrate_definition(definition, from_version)

    def aggregate(self, submissions: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate normalized answers through the optional plugin callback."""
        if self.aggregate_submissions is None:
            return {"submission_count": sum(1 for _ in submissions)}
        return self.aggregate_submissions(submissions)

    def validate_answer(self, submission: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
        """Validate a normalized answer against the definition that is being run."""
        if self.validate_submission is None:
            return submission
        return self.validate_submission(submission, definition)

    def score(self, submission: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
        """Return optional plugin-owned scoring data."""
        if self.score_submission is None:
            return {}
        return self.score_submission(submission, definition)

    def export(self, submission: dict[str, Any]) -> dict[str, Any]:
        """Serialize one submission for an export without coupling core to a type."""
        return self.export_submission(submission) if self.export_submission else submission


class ActivityTypeRegistry:
    def __init__(self) -> None:
        self._types: dict[str, ActivityType] = {}

    def register(self, activity_type: ActivityType, *, replace: bool = False) -> ActivityType:
        if not activity_type.key or "." not in activity_type.key:
            raise ValueError("Activity type keys must be namespaced, for example liveclassroom.poll.")
        if activity_type.key in self._types and not replace:
            raise ValueError(f"Activity type {activity_type.key!r} is already registered.")
        self._types[activity_type.key] = activity_type
        return activity_type

    def get(self, key: str) -> ActivityType:
        try:
            return self._types[key]
        except KeyError as exc:
            raise KeyError(f"Unknown activity type: {key!r}.") from exc

    def all(self) -> tuple[ActivityType, ...]:
        return tuple(self._types.values())

    def unregister(self, key: str) -> None:
        self._types.pop(key, None)


activity_registry = ActivityTypeRegistry()


def _copy_definition(definition: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(definition, dict):
        raise ValueError("An activity definition must be an object.")
    return dict(definition)


def _options(definition: dict[str, Any], *, required: bool = True) -> list[dict[str, str]]:
    value = definition.get("options", definition.get("choices", []))
    if not isinstance(value, list):
        raise ValueError("Activity options must be a list.")
    if required and len(value) < 1:
        raise ValueError("Choice activities require at least one option.")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, option in enumerate(value):
        if isinstance(option, str):
            option = {"id": chr(ord("A") + index), "text": option}
        if not isinstance(option, dict):
            raise ValueError("Each option must be text or an {id, text} object.")
        option_id = str(option.get("id", "")).strip()
        text = str(option.get("text", "")).strip()
        if not option_id or not text or option_id in seen:
            raise ValueError("Each option needs a unique id and non-empty text.")
        seen.add(option_id)
        normalized.append({"id": option_id, "text": text})
    return normalized


def _choice_definition(definition: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(definition)
    result["options"] = _options(result)
    return result


def _true_false_definition(definition: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(definition)
    result["options"] = [{"id": "true", "text": "True"}, {"id": "false", "text": "False"}]
    return result


def _text_definition(definition: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(definition)
    prompt = result.get("prompt", result.get("stem_markdown"))
    if prompt is not None:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("An activity prompt must be non-empty text.")
        result["prompt"] = prompt.strip()
    return result


def _numeric_definition(definition: dict[str, Any]) -> dict[str, Any]:
    result = _text_definition(definition)
    for key in ("minimum", "maximum", "step"):
        if key in result:
            try:
                result[key] = float(result[key])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be numeric.") from exc
            if not math.isfinite(result[key]):
                raise ValueError(f"{key} must be finite.")
            if key == "step" and result[key] <= 0:
                raise ValueError("step must be greater than zero.")
    if result.get("minimum") is not None and result.get("maximum") is not None:
        if result["minimum"] > result["maximum"]:
            raise ValueError("minimum cannot be greater than maximum.")
    return result


def _normalize_choice(answer: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(answer)
    choice = result.get("choice")
    if not isinstance(choice, str) or not choice.strip():
        raise ValueError("A single-choice answer needs a choice.")
    result["choice"] = choice.strip()
    result.pop("choices", None)
    return result


def _option_ids(definition: dict[str, Any]) -> set[str]:
    """Extract option IDs from both modern and legacy definition shapes."""
    options = definition.get("options", definition.get("choices"))
    if options is None and isinstance(definition.get("data"), dict):
        options = definition["data"].get("options", definition["data"].get("choices"))
    if options is None and isinstance(definition.get("question"), dict):
        question = definition["question"]
        data = question.get("data") if isinstance(question.get("data"), dict) else {}
        options = data.get("options", data.get("choices"))
    if not isinstance(options, list):
        return set()
    result: set[str] = set()
    for index, option in enumerate(options):
        if isinstance(option, dict):
            option_id = option.get("id")
        else:
            option_id = chr(ord("A") + index) if isinstance(option, str) else None
        if option_id is not None:
            result.add(str(option_id))
    return result


def _validate_single_choice(answer: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    option_ids = _option_ids(definition)
    if option_ids and answer["choice"] not in option_ids:
        raise ValueError("The selected choice is not part of this activity.")
    return answer


def _validate_multiple_choice(answer: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    option_ids = _option_ids(definition)
    if option_ids and any(choice not in option_ids for choice in answer["choices"]):
        raise ValueError("One or more selected choices are not part of this activity.")
    return answer


def _normalize_multiple(answer: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(answer)
    choices = result.get("choices", result.get("choice"))
    if isinstance(choices, str):
        choices = [choices]
    if not isinstance(choices, list) or not choices or any(not isinstance(choice, str) for choice in choices):
        raise ValueError("A multiple-choice answer needs one or more choices.")
    result["choices"] = list(dict.fromkeys(choice.strip() for choice in choices if choice.strip()))
    if not result["choices"]:
        raise ValueError("A multiple-choice answer needs one or more choices.")
    result.pop("choice", None)
    return result


def _normalize_text(answer: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(answer)
    value = result.get("text", result.get("value"))
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A text answer cannot be empty.")
    if len(value.strip()) > 4000:
        raise ValueError("A text answer is too long.")
    result["text"] = value.strip()
    result.pop("value", None)
    return result


def _normalize_numeric(answer: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(answer)
    value = result.get("value")
    if isinstance(value, bool):
        raise ValueError("A numeric answer must be numeric.")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("A numeric answer must be numeric.") from exc
    if not math.isfinite(value):
        raise ValueError("A numeric answer must be finite.")
    result["value"] = value
    return result


def _validate_numeric(answer: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    value = answer["value"]
    minimum = definition.get("minimum")
    maximum = definition.get("maximum")
    if minimum is not None and value < float(minimum):
        raise ValueError("The numeric answer is below the allowed minimum.")
    if maximum is not None and value > float(maximum):
        raise ValueError("The numeric answer is above the allowed maximum.")
    step = definition.get("step")
    if step is not None:
        step = float(step)
        if step <= 0:
            raise ValueError("step must be greater than zero.")
        origin = float(minimum) if minimum is not None else 0.0
        if not math.isclose((value - origin) / step, round((value - origin) / step), abs_tol=1e-9):
            raise ValueError("The numeric answer does not match the configured step.")
    return answer


def _validate_rating(answer: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    rating_definition = {"minimum": definition.get("minimum", 1), "maximum": definition.get("maximum", 5)}
    rating_definition.update({key: definition[key] for key in ("step",) if key in definition})
    _validate_numeric({"value": answer["rating"]}, rating_definition)
    return answer


def _validate_ranking(answer: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    option_ids = _option_ids(definition)
    if option_ids and any(choice not in option_ids for choice in answer["ranking"]):
        raise ValueError("One or more ranked choices are not part of this activity.")
    return answer


def _validate_text(answer: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    maximum = definition.get("max_length")
    if maximum is not None:
        try:
            maximum = int(maximum)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_length must be an integer.") from exc
        if maximum < 1 or len(answer["text"]) > maximum:
            raise ValueError("The text answer exceeds the configured maximum length.")
    return answer


def _normalize_ranking(answer: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(answer)
    ranking = result.get("ranking", result.get("order"))
    if not isinstance(ranking, list) or not ranking or any(not isinstance(value, str) for value in ranking):
        raise ValueError("A ranking answer needs an ordered list.")
    result["ranking"] = list(dict.fromkeys(value.strip() for value in ranking if value.strip()))
    if not result["ranking"]:
        raise ValueError("A ranking answer needs an ordered list.")
    result.pop("order", None)
    return result


def _normalize_rating(answer: dict[str, Any]) -> dict[str, Any]:
    result = _normalize_numeric(answer)
    result["rating"] = result.pop("value")
    return result


def _aggregate(answers: Iterable[dict[str, Any]]) -> dict[str, Any]:
    choices: Counter[str] = Counter()
    values: list[Any] = []
    count = 0
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        count += 1
        choice = answer.get("choice")
        selected = answer.get("choices")
        if isinstance(selected, list):
            choices.update(str(item) for item in selected if item)
        elif choice:
            choices[str(choice)] += 1
        elif "text" in answer:
            values.append(answer["text"])
        elif "value" in answer:
            values.append(answer["value"])
        elif "rating" in answer:
            values.append(answer["rating"])
        elif "ranking" in answer:
            values.append(answer["ranking"])
    result: dict[str, Any] = {"submission_count": count, "choices": dict(choices)}
    if values:
        result["values"] = values
    return result


def _score_choice(answer: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    expected = definition.get("answer", definition.get("correct_answer"))
    if expected is None and isinstance(definition.get("question"), dict):
        expected = definition["question"].get("answer")
    if expected is None:
        return {}
    if isinstance(expected, str):
        expected = [expected]
    if not isinstance(expected, list):
        return {}
    actual = answer.get("choices", answer.get("choice"))
    if isinstance(actual, str):
        actual = [actual]
    if not isinstance(actual, list):
        return {}
    correct = set(map(str, actual)) == set(map(str, expected))
    return {"is_correct": correct, "score": 1 if correct else 0}


def _plain_export(answer: dict[str, Any]) -> dict[str, Any]:
    return dict(answer)


for _activity_type in (
    ActivityType(
        "liveclassroom.single_choice",
        validate_definition=_choice_definition,
        normalize_submission=_normalize_choice,
        validate_submission=_validate_single_choice,
        aggregate_submissions=_aggregate,
        score_submission=_score_choice,
        export_submission=_plain_export,
        capabilities=frozenset({"choices", "correctness", "aggregate"}),
    ),
    ActivityType(
        "liveclassroom.multiple_choice",
        validate_definition=_choice_definition,
        normalize_submission=_normalize_multiple,
        validate_submission=_validate_multiple_choice,
        aggregate_submissions=_aggregate,
        score_submission=_score_choice,
        export_submission=_plain_export,
        capabilities=frozenset({"choices", "correctness", "aggregate"}),
    ),
    ActivityType(
        "liveclassroom.true_false",
        validate_definition=_true_false_definition,
        normalize_submission=_normalize_choice,
        validate_submission=_validate_single_choice,
        aggregate_submissions=_aggregate,
        score_submission=_score_choice,
        export_submission=_plain_export,
        capabilities=frozenset({"choices", "correctness", "aggregate"}),
    ),
    ActivityType(
        "liveclassroom.poll",
        validate_definition=_choice_definition,
        normalize_submission=_normalize_choice,
        validate_submission=_validate_single_choice,
        aggregate_submissions=_aggregate,
        export_submission=_plain_export,
        capabilities=frozenset({"choices", "aggregate"}),
    ),
    ActivityType(
        "liveclassroom.short_text",
        validate_definition=_text_definition,
        normalize_submission=_normalize_text,
        validate_submission=_validate_text,
        aggregate_submissions=_aggregate,
        export_submission=_plain_export,
        capabilities=frozenset({"text", "aggregate"}),
    ),
    ActivityType(
        "liveclassroom.numeric",
        validate_definition=_numeric_definition,
        normalize_submission=_normalize_numeric,
        validate_submission=_validate_numeric,
        aggregate_submissions=_aggregate,
        export_submission=_plain_export,
        capabilities=frozenset({"numeric", "aggregate"}),
    ),
    ActivityType(
        "liveclassroom.rating",
        validate_definition=_numeric_definition,
        normalize_submission=_normalize_rating,
        validate_submission=_validate_rating,
        aggregate_submissions=_aggregate,
        export_submission=_plain_export,
        capabilities=frozenset({"rating", "aggregate"}),
    ),
    ActivityType(
        "liveclassroom.ranking",
        validate_definition=_choice_definition,
        normalize_submission=_normalize_ranking,
        validate_submission=_validate_ranking,
        aggregate_submissions=_aggregate,
        export_submission=_plain_export,
        capabilities=frozenset({"ranking", "aggregate"}),
    ),
    ActivityType(
        "liveclassroom.word_cloud",
        validate_definition=_text_definition,
        normalize_submission=_normalize_text,
        validate_submission=_validate_text,
        aggregate_submissions=_aggregate,
        export_submission=_plain_export,
        capabilities=frozenset({"text", "aggregate"}),
    ),
    ActivityType("liveclassroom.markdown", export_submission=_plain_export, capabilities=frozenset({"content"})),
    ActivityType("liveclassroom.media", export_submission=_plain_export, capabilities=frozenset({"content"})),
    ActivityType("liveclassroom.timer", export_submission=_plain_export, capabilities=frozenset({"timed"})),
    ActivityType(
        "liveclassroom.question",
        normalize_submission=_copy_definition,
        validate_submission=_validate_single_choice,
        aggregate_submissions=_aggregate,
        score_submission=_score_choice,
        export_submission=_plain_export,
        capabilities=frozenset({"legacy", "aggregate", "correctness"}),
    ),
):
    activity_registry.register(_activity_type)


def register_activity_type(activity_type: ActivityType, *, replace: bool = False) -> ActivityType:
    return activity_registry.register(activity_type, replace=replace)
