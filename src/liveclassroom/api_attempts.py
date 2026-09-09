"""Authenticated start/resume and own-attempt read APIs."""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .api import _body, _error
from .models import AssessmentRun
from .services.attempts import attempt_payload, own_attempt, start_or_resume_attempt
from .services.classroom import ClassroomError


def _user(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    return None


@require_http_methods(["POST"])
def start_attempt(request, public_id):
    denied = _user(request)
    if denied is not None:
        return denied
    try:
        body = _body(request)
        if set(body) - {"request_id", "new_attempt"} or "request_id" not in body:
            raise ClassroomError("request_id is required.")
        run = AssessmentRun.objects.get(public_id=public_id)
        attempt, created = start_or_resume_attempt(
            actor=request.user, run=run, request_id=body["request_id"], new_attempt=body.get("new_attempt", False)
        )
        return JsonResponse({**attempt_payload(attempt), "created": created}, status=201 if created else 200)
    except AssessmentRun.DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    except ClassroomError as exc:
        status = 409 if any(word in str(exc).casefold() for word in ("remain", "used", "concurrently")) else 403
        return _error(str(exc), status, code="stale_revision" if status == 409 else None)


@require_http_methods(["GET"])
def attempt_detail(request, public_id):
    denied = _user(request)
    if denied is not None:
        return denied
    try:
        return JsonResponse(attempt_payload(own_attempt(request.user, public_id)))
    except ClassroomError:
        return _error("Not found.", 404, code="not_found")
