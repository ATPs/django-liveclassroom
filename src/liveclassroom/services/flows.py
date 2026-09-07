"""Transactional services for flow and flow step authoring."""

from __future__ import annotations

from django.db import transaction
from django.utils.text import slugify

from liveclassroom.models import (
    ActivityDefinition,
    Course,
    Flow,
    FlowStep,
    LiveSession,
)
from liveclassroom.services.classroom import ClassroomError
from liveclassroom.services.permissions import (
    can_author_course,
    can_edit_flow,
    can_use_activity_definition,
)


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

    flow = Flow.objects.select_for_update().get(pk=flow.pk)
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
    activity_definition: ActivityDefinition,
    position: int | None = None,
) -> FlowStep:
    """Add one authorized reusable activity definition to a flow."""
    if not can_edit_flow(actor, flow):
        raise ClassroomError("You do not have permission to edit this flow.")

    if activity_definition.status == ActivityDefinition.Status.ARCHIVED:
        raise ClassroomError("Archived activities cannot be added to a flow.")
    if not can_use_activity_definition(actor, activity_definition):
        raise ClassroomError("You do not have permission to use this activity.")

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
    existing_steps = {step.id: step for step in flow.steps.select_for_update().order_by("position")}
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
    step = flow.steps.select_for_update().filter(pk=step_id).order_by("position").first()
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
def duplicate_flow(*, flow: Flow, creator, title=None, slug=None) -> Flow:
    from .plans import copy_lesson
    return copy_lesson(flow=flow, actor=creator, title=title, slug=slug)


@transaction.atomic
def save_session_as_flow(*, session: LiveSession, creator, title: str, slug=None) -> Flow:
    from .plans import save_lesson
    return save_lesson(session=session, actor=creator, title=title, slug=slug)
