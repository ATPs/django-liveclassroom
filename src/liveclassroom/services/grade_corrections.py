"""Audited manual overrides and explicit regrading of retained attempts.

Corrections operate on the task-31 materialized grade rows.  The delivered
attempt manifest and answer revisions are immutable; a correction appends a
new ``AssessmentGradeDecision`` and updates only the current materialized item
grade.  The earlier decision remains the old-value audit record.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from liveclassroom.integrations.host import host_can_manage_assessment_results
from liveclassroom.models import (
    AnswerRevision,
    AssessmentAttempt,
    AssessmentAttemptItem,
    AssessmentGradeDecision,
    AssessmentItemGrade,
    AssessmentRun,
    GradingRuleRevision,
)

from .assessment_grading import (
    POINT_QUANTUM,
    RULE_VERSION,
    _aggregate,
    score_retained_item,
)
from .classroom import ClassroomError
from .manual_grading import COMMENT_MAX_LENGTH, MANUAL_SOURCE, can_grade_attempt
from .permissions import can_teach

CORRECTION_SOURCE = "override"
REGRADE_SOURCE = "regrade"
OVERRIDE_RULE_VERSION = "manual-override-v1"
MAX_REASON_LENGTH = 255
MAX_SCORE_DECIMALS = 10
PRESERVED_SOURCES = frozenset({MANUAL_SOURCE, CORRECTION_SOURCE})


class GradeCorrectionError(ClassroomError):
    """A correction is invalid, unauthorized or outside its explicit scope."""


def _aware_now(value: datetime | None) -> datetime:
    current = timezone.now() if value is None else value
    return timezone.make_aware(current, timezone.get_current_timezone()) if timezone.is_naive(current) else current


def _score(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise GradeCorrectionError("normalized_score must be a finite decimal between zero and one.")
    try:
        result = Decimal(str(value))
    except (DecimalException, TypeError, ValueError) as exc:
        raise GradeCorrectionError("normalized_score must be a finite decimal between zero and one.") from exc
    if not result.is_finite() or result < 0 or result > 1:
        raise GradeCorrectionError("normalized_score must be between zero and one.")
    if result.as_tuple().exponent < -MAX_SCORE_DECIMALS:
        raise GradeCorrectionError("normalized_score has at most ten decimal places.")
    return result.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def _reason(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GradeCorrectionError("reason is required.")
    result = value.strip()
    if len(result) > MAX_REASON_LENGTH:
        raise GradeCorrectionError(f"reason must be at most {MAX_REASON_LENGTH} characters.")
    return result


def _comment(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise GradeCorrectionError("comment must be text.")
    if len(value) > COMMENT_MAX_LENGTH:
        raise GradeCorrectionError(f"comment must be at most {COMMENT_MAX_LENGTH} characters.")
    return value


def _locked_item(attempt_item: AssessmentAttemptItem) -> tuple[AssessmentAttempt, AssessmentAttemptItem]:
    if not isinstance(attempt_item, AssessmentAttemptItem) or not attempt_item.pk:
        raise GradeCorrectionError("attempt_item must be a saved assessment item.")
    try:
        reference = AssessmentAttemptItem.objects.get(pk=attempt_item.pk)
        attempt = (
            AssessmentAttempt.objects.select_for_update(of=("self",))
            .select_related("run", "run__course", "user")
            .get(pk=reference.attempt_id)
        )
        item = AssessmentAttemptItem.objects.select_for_update(of=("self",)).get(pk=reference.pk)
    except (AssessmentAttempt.DoesNotExist, AssessmentAttemptItem.DoesNotExist) as exc:
        raise GradeCorrectionError("The assessment item was not found.") from exc
    if item.attempt_id != attempt.pk:
        raise GradeCorrectionError("The assessment item does not belong to this attempt.")
    return attempt, item


def _ensure_current_grade(attempt: AssessmentAttempt, item: AssessmentAttemptItem) -> AssessmentItemGrade:
    grade = AssessmentItemGrade.objects.select_for_update().filter(item=item).first()
    if grade is not None:
        return grade
    # The submission callback is best effort.  A direct staff action can
    # safely materialize the missing automatic/pending result before changing
    # it, while retaining task-31's lock and audit convention.
    from .assessment_grading import _grade_submitted_attempt

    _grade_submitted_attempt(attempt=attempt)
    grade = AssessmentItemGrade.objects.select_for_update().filter(item=item).first()
    if grade is None:
        raise GradeCorrectionError("The assessment item has no current grade result.")
    return grade


def _append_decision(*, attempt, item, grade, actor, reason, source, rule_version, now) -> AssessmentGradeDecision:
    return AssessmentGradeDecision.objects.create(
        attempt=attempt,
        item=item,
        status=grade.status,
        normalized_score=grade.normalized_score,
        possible_points=grade.possible_points,
        awarded_points=grade.awarded_points,
        retained_answer=deepcopy(grade.retained_answer),
        source=source,
        rule_version=rule_version,
        diagnostic_code=grade.diagnostic_code,
        comment=grade.comment,
        actor=actor,
        reason=reason,
        created_at=now,
    )


def _same_override(*, grade, actor, reason, comment, score) -> bool:
    if grade.source != CORRECTION_SOURCE or grade.normalized_score != score or grade.comment != comment:
        return False
    latest = (
        AssessmentGradeDecision.objects.filter(item_id=grade.item_id, source=CORRECTION_SOURCE)
        .order_by("-created_at", "-id")
        .first()
    )
    return latest is not None and latest.actor_id == actor.pk and latest.reason == reason


def _package_run_scope(actor, run: AssessmentRun) -> bool:
    """Return the package-owned staff scope for a run before host policy."""
    if not getattr(actor, "is_authenticated", False) or not can_teach(actor):
        return False
    if getattr(actor, "is_superuser", False) or run.owner_id == actor.pk:
        return True
    course = getattr(run, "course", None)
    if course is None:
        return False
    if course.created_by_id == actor.pk:
        return True
    from liveclassroom.models import CourseMembership

    return CourseMembership.objects.filter(
        course=course,
        user=actor,
        role__in=(CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT),
    ).exists()


def _can_manage_run(actor, run: AssessmentRun) -> bool:
    return host_can_manage_assessment_results(
        actor=actor,
        run_id=run.pk,
        package_allowed=_package_run_scope(actor, run),
    )


def _latest_answer(item: AssessmentAttemptItem):
    revision = AnswerRevision.objects.filter(item=item).order_by("-version", "-id").first()
    return deepcopy(revision.answer) if revision is not None else None


def _grade_state(item: AssessmentAttemptItem) -> dict[str, Any]:
    """Read current grade state without materializing a missing grade row."""
    grade = AssessmentItemGrade.objects.filter(item=item).first()
    if grade is not None:
        return {
            "status": grade.status,
            "normalized_score": grade.normalized_score,
            "possible_points": grade.possible_points,
            "awarded_points": grade.awarded_points,
            "retained_answer": deepcopy(grade.retained_answer),
            "source": grade.source,
            "rule_version": grade.rule_version,
            "diagnostic_code": grade.diagnostic_code,
            "comment": grade.comment,
        }
    result = score_retained_item(
        {**(deepcopy(item.manifest) if isinstance(item.manifest, dict) else {}), "possible_points": item.points},
        answer=_latest_answer(item),
    )
    return {
        "status": result["status"],
        "normalized_score": result["normalized_score"],
        "possible_points": item.points,
        "awarded_points": result["awarded_points"],
        "retained_answer": deepcopy(result["retained_answer"]),
        "source": result.get("source", "automatic"),
        "rule_version": result.get("rule_version", RULE_VERSION),
        "diagnostic_code": result.get("diagnostic_code", ""),
        "comment": "",
    }


def _state_payload(state: dict[str, Any]) -> dict[str, Any]:
    quanta = {
        "normalized_score": Decimal("0.0000000001"),
        "possible_points": Decimal("0.000001"),
        "awarded_points": Decimal("0.01"),
    }
    def _text(key, value):
        if not isinstance(value, Decimal):
            return deepcopy(value)
        quantum = quanta.get(key)
        return format(value.quantize(quantum, rounding=ROUND_HALF_UP) if quantum else value, "f")

    return {
        key: _text(key, value)
        for key, value in state.items()
        if key in {
            "status", "normalized_score", "possible_points", "awarded_points", "retained_answer",
            "source", "rule_version", "diagnostic_code", "comment",
        }
    }


def _state_changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    return _state_payload(old) != _state_payload(new)


def _preview_rule_revisions(
    *,
    run: AssessmentRun,
    attempts: list[AssessmentAttempt],
    keys: set[UUID] | None,
    rule_version: str,
    rule_config: dict[str, Any] | None,
) -> dict[UUID, dict[str, Any]]:
    """Resolve a preview's grading patches without creating revisions."""
    representatives = _revision_items(attempts, keys)
    if not representatives or rule_version == RULE_VERSION:
        return {}
    if rule_config is not None:
        return {
            item_key: _validated_rule_for_item(item, rule_config)
            for item_key, item in representatives.items()
        }
    revisions = GradingRuleRevision.objects.filter(
        run=run,
        item_key__in=representatives,
        rule_version=rule_version,
        approved_at__isnull=False,
    ).order_by("item_key", "-version")
    resolved: dict[UUID, dict[str, Any]] = {}
    for revision in revisions:
        if revision.item_key in resolved:
            continue
        resolved[revision.item_key] = _validated_rule_for_item(
            representatives[revision.item_key], revision.configuration
        )
    missing = set(representatives) - set(resolved)
    if missing:
        raise GradeCorrectionError("No approved grading rule revision exists for the selected items.")
    return resolved


def _fingerprint_payload(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def item_grade_fingerprint(*, attempt_item: AssessmentAttemptItem) -> str:
    """Fingerprint one retained item and its current grade for stale overrides."""
    item = AssessmentAttemptItem.objects.select_related("attempt", "attempt__run").get(pk=attempt_item.pk)
    state = _grade_state(item)
    return _fingerprint_payload(
        {
            "version": "grade-state-v1",
            "attempt_id": str(item.attempt.public_id),
            "item_key": str(item.key),
            "manifest": item.manifest,
            "state": _state_payload(state),
            "answer": state.get("retained_answer"),
        }
    )


def preview_regrade(
    *,
    run: AssessmentRun,
    item_keys=None,
    rule_version: str,
    actor,
    reason: str,
    rule_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a non-persistent regrade preview for every submitted attempt."""
    reason = _reason(reason)
    version = _rule_version(rule_version, rule_config)
    keys = _item_key_set(item_keys)
    if not getattr(run, "pk", None):
        raise GradeCorrectionError("run must be a saved assessment run.")
    if not _can_manage_run(actor, run):
        raise GradeCorrectionError("You do not have permission to regrade this run.")
    attempts = list(
        AssessmentAttempt.objects.filter(run=run, status=AssessmentAttempt.Status.SUBMITTED)
        .select_related("run", "run__course", "user")
        .prefetch_related("items")
        .order_by("id")
    )
    if any(not can_grade_attempt(actor, attempt) for attempt in attempts):
        raise GradeCorrectionError("You do not have permission to regrade this run.")
    all_items = [item for attempt in attempts for item in attempt.items.all()]
    available_keys = {item.key for item in all_items}
    if keys is not None and not keys.issubset(available_keys):
        raise GradeCorrectionError("One or more selected item keys were not found in this run.")
    patches = _preview_rule_revisions(
        run=run, attempts=attempts, keys=keys, rule_version=version, rule_config=rule_config
    )
    rows: list[dict[str, Any]] = []
    counts = {"scanned": 0, "changed": 0, "unchanged": 0, "ungraded": 0, "failed": 0, "preserved_manual": 0}
    fingerprint_items = []
    for attempt in attempts:
        for item in attempt.items.all():
            if keys is not None and item.key not in keys:
                continue
            counts["scanned"] += 1
            old = _grade_state(item)
            preserved = old["source"] in PRESERVED_SOURCES
            if preserved:
                new = old
                counts["preserved_manual"] += 1
            elif not _objective(item):
                new = old
                counts["unchanged"] += 1
            else:
                patch = patches.get(item.key, {}) if version != RULE_VERSION else {}
                new_result = _regrade_payload(
                    item,
                    type("GradeView", (), {"retained_answer": old["retained_answer"]})(),
                    patch,
                )
                new = {
                    "status": new_result["status"],
                    "normalized_score": new_result["normalized_score"],
                    "possible_points": item.points,
                    "awarded_points": new_result["awarded_points"],
                    "retained_answer": deepcopy(old["retained_answer"]),
                    "source": "automatic",
                    "rule_version": version,
                    "diagnostic_code": new_result["diagnostic_code"],
                    "comment": old["comment"],
                }
                if new["status"] in {AssessmentItemGrade.Status.UNGRADED, AssessmentItemGrade.Status.ERROR}:
                    counts["ungraded"] += 1
            changed = _state_changed(old, new)
            if changed and not preserved:
                counts["changed"] += 1
            elif not preserved and not changed:
                counts["unchanged"] += 1
            rows.append(
                {
                    "attempt_id": str(attempt.public_id),
                    "item_key": str(item.key),
                    "old": _state_payload(old),
                    "new": _state_payload(new),
                    "old_result": _state_payload(old),
                    "new_result": _state_payload(new),
                    "old_score": _state_payload(old)["normalized_score"],
                    "new_score": _state_payload(new)["normalized_score"],
                    "changed": changed and not preserved,
                    "preserved_manual": preserved,
                }
            )
            fingerprint_items.append(
                {
                    "attempt_id": str(attempt.public_id),
                    "item_key": str(item.key),
                    "manifest": item.manifest,
                    "state": _state_payload(old),
                }
            )
    fingerprint = _fingerprint_payload(
        {
            "version": "regrade-preview-v1",
            "run_id": str(run.public_id),
            "item_keys": sorted(str(key) for key in keys) if keys is not None else None,
            "rule_version": version,
            "rule_config": rule_config,
            "reason": reason,
            "items": fingerprint_items,
        }
    )
    counts["affected"] = counts["changed"]
    counts["affected_count"] = counts["changed"]
    return {
        "preview_fingerprint": fingerprint,
        "run_id": str(run.public_id),
        "rule_version": version,
        "reason": reason,
        "items": rows,
        "counts": counts,
    }


@transaction.atomic
def override_item_grade(
    *,
    attempt_item: AssessmentAttemptItem,
    normalized_score,
    comment: str = "",
    actor,
    reason: str,
    now: datetime | None = None,
) -> AssessmentItemGrade:
    """Apply one explicit human correction to one submitted attempt item."""
    score = _score(normalized_score)
    reason = _reason(reason)
    comment = _comment(comment)
    attempt, item = _locked_item(attempt_item)
    if not _can_manage_run(actor, attempt.run):
        raise GradeCorrectionError("You do not have permission to correct this attempt.")
    if not can_grade_attempt(actor, attempt):
        raise GradeCorrectionError("You do not have permission to correct this attempt.")
    if attempt.status != AssessmentAttempt.Status.SUBMITTED:
        raise GradeCorrectionError("Only a submitted attempt can be corrected.")
    grade = _ensure_current_grade(attempt, item)
    if _same_override(grade=grade, actor=actor, reason=reason, comment=comment, score=score):
        return grade
    current = _aware_now(now)
    awarded = (score * Decimal(str(item.points))).quantize(POINT_QUANTUM, rounding=ROUND_HALF_UP)
    grade.status = AssessmentItemGrade.Status.GRADED
    grade.normalized_score = score
    grade.possible_points = item.points
    grade.awarded_points = awarded
    grade.source = CORRECTION_SOURCE
    grade.rule_version = OVERRIDE_RULE_VERSION
    grade.diagnostic_code = ""
    grade.comment = comment
    grade.graded_at = current
    grade.save(
        update_fields=[
            "status", "normalized_score", "possible_points", "awarded_points", "source",
            "rule_version", "diagnostic_code", "comment", "graded_at", "updated_at",
        ]
    )
    _append_decision(
        attempt=attempt,
        item=item,
        grade=grade,
        actor=actor,
        reason=reason,
        source=CORRECTION_SOURCE,
        rule_version=OVERRIDE_RULE_VERSION,
        now=current,
    )
    from .assessment_grading import recompute_attempt_grade

    recompute_attempt_grade(attempt=attempt, now=current)
    return grade


def _rule_version(value: Any, rule_config: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GradeCorrectionError("rule_version is required.")
    version = value.strip()
    if version == RULE_VERSION:
        if rule_config not in (None, {}, []):
            raise GradeCorrectionError("The default rule version cannot carry a correction configuration.")
        return version
    if not version.startswith("activity-registry-v") or not version.removeprefix("activity-registry-v").isdigit():
        raise GradeCorrectionError("rule_version is not an approved activity registry rule.")
    if rule_config is not None and (not isinstance(rule_config, dict) or not rule_config):
        raise GradeCorrectionError("A corrected rule configuration is required for this rule version.")
    return version


def _item_key_set(item_keys) -> set[UUID] | None:
    if item_keys is None:
        return None
    if isinstance(item_keys, (str, UUID)):
        item_keys = [item_keys]
    if not isinstance(item_keys, (list, tuple, set, frozenset)):
        raise GradeCorrectionError("item_keys must be a sequence of item keys.")
    result = set()
    for value in item_keys:
        try:
            result.add(UUID(str(value)))
        except (AttributeError, TypeError, ValueError) as exc:
            raise GradeCorrectionError("item_keys must contain UUIDs.") from exc
    return result


def _rule_for_item(rule_config: dict[str, Any], item: AssessmentAttemptItem) -> dict[str, Any]:
    """Resolve a grading-only patch without changing prompt/options/points."""
    raw = rule_config.get(str(item.key), rule_config.get("default", rule_config))
    if not isinstance(raw, dict):
        raise GradeCorrectionError("The corrected rule must be an object.")
    if "definition" in raw:
        definition = raw["definition"]
        if not isinstance(definition, dict):
            raise GradeCorrectionError("The corrected rule definition must be an object.")
        raw = definition
    try:
        GradingRuleRevision.validate_configuration(raw)
    except ValueError as exc:
        raise GradeCorrectionError(str(exc)) from exc
    return deepcopy(raw)


def _validated_rule_for_item(item: AssessmentAttemptItem, rule_config: dict[str, Any]) -> dict[str, Any]:
    """Validate a grading-only patch against the retained activity definition."""
    patch = _rule_for_item(rule_config, item)
    payload = item.manifest if isinstance(item.manifest, dict) else {}
    type_key = payload.get("type_key")
    if isinstance(type_key, str) and "." not in type_key:
        type_key = f"liveclassroom.{type_key}"
    definition = payload.get("definition", payload.get("payload"))
    if not isinstance(type_key, str) or not isinstance(definition, dict):
        raise GradeCorrectionError("The retained item has no grading definition.")
    try:
        from liveclassroom.registry import activity_registry

        activity_type = activity_registry.get(type_key)
        activity_type.validate({**deepcopy(definition), **deepcopy(patch)})
    except (KeyError, TypeError, ValueError) as exc:
        raise GradeCorrectionError(f"The corrected grading rule is invalid: {exc}") from exc
    return patch


def _regrade_payload(item: AssessmentAttemptItem, grade: AssessmentItemGrade, patch: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(item.manifest) if isinstance(item.manifest, dict) else {}
    definition_key = "definition" if "definition" in payload else "payload"
    definition = payload.get(definition_key)
    if not isinstance(definition, dict):
        raise GradeCorrectionError("The retained item has no grading definition.")
    corrected = deepcopy(definition)
    corrected.update(patch)
    payload[definition_key] = corrected
    payload["possible_points"] = str(item.points)
    return score_retained_item(payload, answer=deepcopy(grade.retained_answer))


def _objective(item: AssessmentAttemptItem) -> bool:
    payload = item.manifest if isinstance(item.manifest, dict) else {}
    type_key = payload.get("type_key")
    if isinstance(type_key, str) and "." not in type_key:
        type_key = f"liveclassroom.{type_key}"
    if not isinstance(type_key, str):
        return False
    try:
        from liveclassroom.registry import activity_registry

        descriptor = activity_registry.get(type_key)
    except KeyError:
        return False
    return "correctness" in descriptor.capabilities and "manual" not in descriptor.capabilities


def _same_result(grade: AssessmentItemGrade, result: dict[str, Any], rule_version: str) -> bool:
    return (
        grade.status == result["status"]
        and grade.normalized_score == result["normalized_score"]
        and grade.awarded_points == result["awarded_points"]
        and grade.rule_version == rule_version
        and grade.diagnostic_code == result["diagnostic_code"]
    )


def _revision_items(attempts: list[AssessmentAttempt], keys: set[UUID] | None) -> dict[UUID, AssessmentAttemptItem]:
    """Return one retained representative for each objective item key."""
    representatives: dict[UUID, AssessmentAttemptItem] = {}
    for attempt in attempts:
        for item in attempt.items.all():
            if keys is not None and item.key not in keys:
                continue
            if item.key not in representatives and _objective(item):
                representatives[item.key] = item
    return representatives


def _prepare_rule_revisions(
    *,
    run: AssessmentRun,
    attempts: list[AssessmentAttempt],
    keys: set[UUID] | None,
    rule_version: str,
    rule_config: dict[str, Any] | None,
    actor,
    reason: str,
    now: datetime | None,
) -> dict[UUID, dict[str, Any]]:
    """Create or resolve approved revisions before changing any grade rows."""
    representatives = _revision_items(attempts, keys)
    if not representatives:
        return {}
    if rule_config is None:
        revisions = GradingRuleRevision.objects.filter(
            run=run,
            item_key__in=representatives,
            rule_version=rule_version,
            approved_at__isnull=False,
        ).order_by("item_key", "-version")
        resolved: dict[UUID, dict[str, Any]] = {}
        for revision in revisions:
            if revision.item_key not in resolved:
                try:
                    resolved[revision.item_key] = _validated_rule_for_item(
                        representatives[revision.item_key], revision.configuration
                    )
                except ValueError as exc:
                    raise GradeCorrectionError("The approved grading rule configuration is invalid.") from exc
        missing = set(representatives) - set(resolved)
        if missing:
            raise GradeCorrectionError("No approved grading rule revision exists for the selected items.")
        return resolved

    locked_run = AssessmentRun.objects.select_for_update().get(pk=run.pk)
    del locked_run
    current = _aware_now(now)
    resolved = {}
    for item_key, item in representatives.items():
        patch = _validated_rule_for_item(item, rule_config)
        latest = (
            GradingRuleRevision.objects.filter(run=run, item_key=item_key)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        revision = GradingRuleRevision(
            run=run,
            item_key=item_key,
            rule_version=rule_version,
            version=(latest or 0) + 1,
            configuration=patch,
            created_by=actor,
            reason=reason,
            approved_at=current,
            created_at=current,
        )
        try:
            revision.full_clean()
        except Exception as exc:
            raise GradeCorrectionError(f"The corrected grading rule is invalid: {exc}") from exc
        revision.save(force_insert=True)
        resolved[item_key] = patch
    return resolved


@transaction.atomic
def regrade_attempts(
    *,
    run: AssessmentRun,
    item_keys=None,
    rule_version: str,
    actor,
    reason: str,
    rule_config: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
    now: datetime | None = None,
    strict: bool = False,
) -> dict[str, int]:
    """Regrade explicitly selected objective items from retained answers.

    ``rule_config`` is optional for the approved current registry rule.  For a
    new version it creates an approved persisted revision; when omitted, the
    latest approved revision for each selected retained item is resolved.  A
    supplied configuration may contain only grading fields, optionally keyed
    by retained item UUID.  The source run manifest is never modified.
    Manual and previous override results are preserved.
    """
    reason = _reason(reason)
    if rules is not None and rule_config is not None:
        raise GradeCorrectionError("Provide rule_config or rules, not both.")
    config = rules if rules is not None else (rule_config or {})
    supplied_config = rules if rules is not None else rule_config
    version = _rule_version(rule_version, supplied_config)
    keys = _item_key_set(item_keys)
    if not getattr(run, "pk", None):
        raise GradeCorrectionError("run must be a saved assessment run.")
    if not getattr(actor, "is_authenticated", False):
        raise GradeCorrectionError("Teacher grading access is required.")
    if not _can_manage_run(actor, run):
        raise GradeCorrectionError("You do not have permission to regrade this run.")
    # Run ownership/course staff is checked through each concrete attempt so
    # the same routine cannot accidentally cross a student's account boundary.
    attempts = list(
        AssessmentAttempt.objects.filter(run=run, status=AssessmentAttempt.Status.SUBMITTED)
        .select_related("run", "run__course", "user")
        .order_by("id")
    )
    counts = {"scanned": 0, "changed": 0, "unchanged": 0, "ungraded": 0, "failed": 0, "preserved_manual": 0}
    authorized = all(can_grade_attempt(actor, reference) for reference in attempts)
    if attempts and not authorized:
        if strict:
            raise GradeCorrectionError("You do not have permission to regrade this run.")
        counts["scanned"] = len(attempts)
        counts["failed"] = len(attempts)
        return counts
    revisions = {}
    if version != RULE_VERSION:
        revisions = _prepare_rule_revisions(
            run=run,
            attempts=attempts,
            keys=keys,
            rule_version=version,
            rule_config=(config if supplied_config is not None else None),
            actor=actor,
            reason=reason,
            now=now,
        )
    for reference in attempts:
        counts["scanned"] += 1
        try:
            if not can_grade_attempt(actor, reference):
                raise GradeCorrectionError("You do not have permission to regrade this run.")
            with transaction.atomic():
                locked_attempt = (
                    AssessmentAttempt.objects.select_for_update(of=("self",))
                    .select_related("run", "run__course", "user")
                    .get(pk=reference.pk)
                )
                items = list(
                    AssessmentAttemptItem.objects.select_for_update()
                    .filter(attempt=locked_attempt)
                    .order_by("position", "id")
                )
                changed = False
                for item in items:
                    if keys is not None and item.key not in keys:
                        continue
                    grade = _ensure_current_grade(locked_attempt, item)
                    if grade.source in {MANUAL_SOURCE, CORRECTION_SOURCE}:
                        counts["preserved_manual"] += 1
                        continue
                    if not _objective(item):
                        counts["unchanged"] += 1
                        continue
                    patch = revisions.get(item.key, {}) if version != RULE_VERSION else {}
                    result = _regrade_payload(item, grade, patch)
                    if result["status"] in {AssessmentItemGrade.Status.UNGRADED, AssessmentItemGrade.Status.ERROR}:
                        counts["ungraded"] += 1
                    if _same_result(grade, result, version):
                        counts["unchanged"] += 1
                        continue
                    current = _aware_now(now)
                    grade.status = result["status"]
                    grade.normalized_score = result["normalized_score"]
                    grade.possible_points = item.points
                    grade.awarded_points = result["awarded_points"]
                    grade.retained_answer = deepcopy(grade.retained_answer)
                    grade.source = "automatic"
                    grade.rule_version = version
                    grade.diagnostic_code = result["diagnostic_code"]
                    grade.graded_at = current
                    grade.save(
                        update_fields=[
                            "status", "normalized_score", "possible_points", "awarded_points",
                            "retained_answer", "source", "rule_version", "diagnostic_code",
                            "graded_at", "updated_at",
                        ]
                    )
                    _append_decision(
                        attempt=locked_attempt,
                        item=item,
                        grade=grade,
                        actor=actor,
                        reason=reason,
                        source=REGRADE_SOURCE,
                        rule_version=version,
                        now=current,
                    )
                    counts["changed"] += 1
                    changed = True
                rows = list(AssessmentItemGrade.objects.filter(item__attempt=locked_attempt).order_by("item_id"))
                _aggregate(locked_attempt, rows, _aware_now(now))
                del changed
        except GradeCorrectionError:
            if strict:
                raise
            counts["failed"] += 1
        except Exception:
            # A malformed retained plugin/item is an explicit failed regrade;
            # another student's attempt must continue independently.
            if strict:
                raise GradeCorrectionError("The regrade could not be applied safely.")
            counts["failed"] += 1
    return counts


__all__ = [
    "CORRECTION_SOURCE",
    "GradeCorrectionError",
    "OVERRIDE_RULE_VERSION",
    "PRESERVED_SOURCES",
    "item_grade_fingerprint",
    "REGRADE_SOURCE",
    "override_item_grade",
    "preview_regrade",
    "regrade_attempts",
]
