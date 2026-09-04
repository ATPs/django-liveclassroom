"""Transactional services for private teacher AI authoring conversations."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import timedelta
from importlib import import_module
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from liveclassroom.ai import AIMessage, AuthoringAIError, authoring_ai_backends
from liveclassroom.models import (
    ActivityDefinition,
    AuthoringAttachment,
    AuthoringJob,
    AuthoringMessage,
    AuthoringThread,
    Flow,
    FlowStep,
)
from liveclassroom.providers import ContentReference, ProviderError, content_providers

from .classroom import ClassroomError
from .permissions import can_author_course


def can_view_authoring_thread(actor, thread: AuthoringThread) -> bool:
    """Keep every authoring conversation private to its owner."""
    return bool(getattr(actor, "is_authenticated", False) and actor.pk == thread.owner_id)


def create_authoring_thread(*, owner, title: str = "New authoring conversation") -> AuthoringThread:
    """Create a teacher-owned conversation."""
    if not getattr(owner, "is_authenticated", False):
        raise ClassroomError("An authenticated teacher is required.")
    if not isinstance(title, str) or not title.strip():
        raise ClassroomError("A thread title is required.")
    return AuthoringThread.objects.create(owner=owner, title=title.strip()[:200])


def _can_attach_activity(actor, activity: ActivityDefinition) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(
        actor.is_superuser
        or activity.owner_id == actor.pk
        or (activity.course_id and can_author_course(actor, activity.course))
    )


def _can_attach_flow(actor, flow: Flow) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(
        actor.is_superuser
        or (flow.created_by_id and flow.created_by_id == actor.pk)
        or (flow.course_id and can_author_course(actor, flow.course))
    )


def _positive_id(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ClassroomError(f"{field} must be a positive integer.")
    return value


def _provider_reference(payload: Mapping[str, Any], *, request) -> tuple[str, dict[str, Any], str]:
    provider_key = payload.get("provider") or (
        "vaultpub" if payload.get("source_type", payload.get("type")) == "vaultpub" else None
    )
    if not isinstance(provider_key, str) or not provider_key.strip():
        raise ClassroomError("A content provider is required.")
    provider_key = provider_key.strip()
    try:
        provider = content_providers().get(provider_key)
        raw_reference = payload.get("reference")
        if isinstance(raw_reference, Mapping):
            reference = ContentReference(
                provider_key,
                str(raw_reference.get("kind", "")),
                dict(raw_reference.get("value", {})),
            )
        elif isinstance(payload.get("url"), str):
            reference = provider.parse_reference(payload["url"], request=request)
        else:
            raise ClassroomError("A provider reference or URL is required.")
        validated = provider.validate_reference(reference, request=request)
    except (ProviderError, TypeError, ValueError) as exc:
        raise ClassroomError("The attached provider source is unavailable or not authorized.") from exc
    value = _safe_reference_value(validated.value)
    fingerprint = ""
    try:
        descriptor = provider.describe(validated, request=request)
        candidate = descriptor.get("source_fingerprint") or descriptor.get("fingerprint", "")
        if isinstance(candidate, str):
            fingerprint = candidate[:128]
    except (ProviderError, TypeError, ValueError):
        pass
    return validated.kind, value, fingerprint


_SOURCE_CONTENT_KEYS = {
    "body",
    "content",
    "document",
    "html",
    "markdown",
    "plain_text",
    "raw",
    "raw_content",
    "rendered",
    "rendered_html",
    "source",
    "source_text",
    "text",
    "text_content",
}


def _safe_reference_value(value: Any) -> dict[str, Any]:
    """Accept only bounded reference metadata, never an expanded source body."""
    if not isinstance(value, Mapping):
        raise ClassroomError("A provider reference must be an object.")

    def scrub(item: Any, *, key: str | None = None) -> Any:
        if key and key.casefold() in _SOURCE_CONTENT_KEYS:
            raise ClassroomError("Provider references must not contain source content.")
        if isinstance(item, Mapping):
            return {str(child_key): scrub(child_value, key=str(child_key)) for child_key, child_value in item.items()}
        if isinstance(item, (list, tuple)):
            return [scrub(child) for child in item]
        if item is None or isinstance(item, (bool, int, float, str)):
            return item
        raise ClassroomError("Provider references must contain JSON metadata only.")

    safe = scrub(value)
    try:
        encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ClassroomError("Provider references must contain JSON metadata only.") from exc
    if len(encoded.encode("utf-8")) > 8192:
        raise ClassroomError("Provider references are too large.")
    return safe


def _normalize_attachment(payload: Mapping[str, Any], *, actor, request) -> dict[str, Any]:
    source_type = payload.get("source_type", payload.get("type"))
    source_type_alias = source_type
    if not isinstance(source_type, str):
        raise ClassroomError("Unsupported authoring attachment type.")
    source_type = {
        "activity_definition": AuthoringAttachment.SourceType.ACTIVITY,
        "activity": AuthoringAttachment.SourceType.ACTIVITY,
        "flow": AuthoringAttachment.SourceType.FLOW,
        "flow_step": AuthoringAttachment.SourceType.FLOW_STEP,
        "provider": AuthoringAttachment.SourceType.PROVIDER,
        "vaultpub": AuthoringAttachment.SourceType.PROVIDER,
    }.get(source_type, source_type)
    if not isinstance(source_type, str) or source_type not in AuthoringAttachment.SourceType.values:
        raise ClassroomError("Unsupported authoring attachment type.")

    if source_type == AuthoringAttachment.SourceType.PROVIDER:
        kind, value, fingerprint = _provider_reference(payload, request=request)
        provider = str(payload.get("provider") or ("vaultpub" if source_type_alias == "vaultpub" else "")).strip()
        if not provider:
            raise ClassroomError("A content provider is required.")
        return {
            "source_type": source_type,
            "source_id": None,
            "provider": provider,
            "reference": {"provider": provider, "kind": kind, "value": value},
            "source_fingerprint": fingerprint,
        }

    source_id = payload.get("source_id", payload.get("id"))
    if source_type == AuthoringAttachment.SourceType.ACTIVITY:
        source_id = payload.get("activity_id", source_id)
    elif source_type == AuthoringAttachment.SourceType.FLOW:
        source_id = payload.get("flow_id", source_id)
    elif source_type == AuthoringAttachment.SourceType.FLOW_STEP:
        source_id = payload.get("flow_step_id", source_id)
    source_id = _positive_id(source_id, "source_id")
    if source_type == AuthoringAttachment.SourceType.ACTIVITY:
        source = ActivityDefinition.objects.filter(pk=source_id).first()
        allowed = source is not None and _can_attach_activity(actor, source)
    elif source_type == AuthoringAttachment.SourceType.FLOW:
        source = Flow.objects.filter(pk=source_id).first()
        allowed = source is not None and _can_attach_flow(actor, source)
    else:
        source = FlowStep.objects.select_related("flow", "activity_definition").filter(pk=source_id).first()
        allowed = source is not None and _can_attach_flow(actor, source.flow)
    if not allowed:
        raise ClassroomError("You do not have permission to attach this source.")
    return {
        "source_type": source_type,
        "source_id": source_id,
        "provider": "",
        "reference": {},
        "source_fingerprint": "",
    }


def _stored_attachment_payload(attachment: AuthoringAttachment, *, actor, request) -> dict[str, Any]:
    if attachment.source_type == AuthoringAttachment.SourceType.ACTIVITY:
        source = ActivityDefinition.objects.filter(pk=attachment.source_id).first()
        if source is None or not _can_attach_activity(actor, source):
            raise ClassroomError("An attached activity is unavailable or not authorized.")
        return {
            "source_type": attachment.source_type,
            "source_id": source.pk,
            "title": source.title,
            "type_key": source.type_key,
            "schema_version": source.schema_version,
            "content": source.definition,
        }
    elif attachment.source_type == AuthoringAttachment.SourceType.FLOW:
        source = Flow.objects.filter(pk=attachment.source_id).first()
        if source is None or not _can_attach_flow(actor, source):
            raise ClassroomError("An attached flow is unavailable or not authorized.")
        return {
            "source_type": attachment.source_type,
            "source_id": source.pk,
            "title": source.title,
            "description": source.description,
        }
    elif attachment.source_type == AuthoringAttachment.SourceType.FLOW_STEP:
        source = FlowStep.objects.select_related("flow", "activity_definition").filter(pk=attachment.source_id).first()
        if source is None or not _can_attach_flow(actor, source.flow):
            raise ClassroomError("An attached flow item is unavailable or not authorized.")
        return {
            "source_type": attachment.source_type,
            "source_id": source.pk,
            "flow_id": source.flow_id,
            "activity_definition_id": source.activity_definition_id,
            "title": source.activity_definition.title,
            "type_key": source.activity_definition.type_key,
            "content": source.activity_definition.definition,
        }
    elif attachment.source_type == AuthoringAttachment.SourceType.PROVIDER:
        try:
            provider = content_providers().get(attachment.provider)
            reference_data = attachment.reference
            reference = ContentReference(
                attachment.provider,
                str(reference_data.get("kind", "")),
                dict(reference_data.get("value", {})),
            )
            validated = provider.validate_reference(reference, request=request)
        except (ProviderError, TypeError, ValueError) as exc:
            raise ClassroomError("An attached provider source is unavailable or not authorized.") from exc
        return {
            "source_type": attachment.source_type,
            "provider": validated.provider,
            "reference": {
                "provider": validated.provider,
                "kind": validated.kind,
                "value": _safe_reference_value(validated.value),
            },
            "source_id": None,
        }
    else:  # pragma: no cover - database choices prevent this branch.
        raise ClassroomError("Unsupported authoring attachment type.")
    return {
        "source_type": attachment.source_type,
        "source_id": attachment.source_id,
        "provider": "",
        "reference": {},
    }


def _safe_options(options: Mapping[str, Any] | None) -> dict[str, Any]:
    if options is None:
        return {}
    if not isinstance(options, Mapping):
        raise ClassroomError("Custom provider options must be an object.")
    return dict(options)


@transaction.atomic
def create_authoring_request(
    *,
    thread: AuthoringThread,
    author,
    content: str,
    backend_key: str,
    model_identifier: str,
    attachments: Iterable[Mapping[str, Any]] | None = None,
    request=None,
    options: Mapping[str, Any] | None = None,
) -> tuple[AuthoringMessage, AuthoringJob]:
    """Persist a prompt and queued job, then hand it to the host dispatcher."""
    if not can_view_authoring_thread(author, thread):
        raise ClassroomError("You do not have permission to use this authoring thread.")
    if not isinstance(content, str) or not content.strip():
        raise ClassroomError("A teacher prompt is required.")
    if not isinstance(backend_key, str) or not backend_key.strip():
        raise ClassroomError("An AI backend is required.")
    if not isinstance(model_identifier, str) or not model_identifier.strip():
        raise ClassroomError("An AI model is required.")
    normalized_options = _safe_options(options)
    prompt = AuthoringMessage.objects.create(
        thread=thread,
        role=AuthoringMessage.Role.TEACHER,
        author=author,
        content=content.strip(),
    )
    for payload in attachments or []:
        if not isinstance(payload, Mapping):
            raise ClassroomError("Each authoring attachment must be an object.")
        normalized = _normalize_attachment(payload, actor=author, request=request)
        AuthoringAttachment.objects.create(message=prompt, **normalized)
    job = AuthoringJob.objects.create(
        thread=thread,
        message=prompt,
        backend_key=backend_key.strip(),
        model_identifier=model_identifier.strip(),
    )
    thread.save(update_fields=["updated_at"])

    transaction.on_commit(
        lambda: dispatch_authoring_job(
            job_id=job.pk,
            actor=author,
            request=request,
            options=normalized_options,
        )
    )
    return prompt, job


def _load_dispatcher(configured):
    if not isinstance(configured, str):
        return configured
    module_name, separator, attribute = configured.rpartition(".")
    if not separator or not module_name or not attribute:
        raise AuthoringAIError("Invalid authoring AI job dispatcher path.")
    try:
        return getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise AuthoringAIError("Unable to load authoring AI job dispatcher.") from exc


def dispatch_authoring_job(*, job_id: int, actor, request=None, options: Mapping[str, Any] | None = None) -> None:
    """Submit a queued job to a host worker without storing transient options.

    Hosts configure ``LIVECLASSROOM['AI_JOB_DISPATCHER']`` with a callable (or
    dotted path). The callable owns actual queueing and may retain custom
    provider options only in its active request/worker memory. Without a
    dispatcher, the durable job remains queued for an explicit worker hook.
    """
    try:
        configured = getattr(settings, "LIVECLASSROOM", {}).get("AI_JOB_DISPATCHER")
        dispatcher = _load_dispatcher(configured)
        if dispatcher is None:
            return
        if not callable(dispatcher):
            raise AuthoringAIError("LIVECLASSROOM['AI_JOB_DISPATCHER'] must be callable.")
        dispatcher(job_id=job_id, actor=actor, request=request, options=_safe_options(options))
    except Exception:
        AuthoringJob.objects.filter(pk=job_id, status=AuthoringJob.Status.QUEUED).update(
            status=AuthoringJob.Status.FAILED,
            error_code="dispatcher_unavailable",
            completed_at=timezone.now(),
        )


@transaction.atomic
def recover_expired_authoring_jobs() -> int:
    """Return expired worker leases to the queue until their bounded retry limit."""
    from liveclassroom.conf import ai_job_max_attempts

    now = timezone.now()
    recovered = 0
    jobs = AuthoringJob.objects.select_for_update().filter(
        status=AuthoringJob.Status.RUNNING,
        lease_expires_at__lt=now,
    )
    for job in jobs:
        if job.attempt < ai_job_max_attempts():
            job.status = AuthoringJob.Status.QUEUED
            job.attempt += 1
            job.started_at = None
            job.lease_token = ""
            job.lease_expires_at = None
            job.error_code = "worker_timeout"
            job.save(update_fields=["status", "attempt", "started_at", "lease_token", "lease_expires_at", "error_code"])
        else:
            job.status = AuthoringJob.Status.FAILED
            job.error_code = "worker_timeout"
            job.completed_at = now
            job.lease_token = ""
            job.lease_expires_at = None
            job.save(update_fields=["status", "error_code", "completed_at", "lease_token", "lease_expires_at"])
        recovered += 1
    return recovered


@transaction.atomic
def claim_next_authoring_job(*, worker_token: str) -> AuthoringJob | None:
    """Atomically claim one queued job for a package worker process."""
    from liveclassroom.conf import ai_job_timeout_seconds

    if not isinstance(worker_token, str) or not worker_token:
        raise ValueError("worker_token is required.")
    job = (
        AuthoringJob.objects.select_for_update(skip_locked=True)
        .select_related("thread", "thread__owner", "message")
        .filter(status=AuthoringJob.Status.QUEUED)
        .order_by("queued_at", "id")
        .first()
    )
    if job is None:
        return None
    now = timezone.now()
    job.status = AuthoringJob.Status.RUNNING
    job.started_at = now
    job.lease_token = worker_token
    job.lease_expires_at = now + timedelta(seconds=ai_job_timeout_seconds())
    job.error_code = ""
    job.save(update_fields=["status", "started_at", "lease_token", "lease_expires_at", "error_code"])
    return job


def _retry_or_fail_job(*, job: AuthoringJob, error_code: str, retry: bool) -> None:
    """Complete a safe failure or return a transient worker failure to its queue."""
    from liveclassroom.conf import ai_job_max_attempts

    now = timezone.now()
    if retry and job.attempt < ai_job_max_attempts():
        AuthoringJob.objects.filter(pk=job.pk).update(
            status=AuthoringJob.Status.QUEUED,
            attempt=job.attempt + 1,
            started_at=None,
            completed_at=None,
            lease_token="",
            lease_expires_at=None,
            error_code=error_code,
        )
        return
    AuthoringJob.objects.filter(pk=job.pk).update(
        status=AuthoringJob.Status.FAILED,
        error_code=error_code,
        completed_at=now,
        lease_token="",
        lease_expires_at=None,
    )


def run_authoring_job(
    *, job_id: int, actor, request=None, options: Mapping[str, Any] | None = None, worker_token: str | None = None
) -> AuthoringJob:
    """Authorize attachments again and store only final text or a safe error code."""
    job = AuthoringJob.objects.select_related("thread", "message").get(pk=job_id)
    if not can_view_authoring_thread(actor, job.thread):
        raise ClassroomError("You do not have permission to use this authoring thread.")
    with transaction.atomic():
        job = AuthoringJob.objects.select_for_update().select_related("thread", "message").get(pk=job_id)
        if job.status == AuthoringJob.Status.QUEUED:
            now = timezone.now()
            job.status = AuthoringJob.Status.RUNNING
            job.started_at = now
            job.error_code = ""
            job.save(update_fields=["status", "started_at", "error_code"])
        elif not worker_token or job.lease_token != worker_token:
            return job
    try:
        backend = authoring_ai_backends().get(job.backend_key)
        attachment_payloads = [
            _stored_attachment_payload(attachment, actor=actor, request=request)
            for attachment in job.message.attachments.all()
        ]
        messages = [
            AIMessage(message.role, message.content) for message in job.thread.messages.order_by("created_at", "id")
        ]
        if request is not None:
            setattr(request, "liveclassroom_ai_options", _safe_options(options))
        try:
            response = backend.complete(
                messages,
                model=job.model_identifier,
                request=request,
                attachments=attachment_payloads,
            )
        finally:
            if request is not None:
                try:
                    delattr(request, "liveclassroom_ai_options")
                except AttributeError:
                    pass
        if not isinstance(response, AIMessage) or response.role != "assistant" or not isinstance(response.content, str):
            raise AuthoringAIError("The AI backend returned an invalid response.")
        with transaction.atomic():
            assistant = AuthoringMessage.objects.create(
                thread=job.thread,
                role=AuthoringMessage.Role.ASSISTANT,
                content=response.content,
                model_identifier=job.model_identifier,
                status=AuthoringMessage.Status.COMPLETE,
            )
            AuthoringJob.objects.filter(pk=job.pk).update(
                status=AuthoringJob.Status.SUCCEEDED,
                assistant_message=assistant,
                completed_at=timezone.now(),
                error_code="",
                lease_token="",
                lease_expires_at=None,
            )
        job.refresh_from_db()
        return job
    except ClassroomError:
        _retry_or_fail_job(job=job, error_code="attachment_not_authorized", retry=False)
        job.refresh_from_db()
        return job
    except (AuthoringAIError, ProviderError, OSError, TimeoutError):
        _retry_or_fail_job(job=job, error_code="provider_unavailable", retry=worker_token is not None)
        job.refresh_from_db()
        return job
    except Exception:
        _retry_or_fail_job(job=job, error_code="internal_error", retry=worker_token is not None)
        job.refresh_from_db()
        return job
