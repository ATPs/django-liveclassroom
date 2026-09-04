"""Parse and import JSON-defined flows through the canonical activity registry."""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from liveclassroom.importers.markdown import ImportError
from liveclassroom.models import ActivityDefinition, Course, Flow, FlowStep
from liveclassroom.registry import activity_registry


def parse_json_flow(source: str | dict[str, Any]) -> dict[str, Any]:
    """Parse and validate a JSON flow definition before touching the database."""
    if isinstance(source, str):
        try:
            data = json.loads(source)
        except json.JSONDecodeError as exc:
            raise ImportError(f"Invalid JSON: {exc}") from exc
    elif isinstance(source, dict):
        data = source
    else:
        raise ImportError("JSON flow must be a JSON string or object.")

    title = data.get("title")
    if not title or not str(title).strip():
        raise ImportError("Flow title is required.")
    title = str(title).strip()

    raw_slug = data.get("slug")
    slug = slugify(str(raw_slug).strip()) if raw_slug and str(raw_slug).strip() else None
    description = str(data.get("description") or "").strip()

    raw_steps = data.get("steps")
    if raw_steps is None:
        raw_steps = data.get("items")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ImportError("The flow contains no importable steps.")

    parsed_steps: list[dict[str, Any]] = []
    for index, step in enumerate(raw_steps, start=1):
        if not isinstance(step, dict):
            raise ImportError(f"Step {index} must be an object.")

        raw_type = step.get("type_key") or step.get("type")
        if not raw_type and step.get("kind"):
            raw_type = step["kind"]
        if not raw_type:
            raw_type = "single_choice"
        raw_type = str(raw_type).strip()
        if "." not in raw_type:
            type_key = f"liveclassroom.{raw_type}"
        else:
            type_key = raw_type

        try:
            activity_type = activity_registry.get(type_key)
        except KeyError as exc:
            raise ImportError(f"Unsupported activity type {type_key!r} in step {index}.") from exc

        step_title = str(step.get("title") or "").strip()

        # Extract definition payload
        if isinstance(step.get("definition"), dict):
            def_payload = dict(step["definition"])
        elif isinstance(step.get("content"), dict) and step.get("content"):
            def_payload = dict(step["content"])
        else:
            meta_keys = {"title", "type", "type_key", "kind", "position", "schema_version", "definition", "content"}
            def_payload = {k: v for k, v in step.items() if k not in meta_keys}

        if "prompt" not in def_payload and "question" in def_payload and isinstance(def_payload["question"], str):
            def_payload["prompt"] = def_payload["question"]
            def_payload["stem_markdown"] = def_payload["question"]

        if not step_title:
            prompt_candidate = def_payload.get("prompt") or def_payload.get("stem_markdown")
            if prompt_candidate and isinstance(prompt_candidate, str):
                step_title = prompt_candidate[:80]
            else:
                step_title = f"Step {index}"

        # Validate through canonical registry before any database writes
        try:
            validated_def = activity_type.validate(def_payload)
        except (ValueError, KeyError, TypeError) as exc:
            raise ImportError(f"Invalid activity definition in step {index} ({type_key}): {exc}") from exc

        kind = step.get("kind") or "activity"
        parsed_steps.append({
            "type_key": type_key,
            "kind": kind,
            "title": step_title,
            "definition": validated_def,
        })

    return {
        "title": title,
        "slug": slug,
        "description": description,
        "steps": parsed_steps,
    }


@transaction.atomic
def import_json_flow(
    *,
    source: str | dict[str, Any],
    course: Course | None = None,
    creator=None,
    fallback_slug: str | None = None,
) -> Flow:
    """Validate all activities then atomically create canonical FlowStep rows."""
    parsed = parse_json_flow(source)

    candidate_slug = parsed["slug"] or fallback_slug or parsed["title"]
    clean_slug = slugify(str(candidate_slug).strip())
    if not clean_slug:
        raise ImportError("A valid slug is required.")

    if Flow.objects.filter(course=course, slug=clean_slug).exists():
        raise ImportError(f"Course already has a flow with slug {clean_slug!r}.")

    owner = creator or getattr(course, "created_by", None)
    if owner is None:
        user_model = get_user_model()
        owner = user_model.objects.filter(is_superuser=True).first() or user_model.objects.first()
        if owner is None:
            raise ImportError("A creator or course owner is required to create activity definitions.")

    flow = Flow.objects.create(
        course=course,
        created_by=creator,
        title=parsed["title"],
        slug=clean_slug,
        description=parsed["description"],
    )

    for position, step_data in enumerate(parsed["steps"], start=1):
        activity_def = ActivityDefinition.objects.create(
            owner=owner,
            course=course,
            type_key=step_data["type_key"],
            title=step_data["title"],
            definition=step_data["definition"],
            status=ActivityDefinition.Status.READY,
        )

        FlowStep.objects.create(
            flow=flow,
            position=position,
            activity_definition=activity_def,
            kind=step_data["kind"],
            title=step_data["title"],
            content=step_data["definition"],
        )

    return flow
