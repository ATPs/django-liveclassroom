"""Small, stable registry for third-party activity types."""

import math
import re
import string
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ActivityType:
    key: str
    validate_definition: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    normalize_submission: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    validate_submission: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None
    aggregate_submissions: Callable[..., dict[str, Any]] | None = None
    score_submission: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None
    export_submission: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)
    migrate_definition: Callable[[dict[str, Any], int], dict[str, Any]] | None = None
    frontend_manifest: dict[str, str] = field(default_factory=dict)

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

    def aggregate(
        self,
        submissions: Iterable[dict[str, Any]],
        definition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Aggregate normalized answers through the optional plugin callback."""
        if self.aggregate_submissions is None:
            return {"submission_count": sum(1 for _ in submissions)}
        try:
            return self.aggregate_submissions(submissions, definition=definition)
        except TypeError:
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
        if not activity_type.key:
            raise ValueError("Activity type key cannot be empty.")
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


VALID_MEDIA_TYPES: frozenset[str] = frozenset({"image", "video", "audio", "iframe"})
DEFAULT_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
        "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
        "between", "both", "but", "by", "could", "did", "do", "does", "doing", "down",
        "during", "each", "few", "for", "from", "further", "had", "has", "have",
        "having", "he", "her", "here", "hers", "herself", "him", "himself", "his",
        "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me",
        "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on",
        "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over",
        "own", "same", "she", "should", "so", "some", "such", "than", "that", "the",
        "their", "theirs", "them", "themselves", "then", "there", "these", "they",
        "this", "those", "through", "to", "too", "under", "until", "up", "very",
        "was", "we", "were", "what", "when", "where", "which", "while", "who",
        "whom", "why", "will", "with", "you", "your", "yours", "yourself",
        "yourselves",
    }
)


def _manifest(name: str) -> dict[str, str]:
    return {
        "editor": f"liveclassroom/editors/{name}.js",
        "student_renderer": f"liveclassroom/renderers/{name}.js",
        "display_renderer": f"liveclassroom/renderers/{name}.js",
        "analytics": f"liveclassroom/analytics/{name}.js",
    }


def _word_cloud_definition(definition: dict[str, Any]) -> dict[str, Any]:
    result = _text_definition(definition)
    max_length = result.get("max_length")
    if max_length is not None:
        if isinstance(max_length, bool):
            raise ValueError("max_length must be an integer.")
        try:
            max_length = int(max_length)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_length must be an integer.") from exc
        if max_length < 1:
            raise ValueError("max_length must be greater than zero.")
        result["max_length"] = max_length
    stop_words = result.get("stop_words")
    if stop_words is not None:
        if not isinstance(stop_words, (list, tuple, set)):
            raise ValueError("stop_words must be a list of strings.")
        normalized_stop_words: list[str] = []
        for word in stop_words:
            if not isinstance(word, str) or not word.strip():
                raise ValueError("Each stop word must be non-empty text.")
            normalized_stop_words.append(word.strip().lower())
        result["stop_words"] = normalized_stop_words
    return result


def _aggregate_word_cloud(
    answers: Iterable[dict[str, Any]],
    definition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stop_words = set(DEFAULT_STOP_WORDS)
    if definition and isinstance(definition.get("stop_words"), (list, tuple, set)):
        stop_words.update(str(w).strip().lower() for w in definition["stop_words"] if str(w).strip())

    word_counts: Counter[str] = Counter()
    raw_answers: list[str] = []

    for answer in answers:
        if not isinstance(answer, dict):
            continue
        text = answer.get("text", answer.get("value"))
        if not isinstance(text, str):
            continue
        stripped_text = text.strip()
        if not stripped_text:
            continue
        raw_answers.append(stripped_text)
        tokens = re.findall(r"\b\w+\b", stripped_text.lower())
        for token in tokens:
            cleaned = token.strip(string.punctuation + "_")
            if cleaned and cleaned not in stop_words:
                word_counts[cleaned] += 1

    return {
        "submission_count": len(raw_answers),
        "word_frequencies": dict(word_counts),
        "words": dict(word_counts),
        "raw_answers": raw_answers,
        "values": raw_answers,
    }


def _timer_definition(definition: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(definition)
    duration = result.get("duration_seconds")
    if duration is None:
        raise ValueError("duration_seconds is required.")
    if isinstance(duration, bool):
        raise ValueError("duration_seconds must be a positive number.")
    try:
        duration = float(duration)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration_seconds must be a positive number.") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration_seconds must be a positive number.")
    result["duration_seconds"] = int(duration) if duration.is_integer() else duration

    label = result.get("label")
    if label is not None:
        if not isinstance(label, str):
            raise ValueError("label must be text.")
        result["label"] = label.strip()

    auto_start = result.get("auto_start")
    if auto_start is not None:
        if not isinstance(auto_start, bool):
            raise ValueError("auto_start must be a boolean.")
        result["auto_start"] = auto_start
    return result


def _markdown_definition(definition: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(definition)
    markdown = result.get("markdown")
    if markdown is None or not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("markdown content is required.")
    result["markdown"] = markdown.strip()

    title = result.get("title")
    if title is not None:
        if not isinstance(title, str):
            raise ValueError("title must be text.")
        result["title"] = title.strip()
    return result


_MEDIA_URL_SCHEMES = frozenset({"http", "https"})
_MEDIA_EXTENSIONS = {
    "image": (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"),
    "video": (".mp4", ".webm"),
    "audio": (".mp3", ".ogg", ".wav"),
}


def _infer_media_type(url: str) -> str:
    """Mirror the frontend's URL-extension inference for server-side enforcement."""
    path = urlsplit(url).path.lower()
    for media_type, extensions in _MEDIA_EXTENSIONS.items():
        if any(path.endswith(extension) for extension in extensions):
            return media_type
    return "iframe"


def _validate_media_url(url: str) -> str:
    """Canonicalize a media URL, rejecting executable or credential-bearing forms."""
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        raise ValueError("url contains control characters.")
    parsed = urlsplit(url)
    if parsed.scheme:
        if parsed.scheme.lower() not in _MEDIA_URL_SCHEMES:
            raise ValueError("url must use http or https.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("url must not contain credentials.")
    elif not url.startswith("/"):
        raise ValueError("relative url must start with '/'.")
    return url


def _media_definition(definition: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(definition)
    url = result.get("url")
    if url is None or not isinstance(url, str) or not url.strip():
        raise ValueError("url is required.")
    url = _validate_media_url(url.strip())
    result["url"] = url

    media_type = result.get("media_type")
    if media_type is None:
        media_type = _infer_media_type(url)
    if not isinstance(media_type, str) or media_type.strip().lower() not in VALID_MEDIA_TYPES:
        raise ValueError(f"media_type must be one of {sorted(VALID_MEDIA_TYPES)}.")
    media_type = media_type.strip().lower()
    if media_type == "iframe":
        from liveclassroom.conf import setting

        if not setting("ALLOW_IFRAME"):
            raise ValueError("Embedding ordinary iframes is disabled by the host.")
    result["media_type"] = media_type

    caption = result.get("caption")
    if caption is not None:
        if not isinstance(caption, str):
            raise ValueError("caption must be text.")
        result["caption"] = caption.strip()
    return result


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
        frontend_manifest=_manifest("single_choice"),
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
        frontend_manifest=_manifest("multiple_choice"),
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
        frontend_manifest=_manifest("true_false"),
    ),
    ActivityType(
        "liveclassroom.poll",
        validate_definition=_choice_definition,
        normalize_submission=_normalize_choice,
        validate_submission=_validate_single_choice,
        aggregate_submissions=_aggregate,
        export_submission=_plain_export,
        capabilities=frozenset({"choices", "aggregate"}),
        frontend_manifest=_manifest("poll"),
    ),
    ActivityType(
        "liveclassroom.short_text",
        validate_definition=_text_definition,
        normalize_submission=_normalize_text,
        validate_submission=_validate_text,
        aggregate_submissions=_aggregate,
        export_submission=_plain_export,
        capabilities=frozenset({"text", "aggregate"}),
        frontend_manifest=_manifest("short_text"),
    ),
    ActivityType(
        "liveclassroom.numeric",
        validate_definition=_numeric_definition,
        normalize_submission=_normalize_numeric,
        validate_submission=_validate_numeric,
        aggregate_submissions=_aggregate,
        export_submission=_plain_export,
        capabilities=frozenset({"numeric", "aggregate"}),
        frontend_manifest=_manifest("numeric"),
    ),
    ActivityType(
        "liveclassroom.rating",
        validate_definition=_numeric_definition,
        normalize_submission=_normalize_rating,
        validate_submission=_validate_rating,
        aggregate_submissions=_aggregate,
        export_submission=_plain_export,
        capabilities=frozenset({"rating", "aggregate"}),
        frontend_manifest=_manifest("rating"),
    ),
    ActivityType(
        "liveclassroom.ranking",
        validate_definition=_choice_definition,
        normalize_submission=_normalize_ranking,
        validate_submission=_validate_ranking,
        aggregate_submissions=_aggregate,
        export_submission=_plain_export,
        capabilities=frozenset({"ranking", "aggregate"}),
        frontend_manifest=_manifest("ranking"),
    ),
    ActivityType(
        "liveclassroom.word_cloud",
        validate_definition=_word_cloud_definition,
        normalize_submission=_normalize_text,
        validate_submission=_validate_text,
        aggregate_submissions=_aggregate_word_cloud,
        export_submission=_plain_export,
        capabilities=frozenset({"text", "aggregate"}),
        frontend_manifest=_manifest("word_cloud"),
    ),
    ActivityType(
        "liveclassroom.markdown",
        validate_definition=_markdown_definition,
        export_submission=_plain_export,
        capabilities=frozenset({"content"}),
        frontend_manifest=_manifest("markdown"),
    ),
    ActivityType(
        "liveclassroom.media",
        validate_definition=_media_definition,
        export_submission=_plain_export,
        capabilities=frozenset({"content"}),
        frontend_manifest=_manifest("media"),
    ),
    ActivityType(
        "liveclassroom.timer",
        validate_definition=_timer_definition,
        export_submission=_plain_export,
        capabilities=frozenset({"timed"}),
        frontend_manifest=_manifest("timer"),
    ),
    ActivityType(
        "liveclassroom.question",
        normalize_submission=_copy_definition,
        validate_submission=_validate_single_choice,
        aggregate_submissions=_aggregate,
        score_submission=_score_choice,
        export_submission=_plain_export,
        capabilities=frozenset({"legacy", "aggregate", "correctness"}),
        frontend_manifest=_manifest("question"),
    ),
):
    activity_registry.register(_activity_type)


def register_activity_type(activity_type: ActivityType, *, replace: bool = False) -> ActivityType:
    return activity_registry.register(activity_type, replace=replace)
