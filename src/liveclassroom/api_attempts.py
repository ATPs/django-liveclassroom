"""Authenticated start/resume and own-attempt read APIs."""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .api import _body, _error
from .models import AssessmentAttempt, AssessmentRun
from .services.attempt_submission import AttemptSubmissionConflict, submit_attempt
from .services.attempts import (
    AttemptAnswerConflict,
    attempt_payload,
    own_attempt,
    save_attempt_answer,
    start_or_resume_attempt,
)
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


@require_http_methods(["POST"])
def save_answer(request, public_id):
    """Save one student's answer with an optimistic version and replay key."""
    denied = _user(request)
    if denied is not None:
        return denied
    try:
        body = _body(request)
        required = {"item_key", "expected_version", "request_id", "answer"}
        if set(body) != required:
            raise ClassroomError("item_key, expected_version, request_id and answer are required.")
        attempt = AssessmentAttempt.objects.get(public_id=public_id)
        revision = save_attempt_answer(
            actor=request.user,
            attempt=attempt,
            item_key=body["item_key"],
            answer=body["answer"],
            expected_version=body["expected_version"],
            request_id=body["request_id"],
        )
        from django.utils import timezone

        return JsonResponse(
            {
                "item_key": str(revision.item.key),
                "version": revision.version,
                "answer": revision.answer,
                "saved_at": revision.saved_at.isoformat(),
                "server_now": timezone.now().isoformat(),
            }
        )
    except AssessmentAttempt.DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    except AttemptAnswerConflict as exc:
        payload = {"code": exc.code, "detail": str(exc)}
        if exc.current is not None:
            payload["current"] = exc.current
            # Keep the conflict useful to clients that consume the result
            # fields directly, while ``current`` remains the canonical group.
            payload.update(
                {
                    "item_key": exc.current["item_key"],
                    "version": exc.current["version"],
                    "answer": exc.current["answer"],
                }
            )
        return JsonResponse(payload, status=exc.status_code)
    except ClassroomError as exc:
        message = str(exc)
        if "permission" in message.casefold() or "authentication" in message.casefold():
            return _error(message, 403, code="permission_denied")
        if "not found" in message.casefold():
            return _error(message, 404, code="not_found")
        return _error(message, 400)


@require_http_methods(["POST"])
def submit(request, public_id):
    """Finalize the authenticated student's attempt exactly once.

    The request deliberately accepts only a request ID and an optional map of
    already acknowledged answer versions.  Client answers, clocks, and
    finalization reasons never cross this boundary.
    """
    denied = _user(request)
    if denied is not None:
        return denied
    try:
        body = _body(request)
        if set(body) - {"request_id", "expected_versions"} or "request_id" not in body:
            raise ClassroomError("request_id is required.")
        attempt = AssessmentAttempt.objects.get(public_id=public_id)
        result = submit_attempt(
            actor=request.user,
            attempt=attempt,
            request_id=body["request_id"],
            expected_versions=body.get("expected_versions"),
        )
        return JsonResponse(dict(result))
    except AssessmentAttempt.DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    except AttemptSubmissionConflict as exc:
        payload = {"code": exc.code, "detail": str(exc)}
        if exc.current_versions is not None:
            payload["current_versions"] = exc.current_versions
        return JsonResponse(payload, status=exc.status_code)
    except ClassroomError as exc:
        message = str(exc)
        if "authentication" in message.casefold():
            return _error(message, 401, code="authentication_required")
        if "permission" in message.casefold() or "access" in message.casefold():
            return _error(message, 403, code="permission_denied")
        return _error(message, 400)
