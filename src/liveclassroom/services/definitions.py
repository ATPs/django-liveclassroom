"""Transactional reusable-activity definition commands."""

from typing import Any

from django.db import transaction

from liveclassroom.models import ActivityDefinition, ActivityDefinitionRevision, ClassroomAsset, Flow
from liveclassroom.registry import activity_registry

from .permissions import can_author_course, can_host_author, can_teach
from .question_metadata import validate_question_metadata
from .runtime import ClassroomError


def _metadata(value) -> dict:
    try:
        return validate_question_metadata(value)
    except ValueError as exc:
        raise ClassroomError(str(exc)) from exc


@transaction.atomic
def create_activity_definition(
    *, owner, title: str, type_key: str, definition: dict[str, Any], course=None, asset=None,
    metadata=None, change_note: str = ""
) -> ActivityDefinition:
    """Create a validated reusable activity and its first immutable revision."""
    if not can_teach(owner):
        raise ClassroomError("An authenticated teacher is required to create an activity.")
    if not can_host_author(owner):
        raise ClassroomError("The host does not allow activity authoring.")
    if not isinstance(type_key, str) or not type_key.strip():
        raise ClassroomError("An activity type is required.")
    type_key = type_key.strip()
    if course is not None and not getattr(owner, "is_superuser", False) and not can_author_course(owner, course):
        raise ClassroomError("You do not have permission to author content for this course.")
    if "." not in type_key:
        type_key = f"liveclassroom.{type_key}"
    if type_key == "liveclassroom.file":
        if not isinstance(asset, ClassroomAsset):
            raise ClassroomError("A classroom asset is required for file content.")
        if asset.owner_id != owner.pk and not getattr(owner, "is_superuser", False):
            raise ClassroomError("You do not have permission to use this classroom asset.")
        if definition.get("asset_id") != str(asset.public_id):
            raise ClassroomError("The file definition does not match the selected asset.")
    elif asset is not None:
        raise ClassroomError("Only file content may reference a classroom asset.")
    try:
        activity_type = activity_registry.get(type_key)
        definition = activity_type.validate(definition)
    except (KeyError, ValueError) as exc:
        raise ClassroomError(str(exc)) from exc
    metadata = _metadata(metadata)
    if not isinstance(title, str) or not title.strip():
        raise ClassroomError("An activity title is required.")
    activity = ActivityDefinition.objects.create(
        owner=owner,
        course=course,
        type_key=type_key,
        title=title.strip(),
        definition=definition,
        metadata=metadata,
        asset=asset,
        status=ActivityDefinition.Status.READY,
    )
    activity.refresh_from_db(fields=["current_revision"])
    revision = activity.current_revision
    if revision is None:
        revision = activity.revisions.create(
            revision=1,
            schema_version=activity.schema_version,
            payload=definition,
            metadata=metadata,
            asset=asset,
            changed_by=owner,
            change_note=change_note,
        )
    elif change_note and revision.change_note != change_note:
        revision.change_note = change_note
        revision.save(update_fields=["change_note"])
    activity.current_revision = revision
    activity.save(update_fields=["current_revision", "updated_at"])
    return activity


@transaction.atomic
def revise_activity_definition(
    *, activity: ActivityDefinition, definition: dict[str, Any], actor, metadata=None, change_note: str = ""
) -> ActivityDefinitionRevision:
    """Update a reusable definition without rewriting its prior payload."""
    if not can_teach(actor) or not can_host_author(actor, activity) or (
        activity.owner_id != actor.pk
        and not (activity.course_id and can_author_course(actor, activity.course))
    ):
        raise ClassroomError("You do not have permission to edit this activity.")
    try:
        definition = activity_registry.get(activity.type_key).validate(definition)
    except (KeyError, ValueError) as exc:
        raise ClassroomError(str(exc)) from exc
    metadata = _metadata(activity.metadata if metadata is None else metadata)
    list(
        Flow.objects.select_for_update()
        .filter(pk__in=activity.flow_steps.values("flow_id"))
        .order_by("pk")
    )
    activity = ActivityDefinition.objects.select_for_update().get(pk=activity.pk)
    latest = activity.revisions.order_by("-revision").first()
    revision = activity.revisions.create(
        revision=(latest.revision if latest else 0) + 1,
        schema_version=activity.schema_version,
        payload=definition,
        metadata=metadata,
        asset=activity.asset,
        changed_by=actor,
        change_note=change_note,
    )
    activity.definition = definition
    activity.metadata = metadata
    activity.current_revision = revision
    activity.save(update_fields=["definition", "metadata", "current_revision", "updated_at"])
    return revision
