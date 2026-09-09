"""Mount-safe assessment result release and student result APIs."""

from __future__ import annotations

from uuid import UUID

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .api import _body, _error
from .models import AssessmentAttempt, AssessmentRun
from .services.attempts import own_attempt
from .services.classroom import ClassroomError
from .services.result_release import (
    ResultReleaseError,
    can_manage_result_release,
    release_result_dimension,
    run_release_policy,
    student_result_payload,
)


def _user(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    return None


def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_jsonable(child) for child in value]
    # Decimal values are kept as strings in grade/result APIs, matching the
    # persisted point contract and avoiding binary rounding in clients.
    from decimal import Decimal

    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _run_for_teacher(actor, public_id):
    try:
        run = AssessmentRun.objects.select_related("course").get(public_id=public_id)
    except AssessmentRun.DoesNotExist as exc:
        raise ResultReleaseError("Assessment run not found.") from exc
    if not can_manage_result_release(actor, run):
        raise ResultReleaseError("Teacher release access is required.")
    return run


@require_http_methods(["POST"])
def release(request, public_id):
    """Release one dimension for the whole run or one explicit attempt."""
    denied = _user(request)
    if denied is not None:
        return denied
    try:
        run = _run_for_teacher(request.user, public_id)
        body = _body(request)
        allowed = {"dimension", "attempt_id"}
        if set(body) - allowed or "dimension" not in body:
            raise ResultReleaseError("dimension is required.")
        attempt = None
        if body.get("attempt_id") is not None:
            try:
                attempt = AssessmentAttempt.objects.get(
                    public_id=UUID(str(body["attempt_id"])), run=run
                )
            except (ValueError, TypeError, AttributeError, AssessmentAttempt.DoesNotExist) as exc:
                raise ResultReleaseError("The assessment attempt was not found.") from exc
        row = release_result_dimension(
            run=run,
            dimension=body["dimension"],
            actor=request.user,
            attempt=attempt,
        )
        return JsonResponse(
            {
                "run_id": str(run.public_id),
                "attempt_id": str(attempt.public_id) if attempt is not None else None,
                "dimension": row.dimension,
                "released": row.released,
                "released_at": row.released_at.isoformat() if row.released_at else None,
                "policy": run_release_policy(run),
            }
        )
    except (ResultReleaseError, ClassroomError) as exc:
        message = str(exc)
        status = 404 if "not found" in message.casefold() else 403
        return _error(message, status, code="not_found" if status == 404 else "permission_denied")


@require_http_methods(["GET"])
def result(request, public_id):
    """Return only the logged-in student's server-filtered result."""
    denied = _user(request)
    if denied is not None:
        return denied
    try:
        attempt = own_attempt(request.user, public_id)
        from .services.assessment_timing import finalize_due_attempt

        if finalize_due_attempt(attempt=attempt) is not None:
            attempt = own_attempt(request.user, public_id)
        return JsonResponse(_jsonable(student_result_payload(attempt=attempt)))
    except ClassroomError:
        # Do not distinguish another student's attempt from a nonexistent one.
        return _error("Not found.", 404, code="not_found")


__all__ = ["release", "result"]
