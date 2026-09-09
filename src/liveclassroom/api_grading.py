"""Mount-safe staff APIs for the pending manual-grading queue."""

from __future__ import annotations

from decimal import Decimal, DecimalException
from uuid import UUID

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .api import _body, _error
from .models import AssessmentAttempt, AssessmentAttemptItem
from .services.classroom import ClassroomError
from .services.manual_grading import (
    COMMENT_MAX_LENGTH,
    ManualGradingError,
    list_manual_grading_items,
    save_manual_grade,
)


def _staff(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    return None


def _decimal_text(value):
    if value is None:
        return None
    return format(value, "f")


def _json_value(value):
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, dict):
        return {key: _json_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_value(child) for child in value]
    return value


def _queue_item_payload(item):
    return _json_value(item)


@require_http_methods(["GET"])
def grading_queue(request):
    """Return pending subjective items visible to this teacher or assistant."""
    denied = _staff(request)
    if denied is not None:
        return denied
    try:
        rows = list_manual_grading_items(
            request.user,
            run_id=request.GET.get("run_id"),
            class_id=request.GET.get("class_id"),
        )
    except ManualGradingError as exc:
        return _error(str(exc), 403 if "permission" in str(exc).casefold() or "teacher" in str(exc).casefold() else 400)
    return JsonResponse({"items": [_queue_item_payload(row) for row in rows], "count": len(rows)})


def _item_for_public_ids(public_id, item_key):
    try:
        item_uuid = UUID(str(item_key))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ManualGradingError("item_key must be a UUID.") from exc
    try:
        return AssessmentAttemptItem.objects.select_related("attempt").get(
            attempt__public_id=public_id,
            key=item_uuid,
        )
    except AssessmentAttemptItem.DoesNotExist as exc:
        raise ManualGradingError("The assessment item was not found.") from exc


def _normalized_from_body(body, item: AssessmentAttemptItem):
    if "normalized_score" in body and "awarded_points" in body:
        raise ManualGradingError("Provide normalized_score or awarded_points, not both.")
    if "normalized_score" in body:
        return body["normalized_score"]
    if "awarded_points" not in body:
        raise ManualGradingError("normalized_score is required.")
    try:
        awarded = Decimal(str(body["awarded_points"]))
        possible = Decimal(str(item.points))
    except (DecimalException, TypeError, ValueError) as exc:
        raise ManualGradingError("awarded_points must be a finite decimal.") from exc
    if not awarded.is_finite() or awarded < 0 or awarded > possible:
        raise ManualGradingError("awarded_points must be within the possible points.")
    return awarded / possible


@require_http_methods(["POST"])
def manual_grade(request, public_id, item_key):
    """Save one explicit normalized score; awarded-points input is also accepted."""
    denied = _staff(request)
    if denied is not None:
        return denied
    try:
        body = _body(request)
        allowed = {"normalized_score", "awarded_points", "comment", "reason", "request_id"}
        if set(body) - allowed:
            raise ManualGradingError("Only score, comment, reason and request_id are accepted.")
        comment = body.get("comment", "")
        if comment is not None and (not isinstance(comment, str) or len(comment) > COMMENT_MAX_LENGTH):
            raise ManualGradingError(f"comment must be at most {COMMENT_MAX_LENGTH} characters.")
        item = _item_for_public_ids(public_id, item_key)
        score = _normalized_from_body(body, item)
        grade = save_manual_grade(
            attempt_item=item,
            normalized_score=score,
            comment=comment or "",
            actor=request.user,
            reason=body.get("reason", ""),
        )
    except ManualGradingError as exc:
        message = str(exc)
        lowered = message.casefold()
        status = 403 if any(word in lowered for word in ("permission", "teacher", "access")) else 400
        if "not found" in lowered:
            status = 404
        return _error(message, status, code="permission_denied" if status == 403 else "invalid_request")
    except (AssessmentAttempt.DoesNotExist, ClassroomError) as exc:
        return _error(str(exc), 400)
    return JsonResponse(
        {
            "attempt_id": str(grade.item.attempt.public_id),
            "item_key": str(grade.item.key),
            "status": grade.status,
            "normalized_score": _decimal_text(grade.normalized_score),
            "possible_points": _decimal_text(grade.possible_points),
            "awarded_points": _decimal_text(grade.awarded_points),
            "comment": grade.comment,
            "source": grade.source,
            "rule_version": grade.rule_version,
        }
    )


__all__ = ["grading_queue", "manual_grade"]
