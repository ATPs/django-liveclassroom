"""Mount-safe HTTP adapters for explicit named reusable-content shares."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .api import _body, _error
from .models import ContentShare
from .services.permissions import can_teach
from .services.sharing import ContentShareError, copy_shared_content, create_share, list_shares, revoke_share


def _teacher(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    return None


def _payload(share):
    return {
        "id": share.pk,
        "kind": share.kind,
        "object_id": share.resource_id,
        "recipient": {"id": share.recipient_id, "display_name": share.recipient.get_username()},
        "created_at": share.created_at.isoformat(),
        "revoked_at": share.revoked_at.isoformat() if share.revoked_at else None,
        "active": share.active,
        "source_fingerprint": share.source_fingerprint,
    }


def _share_for_action(actor, share_id):
    try:
        share = ContentShare.objects.select_related("owner", "recipient").get(pk=share_id)
    except ContentShare.DoesNotExist as exc:
        raise ContentShareError("Content share not found.") from exc
    if share.owner_id != actor.pk and share.recipient_id != actor.pk and not getattr(actor, "is_superuser", False):
        raise ContentShareError("Content share not found.")
    return share


def _response_error(exc):
    message = str(exc)
    if "not found" in message.casefold():
        return _error("Not found.", 404, code="not_found")
    if "do not own" in message.casefold() or "access" in message.casefold() or "available" in message.casefold():
        return _error(message, 403, code="permission_denied")
    return _error(message, 400, code="invalid_request")


@require_http_methods(["GET", "POST"])
def content_shares(request):
    denied = _teacher(request)
    if denied is not None:
        return denied
    try:
        if request.method == "GET":
            return JsonResponse({"content_shares": [_payload(share) for share in list_shares(actor=request.user)]})
        body = _body(request)
        if set(body) != {"kind", "object_id", "recipient_id"}:
            raise ContentShareError("kind, object_id and recipient_id are required.")
        try:
            recipient = get_user_model().objects.get(pk=int(body["recipient_id"]))
        except (TypeError, ValueError, get_user_model().DoesNotExist) as exc:
            raise ContentShareError("Recipient was not found.") from exc
        share = create_share(
            actor=request.user,
            kind=body["kind"],
            object_id=body["object_id"],
            recipient=recipient,
        )
        return JsonResponse(_payload(share), status=201)
    except ContentShareError as exc:
        return _response_error(exc)


@require_http_methods(["DELETE"])
def content_share_detail(request, share_id: int):
    denied = _teacher(request)
    if denied is not None:
        return denied
    try:
        share = _share_for_action(request.user, share_id)
        return JsonResponse(_payload(revoke_share(actor=request.user, share=share)))
    except ContentShareError as exc:
        return _response_error(exc)


@require_http_methods(["POST"])
def content_share_copy(request, share_id: int):
    denied = _teacher(request)
    if denied is not None:
        return denied
    try:
        if _body(request):
            raise ContentShareError("This copy endpoint does not accept fields.")
        share = _share_for_action(request.user, share_id)
        result = copy_shared_content(actor=request.user, share=share)
        return JsonResponse({"share_id": share.pk, "objects": result.objects}, status=201)
    except ContentShareError as exc:
        return _response_error(exc)


__all__ = ["content_share_copy", "content_share_detail", "content_shares"]
