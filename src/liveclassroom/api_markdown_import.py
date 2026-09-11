"""Preview and commit endpoints for portable Markdown/YAML authoring."""

from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .api import _body, _error
from .services.classroom import ClassroomError
from .services.markdown_import import MarkdownImportError, commit_markdown_import, preview_markdown_import
from .services.permissions import can_teach


def _access(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    return None


@require_http_methods(["POST"])
def preview(request):
    denied = _access(request)
    if denied is not None:
        return denied
    try:
        body = _body(request)
        if set(body) != {"filename", "content"}:
            raise MarkdownImportError("filename and content are required.")
        return JsonResponse(preview_markdown_import(actor=request.user, **body).as_dict())
    except (MarkdownImportError, ClassroomError) as exc:
        return _error(str(exc), 400)


@require_http_methods(["POST"])
def commit(request):
    denied = _access(request)
    if denied is not None:
        return denied
    try:
        body = _body(request)
        if set(body) != {"filename", "content", "fingerprint", "idempotency_key"}:
            raise MarkdownImportError("filename, content, fingerprint and idempotency_key are required.")
        result = commit_markdown_import(
            actor=request.user,
            draft=body,
            draft_fingerprint=body["fingerprint"],
            idempotency_key=body["idempotency_key"],
        )
        return JsonResponse({"objects": result.objects}, status=201)
    except (MarkdownImportError, ClassroomError) as exc:
        status = 409 if "changed" in str(exc).casefold() or "already used" in str(exc).casefold() else 400
        return _error(str(exc), status)
