"""Small, stable registry for third-party activity types."""

import math
import posixpath
import re
import shlex
import string
import uuid
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
    aggregate_public_submissions: Callable[..., dict[str, Any]] | None = None
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

    def aggregate_public(
        self,
        submissions: Iterable[dict[str, Any]],
        definition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return an audience-safe aggregate owned by the activity plugin.

        A plugin without an explicit public aggregator exposes only its count.
        This keeps arbitrary private keys, nested answers, and moderation data
        out of participant and display state by default.
        """
        if self.aggregate_public_submissions is None:
            return {"submission_count": sum(1 for _ in submissions)}
        try:
            return self.aggregate_public_submissions(submissions, definition=definition)
        except TypeError:
            return self.aggregate_public_submissions(submissions)

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
    if option_ids and set(answer["ranking"]) != set(option_ids):
        raise ValueError("A ranking answer must include every option exactly once.")
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
    cleaned = [value.strip() for value in ranking]
    if not all(cleaned):
        raise ValueError("A ranking answer needs an ordered list.")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("A ranking answer must not contain the same choice more than once.")
    result["ranking"] = cleaned
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


def _aggregate_public_choices(answers: Iterable[dict[str, Any]], definition=None) -> dict[str, Any]:
    result = _aggregate(answers)
    result.pop("values", None)
    return result


def _aggregate_public_text(answers: Iterable[dict[str, Any]], definition=None) -> dict[str, Any]:
    return {"submission_count": sum(1 for answer in answers if isinstance(answer, dict))}


def _aggregate_public_numeric(answers: Iterable[dict[str, Any]], definition=None) -> dict[str, Any]:
    values: list[float] = []
    count = 0
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        count += 1
        value = answer.get("value", answer.get("rating"))
        if isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            values.append(number)
    result: dict[str, Any] = {"submission_count": count}
    if values:
        result["numeric_summary"] = {
            "minimum": min(values),
            "maximum": max(values),
            "average": sum(values) / len(values),
        }
    return result


def _aggregate_public_ranking(answers: Iterable[dict[str, Any]], definition=None) -> dict[str, Any]:
    positions: dict[str, Counter[int]] = {}
    count = 0
    for answer in answers:
        if not isinstance(answer, dict) or not isinstance(answer.get("ranking"), list):
            continue
        count += 1
        for index, value in enumerate(answer["ranking"], start=1):
            positions.setdefault(str(value), Counter())[index] += 1
    return {
        "submission_count": count,
        "ranking_positions": {
            value: {str(position): total for position, total in counts.items()}
            for value, counts in positions.items()
        },
    }


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


BASH_SIMULATOR_COMMANDS: frozenset[str] = frozenset(
    {"pwd", "ls", "cd", "cat", "echo", "help", "clear", "reset"}
)
BASH_SIMULATOR_MAX_FILES = 100
BASH_SIMULATOR_MAX_FILE_BYTES = 16_000
BASH_SIMULATOR_MAX_TRANSCRIPT_ENTRIES = 100
BASH_SIMULATOR_MAX_COMMAND_LENGTH = 240
BASH_SIMULATOR_MAX_OUTPUT_LENGTH = 4_000
BASH_SIMULATOR_MAX_PATH_LENGTH = 255

_BASH_DEFINITION_KEYS = frozenset(
    {"prompt", "filesystem", "initial_directory", "completion", "max_transcript_entries"}
)
_BASH_COMPLETION_KEYS = frozenset({"required_commands", "required_directory"})
_BASH_CONTROL_CHARACTERS = frozenset(chr(value) for value in range(0x20)) | {chr(0x7F)}


def _bash_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty absolute path.")
    value = value.strip()
    if (
        len(value) > BASH_SIMULATOR_MAX_PATH_LENGTH
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(character in _BASH_CONTROL_CHARACTERS for character in value)
    ):
        raise ValueError(f"{field} must be a safe absolute path.")
    normalized = posixpath.normpath(value)
    if normalized != value or normalized == "//" or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError(f"{field} must be normalized without '.' or '..' segments.")
    return normalized


def _bash_directories(filesystem: dict[str, str]) -> set[str]:
    directories = {"/"}
    for path in filesystem:
        parent = posixpath.dirname(path)
        while parent and parent != "/":
            directories.add(parent)
            parent = posixpath.dirname(parent)
    return directories


def _bash_definition(definition: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(definition)
    unknown = set(result) - _BASH_DEFINITION_KEYS
    if unknown:
        raise ValueError(f"Unsupported bash simulator definition fields: {', '.join(sorted(map(str, unknown)))}.")

    prompt = result.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("A bash simulator prompt must be non-empty text.")
    if len(prompt.strip()) > BASH_SIMULATOR_MAX_OUTPUT_LENGTH:
        raise ValueError("A bash simulator prompt is too long.")
    result["prompt"] = prompt.strip()

    if "filesystem" not in result:
        raise ValueError("filesystem is required.")
    raw_filesystem = result.get("filesystem", {})
    if not isinstance(raw_filesystem, dict):
        raise ValueError("filesystem must be an object mapping absolute paths to file text.")
    if len(raw_filesystem) > BASH_SIMULATOR_MAX_FILES:
        raise ValueError("filesystem has too many files.")
    filesystem: dict[str, str] = {}
    for raw_path, content in raw_filesystem.items():
        path = _bash_path(raw_path, field="filesystem path")
        if path == "/":
            raise ValueError("filesystem cannot define the root as a file.")
        if not isinstance(content, str):
            raise ValueError("filesystem file contents must be text.")
        if len(content.encode("utf-8")) > BASH_SIMULATOR_MAX_FILE_BYTES:
            raise ValueError("filesystem file contents are too large.")
        filesystem[path] = content
    if len(filesystem) != len(raw_filesystem):
        raise ValueError("filesystem paths must be unique after normalization.")
    if any(directory in filesystem for directory in _bash_directories(filesystem)):
        raise ValueError("A filesystem file cannot also be a directory.")
    result["filesystem"] = filesystem

    initial_directory = _bash_path(result.get("initial_directory", "/"), field="initial_directory")
    if initial_directory not in _bash_directories(filesystem):
        raise ValueError("initial_directory must exist in the virtual filesystem.")
    result["initial_directory"] = initial_directory

    completion = result.get("completion", {})
    if not isinstance(completion, dict):
        raise ValueError("completion must be an object.")
    unknown_completion = set(completion) - _BASH_COMPLETION_KEYS
    if unknown_completion:
        raise ValueError(
            f"Unsupported bash simulator completion fields: {', '.join(sorted(map(str, unknown_completion)))}."
        )
    normalized_completion: dict[str, Any] = {}
    required_commands = completion.get("required_commands", [])
    if not isinstance(required_commands, list) or any(
        not isinstance(command, str) or command not in BASH_SIMULATOR_COMMANDS for command in required_commands
    ):
        raise ValueError("completion.required_commands must contain only supported command names.")
    if len(required_commands) > len(BASH_SIMULATOR_COMMANDS) or len(set(required_commands)) != len(required_commands):
        raise ValueError("completion.required_commands must contain unique supported commands.")
    normalized_completion["required_commands"] = list(required_commands)
    if "required_directory" in completion:
        required_directory = _bash_path(completion["required_directory"], field="completion.required_directory")
        if required_directory not in _bash_directories(filesystem):
            raise ValueError("completion.required_directory must exist in the virtual filesystem.")
        normalized_completion["required_directory"] = required_directory
    result["completion"] = normalized_completion

    max_entries = result.get("max_transcript_entries", BASH_SIMULATOR_MAX_TRANSCRIPT_ENTRIES)
    if isinstance(max_entries, bool) or not isinstance(max_entries, int):
        raise ValueError("max_transcript_entries must be an integer.")
    if max_entries < 1 or max_entries > BASH_SIMULATOR_MAX_TRANSCRIPT_ENTRIES:
        raise ValueError("max_transcript_entries must be from 1 to 100.")
    result["max_transcript_entries"] = max_entries
    return result


def _bash_command_parts(command: str) -> list[str]:
    if (
        not isinstance(command, str)
        or not command.strip()
        or len(command) > BASH_SIMULATOR_MAX_COMMAND_LENGTH
        or any(character in _BASH_CONTROL_CHARACTERS for character in command)
        or any(character in command for character in ";&|<>$`\\")
    ):
        raise ValueError("Transcript commands must be one safe supported command per line.")
    try:
        parts = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ValueError("Transcript commands must use valid shell-style quoting.") from exc
    if not parts or parts[0] not in BASH_SIMULATOR_COMMANDS:
        raise ValueError("Transcript contains an unsupported command.")
    return parts


def _normalize_bash_submission(submission: dict[str, Any]) -> dict[str, Any]:
    result = _copy_definition(submission)
    if set(result) != {"completed", "transcript"}:
        raise ValueError("A bash simulator answer must contain only completed and transcript.")
    if result.get("completed") is not True:
        raise ValueError("A bash simulator answer requires explicit completion.")
    transcript = result.get("transcript")
    if (
        not isinstance(transcript, list)
        or not transcript
        or len(transcript) > BASH_SIMULATOR_MAX_TRANSCRIPT_ENTRIES
    ):
        raise ValueError("A bash simulator transcript must contain from 1 to 100 entries.")
    normalized: list[dict[str, str]] = []
    for entry in transcript:
        if not isinstance(entry, dict) or set(entry) != {"command", "output", "cwd"}:
            raise ValueError("Each bash simulator transcript entry needs command, output, and cwd.")
        command = entry["command"]
        _bash_command_parts(command)
        cwd = _bash_path(entry["cwd"], field="transcript cwd")
        output = entry["output"]
        if not isinstance(output, str) or len(output) > BASH_SIMULATOR_MAX_OUTPUT_LENGTH:
            raise ValueError("Transcript output must be text of at most 4000 characters.")
        if "\x00" in output:
            raise ValueError("Transcript output cannot contain NUL bytes.")
        normalized.append({"command": command.strip(), "output": output, "cwd": cwd})
    result["completed"] = True
    result["transcript"] = normalized
    return result


def _validate_bash_submission(submission: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    filesystem = definition.get("filesystem", {})
    directories = _bash_directories(filesystem)
    for entry in submission["transcript"]:
        if entry["cwd"] not in directories:
            raise ValueError("Transcript cwd must exist in the virtual filesystem.")
    completion = definition.get("completion", {})
    command_names = {_bash_command_parts(entry["command"])[0] for entry in submission["transcript"]}
    missing = set(completion.get("required_commands", [])) - command_names
    if missing:
        raise ValueError(f"Completion is missing required commands: {', '.join(sorted(missing))}.")
    required_directory = completion.get("required_directory")
    if required_directory is not None and (
        not submission["transcript"] or submission["transcript"][-1]["cwd"] != required_directory
    ):
        raise ValueError("Completion must finish in the required directory.")
    max_entries = definition.get("max_transcript_entries", BASH_SIMULATOR_MAX_TRANSCRIPT_ENTRIES)
    if len(submission["transcript"]) > max_entries:
        raise ValueError("The transcript exceeds this activity's entry limit.")
    return submission


def _aggregate_bash_submissions(answers: Iterable[dict[str, Any]], definition=None) -> dict[str, Any]:
    completed_count = 0
    submission_count = 0
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        submission_count += 1
        if answer.get("completed") is True:
            completed_count += 1
    return {"submission_count": submission_count, "completed_count": completed_count}


def _export_bash_submission(answer: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_bash_submission(answer)
    return {"completed": True, "transcript": normalized["transcript"]}


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
    """Return collectable versioned frontend modules for built-in activities.

    One module per surface keeps the public browser contract stable while the
    module receives the activity type key at runtime.  Third-party plugins may
    use their own collectable module paths.
    """
    return {
        "editor": "liveclassroom/plugins/editor.v1.js",
        "student_renderer": "liveclassroom/plugins/renderer.v1.js",
        "display_renderer": "liveclassroom/plugins/renderer.v1.js",
        "analytics": "liveclassroom/plugins/analytics.v1.js",
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


def _aggregate_public_word_cloud(
    answers: Iterable[dict[str, Any]],
    definition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _aggregate_word_cloud(answers, definition=definition)
    return {
        "submission_count": result["submission_count"],
        "word_frequencies": result["word_frequencies"],
        "words": result["words"],
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


_FILE_KINDS = frozenset({"markdown", "pdf", "pptx", "video"})


def _file_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Validate the portable reference to a privately served classroom asset."""
    result = _copy_definition(definition)
    asset_id = result.get("asset_id")
    if not isinstance(asset_id, str):
        raise ValueError("asset_id is required.")
    try:
        result["asset_id"] = str(uuid.UUID(asset_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("asset_id must be a UUID.") from exc
    file_kind = result.get("file_kind")
    if not isinstance(file_kind, str) or file_kind.strip().lower() not in _FILE_KINDS:
        raise ValueError(f"file_kind must be one of {sorted(_FILE_KINDS)}.")
    result["file_kind"] = file_kind.strip().lower()
    caption = result.get("caption")
    if caption is not None:
        if not isinstance(caption, str):
            raise ValueError("caption must be text.")
        result["caption"] = caption.strip()
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
    """Canonicalize a media URL, rejecting ambiguous or executable forms."""
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in url) or "\\" in url:
        raise ValueError("url contains control characters.")
    if "#" in url:
        raise ValueError("url must not contain a fragment.")
    if url.startswith("//"):
        raise ValueError("scheme-relative URLs are not allowed.")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise ValueError("url has an invalid host or port.") from exc
    if parsed.scheme:
        if parsed.scheme.lower() not in _MEDIA_URL_SCHEMES:
            raise ValueError("url must use http or https.")
        if not parsed.netloc or not hostname:
            raise ValueError("absolute url must include a host.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("url must not contain credentials.")
    elif parsed.netloc or not url.startswith("/"):
        raise ValueError("relative url must start with '/'.")
    return url


def _canonical_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if parsed.scheme.lower() not in _MEDIA_URL_SCHEMES or not parsed.netloc or not hostname:
        return None
    if parsed.username is not None or parsed.password is not None or parsed.path not in {"", "/"}:
        return None
    if parsed.query or parsed.fragment:
        return None
    hostname = hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme.lower()}://{hostname}{suffix}"


def _iframe_policy_allows(url: str) -> bool:
    """Apply the host's explicit iframe policy to one canonical URL."""
    from liveclassroom.conf import setting

    policy = setting("ALLOW_IFRAME")
    if policy is True:
        return True
    if callable(policy):
        try:
            return bool(policy(url))
        except (TypeError, ValueError):
            return False
    if isinstance(policy, (list, tuple, set, frozenset)):
        if url.startswith("/"):
            return True
        origin = _canonical_origin(url)
        return origin is not None and origin in {
            normalized
            for item in policy
            if isinstance(item, str)
            for normalized in [_canonical_origin(item)]
            if normalized is not None
        }
    return False


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
    provider = result.get("provider")
    if provider is not None and (not isinstance(provider, str) or not provider.strip()):
        raise ValueError("provider must be non-empty text.")
    if isinstance(provider, str):
        result["provider"] = provider.strip().lower()
    if media_type == "iframe":
        is_vaultpub = result.get("provider") == "vaultpub"
        if is_vaultpub and not url.startswith("/"):
            raise ValueError("VaultPub embeds must use a same-origin relative URL.")
        if not is_vaultpub and not _iframe_policy_allows(url):
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
        aggregate_public_submissions=_aggregate_public_choices,
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
        aggregate_public_submissions=_aggregate_public_choices,
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
        aggregate_public_submissions=_aggregate_public_choices,
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
        aggregate_public_submissions=_aggregate_public_choices,
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
        aggregate_public_submissions=_aggregate_public_text,
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
        aggregate_public_submissions=_aggregate_public_numeric,
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
        aggregate_public_submissions=_aggregate_public_numeric,
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
        aggregate_public_submissions=_aggregate_public_ranking,
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
        aggregate_public_submissions=_aggregate_public_word_cloud,
        export_submission=_plain_export,
        capabilities=frozenset({"text", "aggregate"}),
        frontend_manifest=_manifest("word_cloud"),
    ),
    ActivityType(
        "liveclassroom.bash_simulator",
        validate_definition=_bash_definition,
        normalize_submission=_normalize_bash_submission,
        validate_submission=_validate_bash_submission,
        aggregate_submissions=_aggregate_bash_submissions,
        aggregate_public_submissions=_aggregate_bash_submissions,
        export_submission=_export_bash_submission,
        capabilities=frozenset({"aggregate"}),
        frontend_manifest={
            "editor": "liveclassroom/plugins/editor.v1.js",
            "student_renderer": "liveclassroom/plugins/bash_simulator.v1.js",
            "display_renderer": "liveclassroom/plugins/bash_simulator.v1.js",
            "analytics": "liveclassroom/plugins/analytics.v1.js",
        },
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
        "liveclassroom.file",
        validate_definition=_file_definition,
        export_submission=_plain_export,
        capabilities=frozenset({"content"}),
        frontend_manifest=_manifest("file"),
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
