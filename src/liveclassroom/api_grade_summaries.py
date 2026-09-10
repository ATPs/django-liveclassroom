"""Mount-safe teacher endpoints for derived class/course grade summaries."""

from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .api import _error
from .services.grade_summaries import (
    GradeSummaryError,
    class_grade_summary,
    teaching_course_grade_summary,
)


def _teacher(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    return None


def _include_test(request) -> bool:
    value = request.GET.get("include_test", "false")
    if isinstance(value, str):
        lowered = value.casefold()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no", ""}:
            return False
    raise GradeSummaryError("include_test must be a boolean.")


def _summary(request, action):
    denied = _teacher(request)
    if denied is not None:
        return denied
    try:
        payload = action(include_test=_include_test(request))
    except GradeSummaryError as exc:
        message = str(exc)
        if "required" in message.casefold() or "must be a boolean" in message.casefold():
            return _error(message, 400, code="invalid_request")
        return _error("Not found.", 404, code="not_found")
    return JsonResponse(payload)


@require_GET
def class_summary(request, class_id: int):
    """Return one class's named grade summary."""
    return _summary(
        request,
        lambda *, include_test: class_grade_summary(
            request.user, class_id, include_test=include_test
        ),
    )


@require_GET
def course_summary(request, course_id: int):
    """Return one Course/teaching cohort's named grade summary."""
    return _summary(
        request,
        lambda *, include_test: class_grade_summary(
            request.user, course_id, include_test=include_test
        ),
    )


@require_GET
def teaching_course_summary(request, teaching_course_id: int):
    """Return authorized classes grouped under one TeachingCourse."""
    return _summary(
        request,
        lambda *, include_test: teaching_course_grade_summary(
            request.user, teaching_course_id, include_test=include_test
        ),
    )


__all__ = ["class_summary", "course_summary", "teaching_course_summary"]
