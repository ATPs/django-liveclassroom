"""Mount-safe staff endpoints for retained question analytics."""

from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .api import _error
from .services.question_analytics import (
    QuestionAnalyticsError,
    course_question_analytics,
    question_analytics,
)


def _include_named(request) -> bool:
    value = request.GET.get("include_named", request.GET.get("named", "false"))
    if isinstance(value, str):
        lowered = value.casefold()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no", ""}:
            return False
    raise QuestionAnalyticsError("include_named must be a boolean.")


def _response(request, action):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    try:
        payload = action(include_named=_include_named(request))
    except QuestionAnalyticsError as exc:
        message = str(exc)
        if "must be a boolean" in message or "class_id must" in message:
            return _error(message, 400, code="invalid_request")
        if "permission" in message.casefold():
            return _error("Not found.", 404, code="not_found")
        return _error("Not found.", 404, code="not_found")
    return JsonResponse(payload)


@require_GET
def assessment_run_question_analytics(request, public_id):
    """Return aggregate outcomes for one immutable assessment run."""
    return _response(request, lambda *, include_named: question_analytics(
        request.user, public_id, include_named=include_named
    ))


@require_GET
def class_question_analytics(request, class_id: int):
    """Return run-separated outcomes and participation trends for a class."""
    return _response(request, lambda *, include_named: course_question_analytics(
        request.user, class_id, include_named=include_named
    ))


course_question_analytics_view = class_question_analytics


__all__ = [
    "assessment_run_question_analytics",
    "class_question_analytics",
    "course_question_analytics_view",
]
