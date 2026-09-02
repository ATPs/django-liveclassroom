"""Parse versioned Markdown/YAML teaching content before it reaches the ORM."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from django.db import transaction
from django.utils.text import slugify

from liveclassroom.models import Flow, FlowItem, Question


class ImportError(ValueError):
    """Input is invalid; no database write has occurred."""


@dataclass(frozen=True)
class ParsedItem:
    kind: str
    title: str
    content: dict
    question: dict | None = None


@dataclass(frozen=True)
class ParsedFlow:
    title: str
    slug: str
    description: str
    items: tuple[ParsedItem, ...]


_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_QUIZ = re.compile(r"^:::quiz\s*\n(.*?)^:::\s*$", re.MULTILINE | re.DOTALL)
_SEPARATOR = re.compile(r"^---\s*$", re.MULTILINE)
_QUESTION_TYPES = {choice for choice, _ in Question.Type.choices}


def _yaml(value: str, context: str) -> dict:
    try:
        parsed = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        raise ImportError(f"Invalid YAML in {context}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ImportError(f"{context} must be a YAML mapping.")
    return parsed


def _question(payload: dict) -> dict:
    question_type = payload.get("type", Question.Type.SINGLE_CHOICE)
    if question_type not in _QUESTION_TYPES:
        raise ImportError(f"Unsupported question type: {question_type!r}.")
    stem = payload.get("question", "").strip()
    if not stem:
        raise ImportError("A quiz requires question text.")
    choices = payload.get("choices", [])
    if question_type in {Question.Type.SINGLE_CHOICE, Question.Type.MULTIPLE_CHOICE, Question.Type.POLL}:
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
    if question_type != Question.Type.POLL and any(value not in option_ids for value in normalized_answer):
        raise ImportError("Every answer must name an option id or option text.")
    return {
        "question_type": question_type,
        "stem_markdown": stem,
        "data": {"options": options},
        "answer": normalized_answer,
        "explanation_markdown": payload.get("explanation", "").strip(),
        "source": payload.get("id", ""),
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
                items.append(ParsedItem(FlowItem.Kind.MARKDOWN, "", {"markdown": markdown}))
            payload = _question(_yaml(quiz.group(1), "quiz directive"))
            items.append(ParsedItem(FlowItem.Kind.QUESTION, payload["stem_markdown"][:80], {}, payload))
            cursor = quiz.end()
        markdown = section[cursor:].strip()
        if markdown:
            items.append(ParsedItem(FlowItem.Kind.MARKDOWN, "", {"markdown": markdown}))
    if not items:
        raise ImportError("The course file contains no importable content.")
    return ParsedFlow(title, slug, str(metadata.get("description", "")).strip(), tuple(items))


@transaction.atomic
def import_markdown_flow(*, course, source: str, fallback_slug: str | None = None) -> Flow:
    """Validate all source before creating a new flow and its question snapshots."""
    parsed = parse_markdown(source, fallback_slug=fallback_slug)
    if Flow.objects.filter(course=course, slug=parsed.slug).exists():
        raise ImportError(f"Course already has a flow with slug {parsed.slug!r}.")
    flow = Flow.objects.create(course=course, title=parsed.title, slug=parsed.slug, description=parsed.description)
    for position, item in enumerate(parsed.items, start=1):
        question = Question.objects.create(**item.question) if item.question else None
        FlowItem.objects.create(
            flow=flow, position=position, kind=item.kind, title=item.title, content=item.content, question=question
        )
    return flow


def import_markdown_file(*, course, path: str | Path, fallback_slug: str | None = None) -> Flow:
    source = Path(path).read_text(encoding="utf-8")
    return import_markdown_flow(course=course, source=source, fallback_slug=fallback_slug)
