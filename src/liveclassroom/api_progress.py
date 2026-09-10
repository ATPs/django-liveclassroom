"""Mount-safe teacher APIs for assessment progress and learner overview."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .api import _error
from .models import AssessmentRun
from .services.assessment_progress import (
    AssessmentProgressError,
    get_student_overview,
    list_run_progress,
)


def _staff(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    return None


def _query(request):
    values = {}
    for key in ("page", "page_size", "status", "student_id", "class_id", "include_test"):
        if key in request.GET:
            values[key] = request.GET.get(key)
    return values


@require_GET
def run_progress(request, public_id):
    """List one run's named progress with bounded pagination."""
    denied = _staff(request)
    if denied is not None:
        return denied
    try:
        run = AssessmentRun.objects.select_related("course").get(public_id=public_id)
    except AssessmentRun.DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    try:
        payload = list_run_progress(request.user, run, _query(request))
    except AssessmentProgressError:
        return _error("Not found.", 404, code="not_found")
    return JsonResponse(payload)


@require_GET
def student_overview(request, user_id):
    """Return one account-linked learner's assessment and live participation."""
    denied = _staff(request)
    if denied is not None:
        return denied
    try:
        user = get_user_model().objects.get(pk=user_id)
    except get_user_model().DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    class_id = request.GET.get("class_id")
    try:
        payload = get_student_overview(request.user, user, class_id=class_id or None)
    except AssessmentProgressError:
        return _error("Not found.", 404, code="not_found")
    return JsonResponse(payload)


__all__ = ["run_progress", "student_overview"]
