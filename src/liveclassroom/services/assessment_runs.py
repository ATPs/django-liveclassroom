"""Publication of immutable, private assessment-run manifests."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from django.db import transaction

from liveclassroom.models import AssessmentDefinition, AssessmentRun, AssessmentRunAsset

from .classroom import ClassroomError
from .permissions import can_author_course, can_teach


def _owner(actor, assessment: AssessmentDefinition) -> None:
    if not can_teach(actor) or (
        assessment.owner_id != actor.pk and not getattr(actor, "is_superuser", False)
    ):
        raise ClassroomError("You do not have permission to publish this assessment.")


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _audience(assessment: AssessmentDefinition, value: Any) -> str:
    if value is None:
        value = assessment.settings.get("audience", AssessmentRun.Audience.AUTHENTICATED_LINK)
    if value not in AssessmentRun.Audience.values:
        raise ClassroomError("audience must be authenticated_link or class.")
    if value == AssessmentRun.Audience.CLASS:
        if assessment.course_id is None or not can_author_course(assessment.owner, assessment.course):
            raise ClassroomError("A class audience requires an authorized assessment class.")
    return value


def _manifest(assessment: AssessmentDefinition) -> tuple[dict[str, Any], list]:
    items: list[dict[str, Any]] = []
    assets = []
    seen_asset_ids = set()
    for item in assessment.items.select_related("question_revision__definition", "question_revision__asset").all():
        revision = item.question_revision
        definition = revision.definition
        asset = revision.asset or definition.asset
        if asset is not None and asset.pk not in seen_asset_ids:
            assets.append(asset)
            seen_asset_ids.add(asset.pk)
        items.append(
            {
                "key": str(item.key),
                "position": item.position,
                "points": _decimal_text(item.points),
                "revision_id": revision.id,
                "revision": revision.revision,
                "definition_id": definition.id,
                "type_key": definition.type_key,
                "schema_version": revision.schema_version,
                "payload": deepcopy(revision.payload),
                "metadata": deepcopy(revision.metadata),
                "asset_id": str(asset.public_id) if asset is not None else None,
            }
        )
    if not items:
        raise ClassroomError("An assessment needs at least one question before publication.")
    return {
        "schema_version": 1,
        "title": assessment.title,
        "instructions": assessment.instructions,
        "settings": deepcopy(assessment.settings),
        "items": items,
    }, assets


@transaction.atomic
def publish_assessment(
    *, actor, assessment: AssessmentDefinition, expected_version: int, audience: Any = None
) -> AssessmentRun:
    """Freeze a valid teacher draft into a distinct immutable run."""
    _owner(actor, assessment)
    locked = AssessmentDefinition.objects.select_for_update().select_related("course").get(pk=assessment.pk)
    _owner(actor, locked)
    if (
        isinstance(expected_version, bool)
        or not isinstance(expected_version, int)
        or expected_version != locked.version
    ):
        raise ClassroomError("The assessment changed; refresh before publishing.")
    selected_audience = _audience(locked, audience)
    manifest, assets = _manifest(locked)
    run = AssessmentRun.objects.create(
        owner=actor,
        source_assessment=locked,
        source_version=locked.version,
        course=locked.course if selected_audience == AssessmentRun.Audience.CLASS else None,
        audience=selected_audience,
        title=locked.title,
        manifest=manifest,
    )
    AssessmentRunAsset.objects.bulk_create([AssessmentRunAsset(run=run, asset=asset) for asset in assets])
    return run


def run_payload(run: AssessmentRun, *, include_manifest: bool = False) -> dict[str, Any]:
    """Serialize a run without accidentally exposing answer keys to entrants."""
    result = {
        "id": run.id,
        "public_id": str(run.public_id),
        "source_assessment_id": run.source_assessment_id,
        "source_version": run.source_version,
        "title": run.title,
        "audience": run.audience,
        "course_id": run.course_id,
        "created_at": run.created_at.isoformat(),
    }
    if include_manifest:
        result["manifest"] = deepcopy(run.manifest)
    return result


def available_run_payload(run: AssessmentRun) -> dict[str, Any]:
    """Safe pre-attempt metadata; content stays unavailable until task 24."""
    manifest = run.manifest if isinstance(run.manifest, dict) else {}
    return {
        "public_id": str(run.public_id),
        "title": run.title,
        "instructions": manifest.get("instructions", ""),
        "audience": run.audience,
        "course_id": run.course_id,
        "attempt_available": False,
    }
