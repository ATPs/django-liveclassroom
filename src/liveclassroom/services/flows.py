"""Transactional services for flow and flow step authoring."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.text import slugify

from liveclassroom.models import (
    ActivityDefinition,
    Course,
    Flow,
    FlowItem,
    FlowStep,
    LiveSession,
)
from liveclassroom.services.classroom import (
    ClassroomError,
    can_manage_session,
    create_activity_definition,
)
from liveclassroom.services.permissions import (
    can_author_course,
    can_edit_flow,
    can_use_activity_definition,
)


def can_view_flow(actor, flow: Flow) -> bool:
    """Access to view flow authoring details matches edit permissions."""
    return can_edit_flow(actor, flow)


def _generate_unique_flow_slug(course: Course | None, base_text: str, *, exclude_id: int | None = None) -> str:
    slug = slugify(base_text) or "flow"
    candidate = slug
    counter = 1
    query = Flow.objects.filter(course=course)
    if exclude_id:
        query = query.exclude(pk=exclude_id)
    while query.filter(slug=candidate).exists():
        candidate = f"{slug}-{counter}"
        counter += 1
    return candidate


@transaction.atomic
def create_flow(
    *,
    title: str,
    creator,
    course: Course | None = None,
    slug: str | None = None,
    description: str = "",
) -> Flow:
    """Create a new flow associated with a creator and optional course."""
    if not getattr(creator, "is_authenticated", False):
        raise ClassroomError("An authenticated user is required to create a flow.")
    if not isinstance(title, str) or not title.strip():
        raise ClassroomError("Flow title is required.")
    title = title.strip()

    if course is not None and not can_author_course(creator, course):
        raise ClassroomError("You do not have permission to author content for this course.")

    if slug and str(slug).strip():
        cleaned_slug = slugify(str(slug).strip())
        if not cleaned_slug:
            raise ClassroomError("A valid flow slug is required.")
        if Flow.objects.filter(course=course, slug=cleaned_slug).exists():
            raise ClassroomError(f"A flow with slug '{cleaned_slug}' already exists in this course.")
        flow_slug = cleaned_slug
    else:
        flow_slug = _generate_unique_flow_slug(course, title)

    return Flow.objects.create(
        title=title,
        created_by=creator,
        course=course,
        slug=flow_slug,
        description=str(description or "").strip(),
    )


@transaction.atomic
def update_flow(
    *,
    flow: Flow,
    actor,
    title: str | None = None,
    description: str | None = None,
) -> Flow:
    """Update metadata for an existing flow."""
    if not can_edit_flow(actor, flow):
        raise ClassroomError("You do not have permission to edit this flow.")

    update_fields = ["updated_at"]
    if title is not None:
        if not isinstance(title, str) or not title.strip():
            raise ClassroomError("Flow title cannot be empty.")
        flow.title = title.strip()
        update_fields.append("title")

    if description is not None:
        flow.description = str(description).strip()
        update_fields.append("description")

    flow.save(update_fields=update_fields)
    return flow


@transaction.atomic
def add_flow_step(
    *,
    flow: Flow,
    actor,
    item: FlowItem | ActivityDefinition | None = None,
    activity_definition: ActivityDefinition | None = None,
    kind: str = "activity",
    position: int | None = None,
    title: str = "",
    content: dict[str, Any] | None = None,
) -> FlowStep:
    """Add a canonical step to a flow without creating parallel legacy rows."""
    if not can_edit_flow(actor, flow):
        raise ClassroomError("You do not have permission to edit this flow.")

    if activity_definition is None:
        if isinstance(item, ActivityDefinition):
            activity_definition = item
        elif isinstance(item, FlowItem):
            activity_definition = item.activity_definition
            if not title:
                title = item.title
            if content is None:
                content = item.content
            kind = item.kind

    if activity_definition is not None:
        if activity_definition.course_id and flow.course_id and activity_definition.course_id != flow.course_id:
            raise ClassroomError("The activity must belong to the flow's course.")
        if not can_use_activity_definition(actor, activity_definition):
            raise ClassroomError("You do not have permission to use this activity.")
        if not title:
            title = activity_definition.title
        if content is None:
            content = activity_definition.definition

    if content is None:
        content = {}

    flow = Flow.objects.select_for_update().get(pk=flow.pk)
    current_count = flow.steps.count()
    if position is None or position > current_count + 1:
        target_position = current_count + 1
    elif position < 1:
        target_position = 1
    else:
        target_position = position

    # If inserting into existing positions, shift subsequent steps
    if target_position <= current_count:
        steps_to_shift = list(flow.steps.filter(position__gte=target_position).order_by("-position"))
        for s in steps_to_shift:
            s.position = s.position + 1
            s.save(update_fields=["position"])

    step = FlowStep.objects.create(
        flow=flow,
        position=target_position,
        activity_definition=activity_definition,
        kind=kind,
        title=title,
        content=content,
    )

    flow.save(update_fields=["updated_at"])
    return step


@transaction.atomic
def reorder_flow_steps(
    *,
    flow: Flow,
    actor,
    step_ids: list[int],
) -> list[FlowStep]:
    """Reorder steps in a flow according to the given list of step IDs."""
    if not can_edit_flow(actor, flow):
        raise ClassroomError("You do not have permission to edit this flow.")

    flow = Flow.objects.select_for_update().get(pk=flow.pk)
    existing_steps = {step.id: step for step in flow.steps.select_for_update()}
    if len(step_ids) != len(existing_steps) or set(step_ids) != set(existing_steps.keys()):
        raise ClassroomError("step_ids must contain all step IDs of the flow.")

    # Shift steps out of range to prevent unique constraint conflicts
    for step in existing_steps.values():
        step.position = step.position + 100000
        step.save(update_fields=["position"])

    reordered: list[FlowStep] = []
    for new_pos, step_id in enumerate(step_ids, start=1):
        step = existing_steps[step_id]
        step.position = new_pos
        step.save(update_fields=["position"])
        reordered.append(step)

    flow.save(update_fields=["updated_at"])
    return reordered


@transaction.atomic
def remove_flow_step(
    *,
    flow: Flow,
    actor,
    step_id: int,
) -> None:
    """Remove a step from a flow and re-index remaining steps."""
    if not can_edit_flow(actor, flow):
        raise ClassroomError("You do not have permission to edit this flow.")

    flow = Flow.objects.select_for_update().get(pk=flow.pk)
    step = flow.steps.select_for_update().filter(pk=step_id).first()
    if step is None:
        raise ClassroomError("Flow step not found.")

    step.delete()

    # Re-index remaining steps
    remaining_steps = list(flow.steps.all().order_by("position"))
    for s in remaining_steps:
        s.position = s.position + 100000
        s.save(update_fields=["position"])
    for idx, s in enumerate(remaining_steps, start=1):
        s.position = idx
        s.save(update_fields=["position"])

    flow.save(update_fields=["updated_at"])


@transaction.atomic
def duplicate_flow(
    *,
    flow: Flow,
    creator,
    title: str | None = None,
    slug: str | None = None,
) -> Flow:
    """Duplicate a flow along with its canonical FlowSteps."""
    if not getattr(creator, "is_authenticated", False):
        raise ClassroomError("An authenticated user is required to duplicate a flow.")
    if not can_edit_flow(creator, flow):
        raise ClassroomError("You do not have permission to duplicate this flow.")

    new_title = title.strip() if title and title.strip() else f"{flow.title} (Copy)"
    if slug and str(slug).strip():
        cleaned_slug = slugify(str(slug).strip())
        if not cleaned_slug:
            raise ClassroomError("A valid flow slug is required.")
        if Flow.objects.filter(course=flow.course, slug=cleaned_slug).exists():
            raise ClassroomError(f"A flow with slug '{cleaned_slug}' already exists in this course.")
        new_slug = cleaned_slug
    else:
        new_slug = _generate_unique_flow_slug(flow.course, new_title)

    new_flow = Flow.objects.create(
        course=flow.course,
        created_by=creator,
        title=new_title,
        slug=new_slug,
        description=flow.description,
    )

    for step in flow.steps.all().order_by("position"):
        FlowStep.objects.create(
            flow=new_flow,
            position=step.position,
            activity_definition=step.activity_definition,
            kind=step.kind,
            title=step.title,
            content=step.content,
        )

    return new_flow


@transaction.atomic
def save_session_as_flow(
    *,
    session: LiveSession,
    creator,
    title: str,
    slug: str | None = None,
) -> Flow:
    """Create a reusable Flow from all activities launched in a live session."""
    if not can_manage_session(creator, session):
        raise ClassroomError("You do not have permission to save this session as a flow.")

    if not isinstance(title, str) or not title.strip():
        raise ClassroomError("Flow title is required.")
    title = title.strip()

    if slug and str(slug).strip():
        cleaned_slug = slugify(str(slug).strip())
        if not cleaned_slug:
            raise ClassroomError("A valid flow slug is required.")
        if Flow.objects.filter(course=session.course, slug=cleaned_slug).exists():
            raise ClassroomError(f"A flow with slug '{cleaned_slug}' already exists in this course.")
        flow_slug = cleaned_slug
    else:
        flow_slug = _generate_unique_flow_slug(session.course, title)

    flow = Flow.objects.create(
        course=session.course,
        created_by=creator,
        title=title,
        slug=flow_slug,
        description=f"Saved from session: {session.title}",
    )

    activities = list(session.activities.all().order_by("sequence"))
    for position, activity in enumerate(activities, start=1):
        activity_def = None
        if activity.current_revision and activity.current_revision.source_revision:
            activity_def = activity.current_revision.source_revision.definition
        elif activity.source_step and activity.source_step.activity_definition:
            activity_def = activity.source_step.activity_definition
        elif activity.source_item and activity.source_item.activity_definition:
            activity_def = activity.source_item.activity_definition
        elif activity.definition_snapshot and activity.definition_snapshot.get("activity_definition_id"):
            activity_def = ActivityDefinition.objects.filter(
                pk=activity.definition_snapshot["activity_definition_id"]
            ).first()

        if activity_def is None:
            # Create a reusable ActivityDefinition from snapshot
            snapshot = activity.definition_snapshot or {}
            type_key = snapshot.get("type_key")
            if not type_key:
                if "question" in snapshot:
                    q_type = snapshot["question"].get("type", "single_choice")
                    type_key = f"liveclassroom.{q_type}"
                elif snapshot.get("kind"):
                    type_key = f"liveclassroom.{snapshot['kind']}"
                else:
                    type_key = "liveclassroom.single_choice"
            if "." not in type_key:
                type_key = f"liveclassroom.{type_key}"

            act_title = snapshot.get("title")
            if not act_title and "question" in snapshot:
                act_title = snapshot["question"].get("stem_markdown", "")[:80]
            if not act_title:
                act_title = f"Activity {activity.sequence}"

            if "question" in snapshot:
                q = snapshot["question"]
                def_payload = {
                    "prompt": q.get("stem_markdown", ""),
                    "stem_markdown": q.get("stem_markdown", ""),
                    "options": q.get("data", {}).get("options", []),
                    "answer": q.get("answer", []),
                    "explanation": q.get("explanation_markdown", ""),
                }
            else:
                def_payload = dict(snapshot.get("content") or {})
                if type_key in (
                    "liveclassroom.single_choice",
                    "liveclassroom.multiple_choice",
                    "liveclassroom.poll",
                ):
                    if "options" not in def_payload and "choices" not in def_payload:
                        def_payload["options"] = [{"id": "A", "text": "Option A"}]

            activity_def = create_activity_definition(
                owner=creator,
                title=act_title,
                type_key=type_key,
                definition=def_payload,
                course=session.course,
            )

        FlowStep.objects.create(
            flow=flow,
            position=position,
            activity_definition=activity_def,
            kind="activity",
            title=activity_def.title,
            content=activity_def.definition,
        )

    return flow
