"""Owner-scoped HTTP adapters for portable content copies."""

from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .api import _body, _error
from .models import AuthoringCommandReceipt
from .services.permissions import can_teach
from .services.portable_content import PortableContentError, export_portable, import_portable


def _access(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    return None


def _hash(payload) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@require_http_methods(["GET"])
def portable_export(request, kind: str, object_id: int):
    denied = _access(request)
    if denied is not None:
        return denied
    try:
        return JsonResponse(export_portable(actor=request.user, kind=kind, object_id=object_id))
    except PortableContentError as exc:
        status = 403 if "permission" in str(exc).casefold() else 404 if "not found" in str(exc).casefold() else 400
        return _error(str(exc), status)


@require_http_methods(["POST"])
def portable_import(request):
    denied = _access(request)
    if denied is not None:
        return denied
    try:
        body = _body(request)
        if set(body) != {"payload", "idempotency_key"}:
            raise PortableContentError("payload and idempotency_key are required.")
        key = body["idempotency_key"]
        if not isinstance(key, str) or not key.strip() or len(key) > 160:
            raise PortableContentError("idempotency_key must be non-empty text of at most 160 characters.")
        key = key.strip()
        request_hash = _hash(body["payload"])
        with transaction.atomic():
            receipt = (
                AuthoringCommandReceipt.objects.select_for_update()
                .filter(owner=request.user, idempotency_key=key)
                .first()
            )
            if receipt is not None:
                if receipt.command_type != "portable.import" or receipt.request_hash != request_hash:
                    return _error(
                        "This idempotency key was already used with different input.",
                        409,
                        code="idempotency_conflict",
                    )
                response = JsonResponse(receipt.response, status=receipt.status_code)
                response["Idempotent-Replay"] = "true"
                return response
            result = import_portable(actor=request.user, payload=body["payload"])
            response_payload = {"objects": result.objects}
            AuthoringCommandReceipt.objects.create(
                owner=request.user, idempotency_key=key, command_type="portable.import",
                request_hash=request_hash, response=response_payload, status_code=201,
            )
        return JsonResponse(response_payload, status=201)
    except PortableContentError as exc:
        return _error(str(exc), 403 if "permission" in str(exc).casefold() else 400)
