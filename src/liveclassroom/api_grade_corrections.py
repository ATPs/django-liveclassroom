"""Audited grade-correction and regrade HTTP adapters.

The adapters deliberately contain no scoring rules.  They validate the
request envelope, bind retries to the authenticated teacher, and delegate all
grade mutations to :mod:`liveclassroom.services.grade_corrections`.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from uuid import UUID

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .api import _body, _error
from .models import (
    AssessmentAttemptItem,
    AssessmentGradeDecision,
    AssessmentRun,
    AuthoringCommandReceipt,
)
from .services.classroom import ClassroomError
from .services.grade_corrections import (
    GradeCorrectionError,
    item_grade_fingerprint,
    override_item_grade,
    preview_regrade,
    regrade_attempts,
)


class _StaleCorrection(GradeCorrectionError):
    """The client preview/fingerprint no longer describes current state."""


def _authenticated(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    return None


def _jsonable(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(child) for child in value]
    return value


def _request_hash(*, action: str, target: str, body: dict) -> str:
    canonical = {
        "action": action,
        "target": target,
        "body": {key: value for key, value in body.items() if key != "idempotency_key"},
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _key(body: dict) -> str:
    value = body.get("idempotency_key")
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 160:
        raise GradeCorrectionError("idempotency_key must be non-empty text of at most 160 characters.")
    return value.strip()


def _receipt_replay(*, actor, key: str, command_type: str, request_hash: str):
    receipt = AuthoringCommandReceipt.objects.select_for_update().filter(
        owner=actor, idempotency_key=key
    ).first()
    if receipt is None:
        return None
    if receipt.command_type != command_type or receipt.request_hash != request_hash:
        return _error(
            "This idempotency key was already used with different input.",
            409,
            code="idempotency_conflict",
        )
    response = JsonResponse(receipt.response, status=receipt.status_code)
    response["Idempotent-Replay"] = "true"
    return response


def _item(attempt_id, item_key):
    try:
        attempt_uuid = UUID(str(attempt_id))
        item_uuid = UUID(str(item_key))
    except (AttributeError, TypeError, ValueError) as exc:
        raise GradeCorrectionError("The assessment item was not found.") from exc
    try:
        return AssessmentAttemptItem.objects.select_related(
            "attempt", "attempt__run", "attempt__run__course", "attempt__user"
        ).get(attempt__public_id=attempt_uuid, key=item_uuid)
    except AssessmentAttemptItem.DoesNotExist as exc:
        raise GradeCorrectionError("The assessment item was not found.") from exc


def _run(run_id):
    try:
        return AssessmentRun.objects.select_related("course").get(public_id=UUID(str(run_id)))
    except (AssessmentRun.DoesNotExist, AttributeError, TypeError, ValueError) as exc:
        raise GradeCorrectionError("The assessment run was not found.") from exc


def _grade_payload(grade, *, decision=None, fingerprint=None):
    payload = {
        "attempt_id": str(grade.item.attempt.public_id),
        "item_key": str(grade.item.key),
        "status": grade.status,
        "normalized_score": grade.normalized_score,
        "possible_points": grade.possible_points,
        "awarded_points": grade.awarded_points,
        "comment": grade.comment,
        "source": grade.source,
        "rule_version": grade.rule_version,
        "decision_id": decision.pk if decision is not None else None,
        "grade_fingerprint": fingerprint,
    }
    return _jsonable(payload)


def _error_response(exc: Exception):
    message = str(exc)
    lowered = message.casefold()
    if isinstance(exc, _StaleCorrection) or "stale" in lowered or "fingerprint" in lowered and "current" in lowered:
        return _error(message, 409, code="stale_correction")
    if "not found" in lowered:
        return _error(message, 404, code="not_found")
    if "permission" in lowered or "access" in lowered or "teacher" in lowered:
        return _error(message, 403, code="permission_denied")
    return _error(message, 400, code="invalid_request")


@require_http_methods(["POST"])
@csrf_protect
def grade_override(request, attempt_id, item_key):
    """Apply one reasoned manual override with optimistic stale protection."""
    denied = _authenticated(request)
    if denied is not None:
        return denied
    try:
        body = _body(request)
        allowed = {
            "normalized_score", "comment", "reason", "expected_grade_fingerprint", "idempotency_key",
        }
        if set(body) - allowed:
            raise GradeCorrectionError(
                "Only normalized_score, comment, reason, expected_grade_fingerprint and idempotency_key are accepted."
            )
        for required in ("normalized_score", "reason", "expected_grade_fingerprint"):
            if required not in body:
                raise GradeCorrectionError(f"{required} is required.")
        key = _key(body)
        target = f"{attempt_id}/{item_key}"
        request_hash = _request_hash(action="grade-override", target=target, body=body)
        command_type = "assessment.grade_override"
        with transaction.atomic():
            replay = _receipt_replay(
                actor=request.user, key=key, command_type=command_type, request_hash=request_hash
            )
            if replay is not None:
                return replay
            item = _item(attempt_id, item_key)
            locked = AssessmentAttemptItem.objects.select_for_update().get(pk=item.pk)
            actual_fingerprint = item_grade_fingerprint(attempt_item=locked)
            if body["expected_grade_fingerprint"] != actual_fingerprint:
                raise _StaleCorrection("The grade changed; refresh the item and retry with a new fingerprint.")
            grade = override_item_grade(
                attempt_item=locked,
                normalized_score=body["normalized_score"],
                comment=body.get("comment", ""),
                actor=request.user,
                reason=body["reason"],
            )
            decision = AssessmentGradeDecision.objects.filter(
                item=grade.item, source="override", actor=request.user
            ).order_by("-created_at", "-id").first()
            response_payload = {
                "grade": _grade_payload(
                    grade,
                    decision=decision,
                    fingerprint=item_grade_fingerprint(attempt_item=grade.item),
                ),
                "audit_decision_id": decision.pk if decision is not None else None,
                "audit_decision_reference": str(decision.pk) if decision is not None else None,
            }
            AuthoringCommandReceipt.objects.create(
                owner=request.user,
                idempotency_key=key,
                command_type=command_type,
                request_hash=request_hash,
                response=response_payload,
                status_code=200,
            )
        return JsonResponse(_jsonable(response_payload))
    except IntegrityError:
        try:
            key = _key(body)
            request_hash = _request_hash(action="grade-override", target=f"{attempt_id}/{item_key}", body=body)
            with transaction.atomic():
                replay = _receipt_replay(
                    actor=request.user, key=key, command_type="assessment.grade_override", request_hash=request_hash
                )
            if replay is not None:
                return replay
        except GradeCorrectionError:
            pass
        return _error(
            "This idempotency key is already being used; retry the request.",
            409,
            code="idempotency_conflict",
        )
    except (GradeCorrectionError, ClassroomError) as exc:
        return _error_response(exc)


def _regrade_body(body: dict, *, apply: bool) -> tuple[str, dict]:
    allowed = {"item_keys", "rule_version", "rule_config", "reason"}
    if apply:
        allowed |= {"preview_fingerprint", "idempotency_key"}
    if set(body) - allowed:
        raise GradeCorrectionError("The regrade request contains unsupported fields.")
    if "rule_version" not in body or "reason" not in body:
        raise GradeCorrectionError("rule_version and reason are required.")
    config = body.get("rule_config")
    if config is not None and not isinstance(config, dict):
        raise GradeCorrectionError("rule_config must be an object.")
    if apply and "preview_fingerprint" not in body:
        raise GradeCorrectionError("preview_fingerprint is required.")
    key = _key(body) if apply else ""
    return key, {
        "item_keys": body.get("item_keys"),
        "rule_version": body["rule_version"],
        "rule_config": config,
        "reason": body["reason"],
        **({"preview_fingerprint": body["preview_fingerprint"], "idempotency_key": key} if apply else {}),
    }


@require_http_methods(["POST"])
@csrf_protect
def regrade_preview(request, run_id):
    """Preview a run regrade without creating rows or changing grades."""
    denied = _authenticated(request)
    if denied is not None:
        return denied
    try:
        body = _body(request)
        _key_value, payload = _regrade_body(body, apply=False)
        result = preview_regrade(run=_run(run_id), actor=request.user, **payload)
        return JsonResponse(_jsonable(result))
    except (GradeCorrectionError, ClassroomError) as exc:
        return _error_response(exc)


@require_http_methods(["POST"])
@csrf_protect
def regrade_apply(request, run_id):
    """Revalidate and atomically apply a previously previewed regrade."""
    denied = _authenticated(request)
    if denied is not None:
        return denied
    body = {}
    try:
        body = _body(request)
        key, payload = _regrade_body(body, apply=True)
        target = str(run_id)
        request_hash = _request_hash(action="regrade-apply", target=target, body=body)
        command_type = "assessment.regrade_apply"
        with transaction.atomic():
            replay = _receipt_replay(
                actor=request.user, key=key, command_type=command_type, request_hash=request_hash
            )
            if replay is not None:
                return replay
            run = AssessmentRun.objects.select_for_update().select_related("course").get(public_id=UUID(str(run_id)))
            preview = preview_regrade(
                run=run,
                actor=request.user,
                item_keys=payload["item_keys"],
                rule_version=payload["rule_version"],
                rule_config=payload["rule_config"],
                reason=payload["reason"],
            )
            if payload["preview_fingerprint"] != preview["preview_fingerprint"]:
                raise _StaleCorrection("The regrade preview is stale; create a new preview and retry.")
            counts = regrade_attempts(
                run=run,
                item_keys=payload["item_keys"],
                rule_version=payload["rule_version"],
                rule_config=payload["rule_config"],
                actor=request.user,
                reason=payload["reason"],
                strict=True,
            )
            response_payload = {
                "run_id": str(run.public_id),
                "preview_fingerprint": preview["preview_fingerprint"],
                "rule_version": preview["rule_version"],
                "counts": counts,
                "items": preview["items"],
            }
            AuthoringCommandReceipt.objects.create(
                owner=request.user,
                idempotency_key=key,
                command_type=command_type,
                request_hash=request_hash,
                response=_jsonable(response_payload),
                status_code=200,
            )
        return JsonResponse(_jsonable(response_payload))
    except AssessmentRun.DoesNotExist:
        return _error("The assessment run was not found.", 404, code="not_found")
    except IntegrityError:
        return _error(
            "This idempotency key is already being used; retry the request.",
            409,
            code="idempotency_conflict",
        )
    except (GradeCorrectionError, ClassroomError) as exc:
        return _error_response(exc)


# ``override_grade`` is retained as a discoverable alias for hosts that name
# views after the action rather than the endpoint noun.
override_grade = grade_override

__all__ = ["grade_override", "override_grade", "regrade_apply", "regrade_preview"]
