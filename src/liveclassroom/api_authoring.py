"""Authoring and AI endpoints kept separate from live classroom control APIs."""

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .ai import AuthoringAIError, authoring_ai_backends
from .api import _authoring_replay, _body, _error, _record_authoring
from .models import ActivityDefinition, AuthoringJob, AuthoringMessage, AuthoringThread, Course
from .registry import activity_registry
from .services.authoring import can_view_authoring_thread, create_authoring_request, create_authoring_thread
from .services.classroom import ClassroomError, create_activity_definition, revise_activity_definition
from .services.permissions import can_author_course


@require_http_methods(["GET", "POST"])
@transaction.atomic
def activity_definitions(request):
    """List or create reusable activities for the authenticated teacher."""
    if not getattr(request.user, "is_authenticated", False):
        return _error("An authenticated teacher is required.", 403)
    if request.method == "POST":
        return create_activity(request)
    definitions = ActivityDefinition.objects.filter(owner=request.user).values(
        "id", "title", "type_key", "schema_version", "status", "definition", "current_revision_id", "updated_at"
    )
    return JsonResponse({"activities": list(definitions)})


@require_GET
def activity_types(request):
    """Expose the installed activity manifest to authenticated authoring clients."""
    if not getattr(request.user, "is_authenticated", False):
        return _error("An authenticated teacher is required.", 403)
    return JsonResponse(
        {
            "protocol_version": 1,
            "activity_types": [
                {
                    "key": activity_type.key,
                    "schema_version": 1,
                    "capabilities": sorted(activity_type.capabilities),
                    "frontend_manifest": dict(activity_type.frontend_manifest),
                }
                for activity_type in sorted(activity_registry.all(), key=lambda item: item.key)
            ],
        }
    )


def _authoring_message_payload(message: AuthoringMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "model_identifier": message.model_identifier,
        "status": message.status,
        "attachments": [
            {
                "id": attachment.id,
                "source_type": attachment.source_type,
                "source_id": attachment.source_id,
                "provider": attachment.provider,
                "reference": attachment.reference,
                "source_fingerprint": attachment.source_fingerprint,
            }
            for attachment in message.attachments.all()
        ],
        "created_at": message.created_at,
    }


def _authoring_job_payload(job: AuthoringJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "backend_key": job.backend_key,
        "model_identifier": job.model_identifier,
        "error_code": job.error_code,
        "attempt": job.attempt,
        "message_id": job.message_id,
        "assistant_message_id": job.assistant_message_id,
        "queued_at": job.queued_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


@require_http_methods(["GET", "POST"])
@transaction.atomic
def authoring_threads(request):
    """List or create private teacher authoring conversations."""
    if not getattr(request.user, "is_authenticated", False):
        return _error("An authenticated teacher is required.", 403)
    if request.method == "POST":
        replay, key = _authoring_replay(request, "authoring.thread.create")
        if replay is not None:
            return replay
        try:
            body = _body(request)
            thread = create_authoring_thread(
                owner=request.user,
                title=body.get("title", "New authoring conversation"),
            )
        except ClassroomError as exc:
            return _record_authoring(request, key, "authoring.thread.create", _error(str(exc), 400))
        return _record_authoring(
            request,
            key,
            "authoring.thread.create",
            JsonResponse({"id": thread.id, "title": thread.title}, status=201),
        )
    threads = AuthoringThread.objects.filter(owner=request.user).values("id", "title", "created_at", "updated_at")
    return JsonResponse({"threads": list(threads)})


@require_GET
def authoring_models(request):
    """Expose only safe model metadata from configured AI backends."""
    if not getattr(request.user, "is_authenticated", False):
        return _error("An authenticated teacher is required.", 403)
    backend_key = request.GET.get("backend")
    try:
        registry = authoring_ai_backends()
        keys = [backend_key] if backend_key else registry.keys()
        models = []
        for key in keys:
            for model in registry.get(key).list_models(request=request):
                if not hasattr(model, "identifier") or not hasattr(model, "label"):
                    raise AuthoringAIError("Invalid model metadata")
                models.append({"backend_key": key, "identifier": str(model.identifier), "label": str(model.label)})
    except Exception:
        return _error("AI model discovery is temporarily unavailable.", 503)
    return JsonResponse({"backends": registry.keys(), "models": models})


@require_GET
def authoring_thread(request, thread_id: int):
    """Return one private conversation and bounded job status."""
    thread = get_object_or_404(AuthoringThread, pk=thread_id)
    if not can_view_authoring_thread(request.user, thread):
        return _error("You do not have permission to view this authoring thread.", 403)
    messages = list(thread.messages.prefetch_related("attachments").all())
    return JsonResponse(
        {
            "id": thread.id,
            "title": thread.title,
            "messages": [_authoring_message_payload(message) for message in messages],
            "jobs": [_authoring_job_payload(job) for job in thread.jobs.all()],
        }
    )


@require_POST
@transaction.atomic
def authoring_message(request, thread_id: int):
    """Queue a teacher prompt with explicit, re-authorized attachments."""
    thread = get_object_or_404(AuthoringThread, pk=thread_id)
    if not can_view_authoring_thread(request.user, thread):
        return _error("You do not have permission to use this authoring thread.", 403)
    replay, key = _authoring_replay(request, f"authoring.message.{thread_id}")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        prompt, job = create_authoring_request(
            thread=thread,
            author=request.user,
            content=body["content"],
            backend_key=body["backend_key"],
            model_identifier=body["model_identifier"],
            attachments=body.get("attachments", []),
            request=request,
            options=body.get("options"),
        )
    except KeyError as exc:
        return _record_authoring(request, key, f"authoring.message.{thread_id}", _error(f"{exc.args[0]} is required."))
    except ClassroomError as exc:
        return _record_authoring(request, key, f"authoring.message.{thread_id}", _error(str(exc), 400))
    return _record_authoring(
        request,
        key,
        f"authoring.message.{thread_id}",
        JsonResponse({"message": _authoring_message_payload(prompt), "job": _authoring_job_payload(job)}, status=202),
    )


@require_GET
def authoring_job(request, job_id: int):
    """Return a teacher-owned job status without provider diagnostics."""
    job = get_object_or_404(AuthoringJob.objects.select_related("thread"), pk=job_id)
    if not can_view_authoring_thread(request.user, job.thread):
        return _error("You do not have permission to view this authoring job.", 403)
    return JsonResponse(_authoring_job_payload(job))


@require_POST
@transaction.atomic
def create_activity(request):
    """Create one validated reusable activity through the registry contract."""
    if not getattr(request.user, "is_authenticated", False):
        return _error("An authenticated teacher is required.", 403)
    replay, key = _authoring_replay(request, "activity.create")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        course = None
        if body.get("course_id") is not None:
            course = get_object_or_404(Course, pk=body["course_id"])
            if not can_author_course(request.user, course):
                return _record_authoring(
                    request,
                    key,
                    "activity.create",
                    _error("You do not have permission to author content for this course.", 403),
                )
        activity = create_activity_definition(
            owner=request.user,
            title=body["title"],
            type_key=body["type_key"],
            definition=body.get("definition", {}),
            course=course,
            change_note=body.get("change_note", ""),
        )
    except KeyError as exc:
        return _record_authoring(request, key, "activity.create", _error(f"{exc.args[0]} is required."))
    except ClassroomError as exc:
        return _record_authoring(request, key, "activity.create", _error(str(exc), 400))
    return _record_authoring(
        request,
        key,
        "activity.create",
        JsonResponse(
            {
                "id": activity.id,
                "title": activity.title,
                "type_key": activity.type_key,
                "revision": activity.current_revision_id,
            },
            status=201,
        ),
    )


@require_POST
@transaction.atomic
def revise_activity_definition_api(request, activity_id: int):
    """Create an immutable reusable-activity revision after registry validation."""
    activity = get_object_or_404(ActivityDefinition, pk=activity_id)
    command_type = f"activity.revise-definition.{activity_id}"
    replay, key = _authoring_replay(request, command_type)
    if replay is not None:
        return replay
    try:
        body = _body(request)
        revision = revise_activity_definition(
            activity=activity,
            definition=body["definition"],
            actor=request.user,
            change_note=body.get("change_note", ""),
        )
    except KeyError:
        return _record_authoring(request, key, command_type, _error("definition is required."))
    except ClassroomError as exc:
        return _record_authoring(request, key, command_type, _error(str(exc), 403))
    return _record_authoring(
        request,
        key,
        command_type,
        JsonResponse(
            {"activity_id": activity.id, "revision": revision.revision, "revision_id": revision.id},
            status=201,
        ),
    )
