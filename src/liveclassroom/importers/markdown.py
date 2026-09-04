"""Parse versioned Markdown/YAML teaching content before it reaches the ORM."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from liveclassroom.models import ActivityDefinition, Flow, FlowStep
from liveclassroom.registry import activity_registry


class ImportError(ValueError):
    """Input is invalid; no database write has occurred."""


@dataclass(frozen=True)
class ParsedItem:
    type_key: str
    title: str
    content: dict


@dataclass(frozen=True)
class ParsedFlow:
    title: str
    slug: str
    description: str
    items: tuple[ParsedItem, ...]


_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_QUIZ = re.compile(r"^:::quiz\s*\n(.*?)^:::\s*$", re.MULTILINE | re.DOTALL)
_SEPARATOR = re.compile(r"^---\s*$", re.MULTILINE)
_QUESTION_TYPES = {
    "single_choice", "multiple_choice", "true_false", "poll", "short_text", "numeric", "rating", "ranking",
}


def _yaml(value: str, context: str) -> dict:
    try:
        parsed = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        raise ImportError(f"Invalid YAML in {context}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ImportError(f"{context} must be a YAML mapping.")
    return parsed


def _question(payload: dict) -> dict:
    question_type = payload.get("type", "single_choice")
    if question_type not in _QUESTION_TYPES:
        raise ImportError(f"Unsupported question type: {question_type!r}.")
    stem = payload.get("question", "").strip()
    if not stem:
        raise ImportError("A quiz requires question text.")
    choices = payload.get("choices", [])
    if question_type in {"single_choice", "multiple_choice", "poll"}:
        if not isinstance(choices, list) or len(choices) < 2:
            raise ImportError("Choice questions require at least two choices.")
    options, text_to_id = [], {}
    for index, choice in enumerate(choices):
        option_id = chr(ord("A") + index)
        text = choice
        if isinstance(choice, dict):
            option_id, text = choice.get("id", option_id), choice.get("text")
        if not isinstance(option_id, str) or not isinstance(text, str) or not text.strip():
            raise ImportError("Each choice must be text or an {id, text} mapping.")
        options.append({"id": option_id, "text": text.strip()})
        text_to_id[text.strip()] = option_id
    answer = payload.get("answer", [])
    if isinstance(answer, str):
        answer = [answer]
    if not isinstance(answer, list):
        raise ImportError("answer must be a list or string.")
    normalized_answer = [text_to_id.get(value, value) for value in answer]
    option_ids = {option["id"] for option in options}
    if question_type != "poll" and any(value not in option_ids for value in normalized_answer):
        raise ImportError("Every answer must name an option id or option text.")
    return {
        "type_key": f"liveclassroom.{question_type}",
        "title": stem[:80],
        "definition": {
            "prompt": stem,
            "stem_markdown": stem,
            "options": options,
            "answer": normalized_answer,
            "explanation": payload.get("explanation", "").strip(),
        },
    }


def parse_markdown(source: str, *, fallback_slug: str | None = None) -> ParsedFlow:
    """Parse front matter, Markdown pages, and ``:::quiz`` YAML directives."""
    match = _FRONT_MATTER.match(source)
    metadata = _yaml(match.group(1), "front matter") if match else {}
    body = source[match.end() :] if match else source
    title = str(metadata.get("title", "")).strip()
    if not title:
        raise ImportError("Front matter must define title.")
    slug = slugify(str(metadata.get("slug") or fallback_slug or title))
    if not slug:
        raise ImportError("A valid slug is required.")
    items: list[ParsedItem] = []
    for section in (part.strip() for part in _SEPARATOR.split(body)):
        if not section:
            continue
        cursor = 0
        for quiz in _QUIZ.finditer(section):
            markdown = section[cursor : quiz.start()].strip()
            if markdown:
                items.append(ParsedItem("liveclassroom.markdown", "", {"markdown": markdown}))
            payload = _question(_yaml(quiz.group(1), "quiz directive"))
            items.append(ParsedItem(payload["type_key"], payload["title"], payload["definition"]))
            cursor = quiz.end()
        markdown = section[cursor:].strip()
        if markdown:
            items.append(ParsedItem("liveclassroom.markdown", "", {"markdown": markdown}))
    if not items:
        raise ImportError("The course file contains no importable content.")
    return ParsedFlow(title, slug, str(metadata.get("description", "")).strip(), tuple(items))


@transaction.atomic
def import_markdown_flow(
    *,
    course,
    source: str,
    creator=None,
    fallback_slug: str | None = None,
) -> Flow:
    """Validate all source before creating canonical activity definitions and flow steps."""
    parsed = parse_markdown(source, fallback_slug=fallback_slug)
    if Flow.objects.filter(course=course, slug=parsed.slug).exists():
        raise ImportError(f"Course already has a flow with slug {parsed.slug!r}.")

    owner = creator or getattr(course, "created_by", None)
    if owner is None:
        user_model = get_user_model()
        owner = user_model.objects.filter(is_superuser=True).first() or user_model.objects.first()

    flow = Flow.objects.create(
        course=course,
        created_by=creator or getattr(course, "created_by", None),
        title=parsed.title,
        slug=parsed.slug,
        description=parsed.description,
    )
    if owner is None:
        raise ImportError("A creator or course owner is required to import a flow.")
    for position, item in enumerate(parsed.items, start=1):
        try:
            definition = activity_registry.get(item.type_key).validate(item.content)
        except (KeyError, TypeError, ValueError) as exc:
            raise ImportError(f"Invalid activity definition for {item.type_key}: {exc}") from exc
        activity_def = ActivityDefinition.objects.create(
            owner=owner,
            course=course,
            type_key=item.type_key,
            title=item.title or "Markdown",
            definition=definition,
            status=ActivityDefinition.Status.READY,
        )
        FlowStep.objects.create(
            flow=flow,
            position=position,
            activity_definition=activity_def,
        )

    return flow


def import_markdown_file(
    *,
    course,
    path: str | Path,
    creator=None,
    fallback_slug: str | None = None,
) -> Flow:
    source = Path(path).read_text(encoding="utf-8")
    return import_markdown_flow(course=course, source=source, creator=creator, fallback_slug=fallback_slug)
