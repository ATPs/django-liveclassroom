"""Publication of immutable, private assessment-run manifests."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any
from uuid import uuid4

from django.db import transaction

from liveclassroom.models import (
    AssessmentDefinition,
    AssessmentRun,
    AssessmentRunAsset,
    AssessmentSectionEntry,
    QuestionBankItem,
)

from .classroom import ClassroomError
from .permissions import can_author_course, can_teach, can_use_activity_definition
from .question_banks import _matches, normalize_bank_filters


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


def _snapshot(
    *, revision, key: str, points: Decimal, position: int, asset_seen: set[int], assets: list
) -> dict[str, Any]:
    definition = revision.definition
    asset = revision.asset or definition.asset
    if asset is not None and asset.pk not in asset_seen:
        assets.append(asset)
        asset_seen.add(asset.pk)
    return {
        "key": key,
        "position": position,
        "points": _decimal_text(points),
        "revision_id": revision.id,
        "revision": revision.revision,
        "definition_id": definition.id,
        "type_key": definition.type_key,
        "schema_version": revision.schema_version,
        "payload": deepcopy(revision.payload),
        "metadata": deepcopy(revision.metadata),
        "asset_id": str(asset.public_id) if asset is not None else None,
    }


def _candidate_rows(*, actor, entry, excluded_definitions: set[int], excluded_revisions: set[int]):
    """Resolve a bank rule against current source data at publication only."""
    if entry.bank is None or entry.bank.owner_id != actor.pk and not getattr(actor, "is_superuser", False):
        raise ClassroomError("You do not have permission to use this question bank.")
    try:
        filters = normalize_bank_filters(entry.filters if isinstance(entry.filters, dict) else {})
    except ClassroomError:
        raise ClassroomError("The pool contains invalid search filters.") from None
    members = QuestionBankItem.objects.filter(bank=entry.bank).select_related(
        "definition__current_revision", "definition__asset", "definition__current_revision__asset"
    ).order_by("position", "id")
    rows = []
    seen: set[tuple[int, int]] = set()
    for membership in members:
        definition = membership.definition
        revision = definition.current_revision
        if revision is None or definition.pk in excluded_definitions or revision.pk in excluded_revisions:
            continue
        if not _matches(definition, filters):
            continue
        if not can_use_activity_definition(actor, definition):
            raise ClassroomError("You do not have permission to use a pooled question.")
        try:
            from liveclassroom.registry import activity_registry

            activity_type = activity_registry.get(definition.type_key)
            activity_type.validate(deepcopy(revision.payload))
        except (KeyError, TypeError, ValueError) as exc:
            raise ClassroomError("A pooled question revision is no longer supported.") from exc
        if not (activity_type.capabilities & frozenset({"correctness", "manual"})):
            raise ClassroomError("Only graded question types may be selected by a pool.")
        asset = revision.asset or definition.asset
        if asset is not None and asset.owner_id not in {actor.pk, definition.owner_id} and not getattr(
            actor, "is_superuser", False
        ):
            raise ClassroomError("You do not have permission to retain a pooled question asset.")
        identity = (definition.pk, revision.pk)
        if identity in seen:
            continue
        seen.add(identity)
        rows.append((definition, revision))
    return rows


def _manifest(assessment: AssessmentDefinition, *, actor=None) -> tuple[dict[str, Any], list]:
    """Freeze fixed items and section pools into a run manifest."""
    actor = assessment.owner if actor is None else actor
    assets = []
    seen_asset_ids: set[int] = set()
    fixed_items: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    has_pool = False
    section_rows = list(
        assessment.sections.prefetch_related(
            "entries__bank",
            "entries__item__question_revision__definition",
            "entries__item__question_revision__asset",
        ).all()
    )
    if not section_rows:
        # Direct ORM-created legacy drafts have no section rows.  Interpret
        # them as the compatibility default section without changing items.
        section_rows = []

    if section_rows:
        for section in section_rows:
            section_manifest = {
                "key": str(section.key),
                "title": section.title,
                "position": section.position,
                "shuffle_questions": section.shuffle_questions,
                "entries": [],
            }
            fixed_definitions: set[int] = {
                entry.item.question_revision.definition_id
                for entry in section.entries.all()
                if entry.kind == AssessmentSectionEntry.Kind.FIXED and entry.item is not None
            }
            fixed_revisions: set[int] = {
                entry.item.question_revision_id
                for entry in section.entries.all()
                if entry.kind == AssessmentSectionEntry.Kind.FIXED and entry.item is not None
            }
            pooled_identities: set[tuple[int, int]] = set()
            for entry in section.entries.all():
                if entry.kind == AssessmentSectionEntry.Kind.FIXED:
                    item = entry.item
                    if item is None or item.assessment_id != assessment.pk:
                        raise ClassroomError("A section fixed item does not belong to this assessment.")
                    revision = item.question_revision
                    snapshot = _snapshot(
                        revision=revision,
                        key=str(item.key),
                        points=item.points,
                        position=item.position,
                        asset_seen=seen_asset_ids,
                        assets=assets,
                    )
                    snapshot["section_key"] = str(section.key)
                    fixed_items.append(snapshot)
                    section_manifest["entries"].append(
                        {
                            "key": str(entry.key),
                            "position": entry.position,
                            "kind": "fixed",
                            "item_key": str(item.key),
                            "item": deepcopy(snapshot),
                            "shuffle_options": entry.shuffle_options,
                        }
                    )
                    continue
                if entry.kind != AssessmentSectionEntry.Kind.POOL:
                    raise ClassroomError("The assessment section contains an unsupported entry.")
                has_pool = True
                candidate_rows = _candidate_rows(
                    actor=actor,
                    entry=entry,
                    excluded_definitions=fixed_definitions,
                    excluded_revisions=fixed_revisions,
                )
                if entry.sample_size is None or entry.sample_size <= 0:
                    raise ClassroomError("sample_size must be a positive integer.")
                if entry.sample_size > len(candidate_rows):
                    raise ClassroomError(
                        f"Pool {entry.bank_id} has {len(candidate_rows)} eligible questions; "
                        f"sample_size {entry.sample_size} is unavailable."
                    )
                candidate_manifests = []
                identities: set[tuple[int, int]] = set()
                for candidate_position, (definition, revision) in enumerate(candidate_rows, 1):
                    identity = (definition.pk, revision.pk)
                    if identity in identities:
                        raise ClassroomError("A question appears more than once in this pool.")
                    if identity in pooled_identities:
                        raise ClassroomError("Question pools overlap in this section.")
                    identities.add(identity)
                    pooled_identities.add(identity)
                    candidate_manifests.append(
                        _snapshot(
                            revision=revision,
                            key=str(uuid4()),
                            points=entry.points or _candidate_points(revision),
                            position=candidate_position,
                            asset_seen=seen_asset_ids,
                            assets=assets,
                        )
                    )
                section_manifest["entries"].append(
                    {
                        "key": str(entry.key),
                        "position": entry.position,
                        "kind": "pool",
                        "bank_id": entry.bank_id,
                        "filters": deepcopy(entry.filters),
                        "sample_size": entry.sample_size,
                        "points": _decimal_text(entry.points) if entry.points is not None else None,
                        "shuffle_options": entry.shuffle_options,
                        "candidates": candidate_manifests,
                    }
                )
            sections.append(section_manifest)
    else:
        for item in assessment.items.select_related("question_revision__definition", "question_revision__asset").all():
            fixed_items.append(
                _snapshot(
                    revision=item.question_revision,
                    key=str(item.key),
                    points=item.points,
                    position=item.position,
                    asset_seen=seen_asset_ids,
                    assets=assets,
                )
            )
    if not fixed_items and not has_pool:
        raise ClassroomError("An assessment needs at least one question before publication.")
    if not fixed_items and not sections:
        raise ClassroomError("An assessment needs at least one question before publication.")
    return {
        "schema_version": 2,
        "title": assessment.title,
        "instructions": assessment.instructions,
        "settings": deepcopy(assessment.settings),
        "items": fixed_items,
        "sections": sections,
    }, assets


def _candidate_points(revision) -> Decimal:
    metadata = revision.metadata if isinstance(revision.metadata, dict) else {}
    value = metadata.get("default_points", "1")
    try:
        points = Decimal(str(value))
    except Exception as exc:  # pragma: no cover - invalid direct ORM rows are reported below
        raise ClassroomError("A pooled question has invalid points.") from exc
    if not points.is_finite() or points <= 0 or points > Decimal("1000"):
        raise ClassroomError("A pooled question has invalid points.")
    if -points.as_tuple().exponent > 6:
        raise ClassroomError("A pooled question has too many decimal places in points.")
    return points


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
    manifest, assets = _manifest(locked, actor=actor)
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
    """Safe landing metadata; assigned content is returned only after start."""
    manifest = run.manifest if isinstance(run.manifest, dict) else {}
    return {
        "public_id": str(run.public_id),
        "title": run.title,
        "instructions": manifest.get("instructions", ""),
        "audience": run.audience,
        "course_id": run.course_id,
        "attempt_available": True,
    }
