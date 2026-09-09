"""Start and resume independent attempts from immutable run manifests."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from liveclassroom.models import (
    AssessmentAttempt,
    AssessmentAttemptItem,
    AssessmentRun,
    AttemptStartReceipt,
    CourseMembership,
)

from .classroom import ClassroomError


def _request_uuid(value) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ClassroomError("request_id must be a UUID.") from exc


def _hash_request(*, new_attempt: bool) -> str:
    return hashlib.sha256(json.dumps({"new_attempt": new_attempt}, sort_keys=True).encode()).hexdigest()


def _can_access(actor, run: AssessmentRun) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    if run.audience == AssessmentRun.Audience.AUTHENTICATED_LINK:
        return True
    return bool(
        run.course_id
        and CourseMembership.objects.filter(
            course_id=run.course_id, user=actor, role=CourseMembership.Role.STUDENT
        ).exists()
    )


def _limit(run: AssessmentRun) -> int | None:
    settings = run.manifest.get("settings", {}) if isinstance(run.manifest, dict) else {}
    value = settings.get("max_attempts", 1) if isinstance(settings, dict) else 1
    if value is None:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else 1


def _item_rows(run: AssessmentRun) -> list[AssessmentAttemptItem]:
    manifest = run.manifest if isinstance(run.manifest, dict) else {}
    source_items = manifest.get("items") if isinstance(manifest, dict) else None
    if not isinstance(source_items, list) or not source_items:
        raise ClassroomError("The published assessment has no usable questions.")
    rows = []
    for position, item in enumerate(source_items, 1):
        if not isinstance(item, dict):
            raise ClassroomError("The published assessment is invalid.")
        try:
            key = UUID(str(item["key"]))
            points = Decimal(str(item["points"]))
        except (KeyError, ValueError, ArithmeticError) as exc:
            raise ClassroomError("The published assessment is invalid.") from exc
        if not points.is_finite() or points <= 0:
            raise ClassroomError("The published assessment is invalid.")
        rows.append(AssessmentAttemptItem(key=key, position=position, points=points, manifest=deepcopy(item)))
    return rows


@transaction.atomic
def start_or_resume_attempt(
    *, actor, run: AssessmentRun, request_id, new_attempt: bool = False
) -> tuple[AssessmentAttempt, bool]:
    """Return an active attempt, or create a deliberately requested next one."""
    if not isinstance(new_attempt, bool):
        raise ClassroomError("new_attempt must be a boolean.")
    request_id = _request_uuid(request_id)
    locked_run = AssessmentRun.objects.select_for_update().get(pk=run.pk)
    if not _can_access(actor, locked_run):
        raise ClassroomError("You do not have access to this assessment.")
    request_hash = _hash_request(new_attempt=new_attempt)
    receipt = (
        AttemptStartReceipt.objects.filter(run=locked_run, user=actor, request_id=request_id)
        .select_related("attempt")
        .first()
    )
    if receipt is not None:
        if receipt.request_hash != request_hash:
            raise ClassroomError("This request_id was already used with different input.")
        if receipt.attempt is None:
            raise ClassroomError("The start request did not complete; retry with a new request_id.")
        return receipt.attempt, False
    active = (
        AssessmentAttempt.objects.select_for_update()
        .filter(run=locked_run, user=actor, status=AssessmentAttempt.Status.IN_PROGRESS)
        .first()
    )
    if active is not None:
        AttemptStartReceipt.objects.create(
            run=locked_run, user=actor, request_id=request_id, request_hash=request_hash, attempt=active
        )
        return active, False
    latest = (
        AssessmentAttempt.objects.select_for_update()
        .filter(run=locked_run, user=actor)
        .order_by("-attempt_number")
        .first()
    )
    if latest is not None and not new_attempt:
        AttemptStartReceipt.objects.create(
            run=locked_run, user=actor, request_id=request_id, request_hash=request_hash, attempt=latest
        )
        return latest, False
    number = (latest.attempt_number if latest is not None else 0) + 1
    maximum = _limit(locked_run)
    if maximum is not None and number > maximum:
        raise ClassroomError("No attempts remain for this assessment.")
    try:
        attempt = AssessmentAttempt.objects.create(run=locked_run, user=actor, attempt_number=number)
    except IntegrityError as exc:
        # The database constraints are the concurrency backstop on SQLite and PostgreSQL.
        active = AssessmentAttempt.objects.filter(
            run=locked_run, user=actor, status=AssessmentAttempt.Status.IN_PROGRESS
        ).first()
        if active is not None:
            return active, False
        raise ClassroomError("The attempt changed concurrently; retry.") from exc
    rows = _item_rows(locked_run)
    for row in rows:
        row.attempt = attempt
    AssessmentAttemptItem.objects.bulk_create(rows)
    AttemptStartReceipt.objects.create(
        run=locked_run, user=actor, request_id=request_id, request_hash=request_hash, attempt=attempt
    )
    return attempt, True


def _public_manifest(item: AssessmentAttemptItem) -> dict:
    source = item.manifest if isinstance(item.manifest, dict) else {}
    payload = deepcopy(source.get("payload", {}))

    def redact(value):
        if isinstance(value, dict):
            return {
                key: redact(child)
                for key, child in value.items()
                if key not in {"answer", "correct_answer", "explanation", "explanation_markdown", "feedback"}
            }
        if isinstance(value, list):
            return [redact(child) for child in value]
        return value

    return {
        "key": str(item.key),
        "position": item.position,
        "points": format(item.points.normalize(), "f"),
        "type_key": source.get("type_key"),
        "schema_version": source.get("schema_version"),
        "payload": redact(payload),
        "metadata": redact(deepcopy(source.get("metadata", {}))),
        "asset_id": source.get("asset_id"),
        "answer_version": 0,
        "answer": None,
    }


def attempt_payload(attempt: AssessmentAttempt) -> dict:
    return {
        "id": str(attempt.public_id),
        "run_id": str(attempt.run.public_id),
        "attempt_number": attempt.attempt_number,
        "status": attempt.status,
        "started_at": attempt.started_at.isoformat(),
        "deadline_at": attempt.deadline_at.isoformat() if attempt.deadline_at else None,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "server_now": timezone.now().isoformat(),
        "items": [_public_manifest(item) for item in attempt.items.all()],
    }


def own_attempt(actor, public_id) -> AssessmentAttempt:
    try:
        attempt = (
            AssessmentAttempt.objects.prefetch_related("items")
            .select_related("run")
            .get(public_id=public_id, user=actor)
        )
    except AssessmentAttempt.DoesNotExist as exc:
        raise ClassroomError("Attempt not found.") from exc
    if not _can_access(actor, attempt.run):
        raise ClassroomError("You do not have access to this assessment.")
    return attempt
