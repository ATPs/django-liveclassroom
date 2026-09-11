"""Named grants for reusable authoring content."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from django.db import IntegrityError, transaction
from django.utils import timezone

from liveclassroom.models import ActivityDefinition, AssessmentDefinition, ContentShare, Deck, QuestionBank

from .classroom import ClassroomError
from .permissions import can_teach

_RESOURCE_MODELS = {
    ContentShare.Kind.QUESTION: ActivityDefinition,
    ContentShare.Kind.BANK: QuestionBank,
    ContentShare.Kind.DECK: Deck,
    ContentShare.Kind.ASSESSMENT: AssessmentDefinition,
}


class ContentShareError(ClassroomError):
    pass


def _kind(value):
    if not isinstance(value, str) or value not in _RESOURCE_MODELS:
        raise ContentShareError("kind must be question, bank, deck or assessment.")
    return value


def _resource(kind, object_id):
    try:
        value = int(object_id)
    except (TypeError, ValueError) as exc:
        raise ContentShareError("object_id must be a positive integer.") from exc
    if value < 1:
        raise ContentShareError("object_id must be a positive integer.")
    model = _RESOURCE_MODELS[kind]
    try:
        return model.objects.get(pk=value)
    except model.DoesNotExist as exc:
        raise ContentShareError("Content was not found.") from exc


def _owner(resource):
    return getattr(resource, "owner", None)


def _fingerprint(resource) -> str:
    # This is metadata only; source content stays behind normal read/copy checks.
    return sha256(
        f"{resource.__class__.__name__}:{resource.pk}:{getattr(resource, 'updated_at', '')}".encode()
    ).hexdigest()


@transaction.atomic
def create_share(*, actor, kind, object_id, recipient):
    kind = _kind(kind)
    resource = _resource(kind, object_id)
    if not getattr(actor, "is_authenticated", False) or not can_teach(actor):
        raise ContentShareError("Teacher sharing access is required.")
    if not (getattr(actor, "is_superuser", False) or _owner(resource).pk == actor.pk):
        raise ContentShareError("You do not own this content.")
    if not getattr(recipient, "pk", None) or recipient.pk == _owner(resource).pk:
        raise ContentShareError("Recipient must be another saved account.")
    existing = (
        ContentShare.objects.select_for_update()
        .filter(
            owner=_owner(resource), recipient=recipient, kind=kind, resource_id=resource.pk, revoked_at__isnull=True
        )
        .first()
    )
    if existing:
        return existing
    try:
        return ContentShare.objects.create(
            owner=_owner(resource),
            recipient=recipient,
            kind=kind,
            resource_id=resource.pk,
            source_fingerprint=_fingerprint(resource),
        )
    except IntegrityError:
        return ContentShare.objects.get(
            owner=_owner(resource), recipient=recipient, kind=kind, resource_id=resource.pk, revoked_at__isnull=True
        )


def list_shares(*, actor):
    if not getattr(actor, "is_authenticated", False):
        raise ContentShareError("Authentication required.")
    # Keep the original owner-list contract for ordinary teachers.  A
    # superuser can administer grants for every owner, so returning all rows
    # here also makes the API's elevated revoke path discoverable.
    queryset = (
        ContentShare.objects.all()
        if getattr(actor, "is_superuser", False)
        else ContentShare.objects.filter(owner=actor)
    )
    return queryset.select_related("owner", "recipient")


def list_received_shares(*, actor, include_revoked: bool = False):
    """Return grants that make reusable content discoverable to ``actor``.

    Revoked grants are intentionally omitted from the recipient view by
    default.  A revoked source must not remain a usable preview/copy entry;
    the owner list still retains revoked rows for audit and idempotent revoke.
    ``include_revoked`` is available to administrative callers that need a
    complete history, but the HTTP API does not use it for recipients.
    """
    if not getattr(actor, "is_authenticated", False):
        raise ContentShareError("Authentication required.")
    queryset = ContentShare.objects.filter(recipient=actor)
    if not include_revoked:
        queryset = queryset.filter(revoked_at__isnull=True)
    return queryset.select_related("owner", "recipient")


@transaction.atomic
def revoke_share(*, actor, share, now: datetime | None = None):
    locked = ContentShare.objects.select_for_update().get(pk=share.pk)
    if not (getattr(actor, "is_superuser", False) or locked.owner_id == getattr(actor, "pk", None)):
        raise ContentShareError("You do not own this share.")
    if locked.revoked_at is None:
        locked.revoked_at = timezone.now() if now is None else now
        locked.save(update_fields=["revoked_at"])
    return locked


def shared_resource(*, actor, share):
    share = ContentShare.objects.select_related("owner", "recipient").get(pk=share.pk)
    if share.revoked_at is not None or share.recipient_id != getattr(actor, "pk", None):
        raise ContentShareError("This content share is not available.")
    resource = _resource(share.kind, share.resource_id)
    if _owner(resource).pk != share.owner_id:
        raise ContentShareError("This content share is no longer available.")
    return resource


def describe_shared_resource(*, actor, share):
    """Resolve a safe source object for a share preview.

    Owners (and superusers) may inspect their grant metadata even after
    revocation.  Recipients may inspect it only while the grant is active;
    this keeps a revoked source from becoming an alternate content lookup
    path.  The returned model object is for trusted server-side serializers;
    callers must not expose its definition as a share summary.
    """
    share = ContentShare.objects.select_related("owner", "recipient").get(pk=share.pk)
    actor_id = getattr(actor, "pk", None)
    is_owner = getattr(actor, "is_superuser", False) or share.owner_id == actor_id
    is_recipient = share.recipient_id == actor_id and share.revoked_at is None
    if not (is_owner or is_recipient):
        raise ContentShareError("This content share is not available.")
    resource = _resource(share.kind, share.resource_id)
    if _owner(resource).pk != share.owner_id:
        raise ContentShareError("This content share is no longer available.")
    return resource


@transaction.atomic
def copy_shared_content(*, actor, share):
    """Copy an active named grant without treating the recipient as its owner.

    The portable serializer asks ``authorize`` about each object it reaches.
    This limits the exception to the exact graph rooted at the active grant;
    it does not turn the recipient into the source owner's identity.
    """
    try:
        locked = ContentShare.objects.select_for_update().select_related("owner", "recipient").get(pk=share.pk)
    except ContentShare.DoesNotExist as exc:
        raise ContentShareError("This content share is not available.") from exc
    resource = shared_resource(actor=actor, share=locked)

    def authorize(reached_kind, reached):
        if reached_kind == locked.kind and reached.pk == resource.pk:
            return
        # Dependency traversal starts only from the granted root.  Every
        # subordinate definition, bank and uploaded asset must still belong to
        # that same source owner.  Provider definitions receive an additional
        # recipient-side validation from portable_content.
        if getattr(reached, "owner_id", None) != locked.owner_id:
            raise ContentShareError("This share cannot copy a private dependency.")

    try:
        from .portable_content import (
            PortableContentError,
            export_portable_for_granted_graph,
            import_portable,
        )

        payload = export_portable_for_granted_graph(
            actor=actor,
            kind=locked.kind,
            resource=resource,
            authorize=authorize,
        )
        return import_portable(actor=actor, payload=payload)
    except PortableContentError as exc:
        raise ContentShareError(str(exc)) from exc


__all__ = [
    "ContentShareError",
    "copy_shared_content",
    "create_share",
    "describe_shared_resource",
    "list_shares",
    "list_received_shares",
    "revoke_share",
    "shared_resource",
]
