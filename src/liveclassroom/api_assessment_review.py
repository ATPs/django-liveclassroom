"""Authenticated, mount-safe APIs for own assessment history and review."""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .api import _error
from .services.assessment_review import (
    AssessmentReviewError,
    list_own_attempt_history,
    review_own_attempt,
)


def _user(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    return None


@require_http_methods(["GET"])
def history(request):
    denied = _user(request)
    if denied is not None:
        return denied
    try:
        return JsonResponse(
            list_own_attempt_history(
                actor=request.user,
                limit=request.GET.get("limit"),
                offset=request.GET.get("offset"),
            )
        )
    except AssessmentReviewError as exc:
        return _error(str(exc), 400, code="invalid_request")


@require_http_methods(["GET"])
def review(request, public_id):
    denied = _user(request)
    if denied is not None:
        return denied
    try:
        return JsonResponse(review_own_attempt(actor=request.user, public_id=public_id))
    except AssessmentReviewError:
        return _error("Not found.", 404, code="not_found")


__all__ = ["history", "review"]
