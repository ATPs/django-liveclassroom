import csv
import hashlib
import io
import json
from copy import deepcopy

from django.db import IntegrityError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .ai import AuthoringAIError, authoring_ai_backends
from .models import (
    ActivityDefinition,
    AuthoringCommandReceipt,
    AuthoringJob,
    AuthoringMessage,
    AuthoringThread,
    CommandReceipt,
    Course,
    FlowItem,
    FlowStep,
    LiveActivity,
    LiveSession,
    Participant,
    SessionChannelState,
)
from .registry import activity_registry
from .services.analytics import session_analytics
from .services.authoring import (
    can_view_authoring_thread,
    create_authoring_request,
    create_authoring_thread,
)
from .services.classroom import (
    ClassroomError,
    archive_session,
    can_manage_admission,
    can_view_display,
    can_view_session,
    create_activity_definition,
    delete_session,
    end_session,
    ensure_channel_states,
    join_authenticated,
    join_guest,
    launch_item,
    pause_session,
    post_message,
    publish_activity_to_channel,
    result_summary,
    revise_activity,
    revise_activity_definition,
    set_activity_state,
    set_chat_enabled,
    set_participant_admission,
    start_session,
    submit_answer,
    update_channel_visibility,
)


def _body(request) -> dict:
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        raise ClassroomError("Request body must be valid JSON.")
    if not isinstance(payload, dict):
        raise ClassroomError("Request body must be a JSON object.")
    return payload


def _error_code(message: str, status: int) -> str:
    """Map legacy command messages to the stable public error vocabulary."""
    normalized = message.casefold()
    if "idempotency key" in normalized or "already in progress" in normalized:
        return "idempotency_conflict"
    if "chat is disabled" in normalized:
        return "chat_disabled"
    if (
        status == 503
        or "temporarily unavailable" in normalized
        or "provider" in normalized
        and "unavailable" in normalized
    ):
        return "provider_unavailable"
    if any(
        phrase in normalized
        for phrase in (
            "not admitted",
            "join the classroom",
            "requires a django account",
            "approved roster",
            "not on this classroom's roster",
            "waiting room",
        )
    ):
        return "admission_required"
    if any(
        phrase in normalized
        for phrase in (
            "no longer accepting answers",
            "only an open activity",
            "only a live session",
            "ended session",
            "archive the ended session",
        )
    ):
        return "activity_closed"
    if status == 403 or "permission" in normalized:
        return "permission_denied"
    if "stale" in normalized or ("version" in normalized and "current" in normalized):
        return "stale_revision"
    if "revision" in normalized:
        return "invalid_revision"
    if status == 404:
        return "not_found"
    return "invalid_request"


def _error(message: str, status: int = 400, *, code: str | None = None):
    return JsonResponse(
        {"code": code or _error_code(message, status), "detail": message},
        status=status,
    )


def _idempotency_key(request) -> str | None:
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key:
        return None
    if len(key) > 160:
        raise ClassroomError("Idempotency-Key must be at most 160 characters.")
    return key


def _request_hash(request) -> str:
    """Hash the canonical JSON body so a key cannot be reused for new input."""
    raw = request.body or b"{}"
    try:
        raw = json.dumps(
            json.loads(raw),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    return hashlib.sha256(raw).hexdigest()


def _replay(request, session: LiveSession, command_type: str):
    try:
        key = _idempotency_key(request)
    except ClassroomError as exc:
        return _error(str(exc)), None
    if not key:
        return None, None
    request_hash = _request_hash(request)
    receipt = CommandReceipt.objects.filter(session=session, idempotency_key=key).first()
    if receipt is None:
        try:
            CommandReceipt.objects.create(
                session=session,
                idempotency_key=key,
                command_type=command_type,
                actor=request.user if request.user.is_authenticated else None,
                request_hash=request_hash,
                response={"pending": True},
                status_code=102,
            )
            return None, key
        except IntegrityError:
            receipt = CommandReceipt.objects.filter(session=session, idempotency_key=key).first()
            if receipt is None:
                raise
    actor_id = request.user.pk if request.user.is_authenticated else None
    if receipt.command_type != command_type or receipt.actor_id != actor_id:
        return _error("This idempotency key was already used for another command.", 409), key
    if receipt.request_hash and receipt.request_hash != request_hash:
        return _error("This idempotency key was already used with different input.", 409), key
    if receipt.status_code == 102 and isinstance(receipt.response, dict) and receipt.response.get("pending"):
        return _error("This command is already in progress; retry the request.", 409), key
    response = JsonResponse(receipt.response, status=receipt.status_code)
    response["Idempotent-Replay"] = "true"
    return response, key


def _record(session: LiveSession, key: str | None, command_type: str, request, response: JsonResponse) -> JsonResponse:
    if not key:
        return response
    actor = request.user if request.user.is_authenticated else None
    if response.status_code < 200 or response.status_code >= 300:
        CommandReceipt.objects.filter(
            session=session,
            idempotency_key=key,
            command_type=command_type,
            actor=actor,
            status_code=102,
        ).delete()
        return response
    try:
        payload = json.loads(response.content)
        updated = CommandReceipt.objects.filter(
            session=session,
            idempotency_key=key,
            command_type=command_type,
            actor=actor,
            status_code=102,
        ).update(response=payload, status_code=response.status_code)
        if not updated:
            CommandReceipt.objects.create(
                session=session,
                idempotency_key=key,
                command_type=command_type,
                actor=actor,
                request_hash=_request_hash(request),
                response=payload,
                status_code=response.status_code,
            )
    except IntegrityError:
        # A completed receipt may have been written by a concurrent retry.
        pass
    return response


def _authoring_replay(request, command_type: str):
    """Reserve or replay an authoring command for the authenticated owner."""
    try:
        key = _idempotency_key(request)
    except ClassroomError as exc:
        return _error(str(exc)), None
    if not key or not request.user.is_authenticated:
        return None, key
    request_hash = _request_hash(request)
    receipt = AuthoringCommandReceipt.objects.filter(owner=request.user, idempotency_key=key).first()
    if receipt is None:
        try:
            AuthoringCommandReceipt.objects.create(
                owner=request.user,
                idempotency_key=key,
                command_type=command_type,
                request_hash=request_hash,
                response={"pending": True},
                status_code=102,
            )
            return None, key
        except IntegrityError:
            receipt = AuthoringCommandReceipt.objects.filter(owner=request.user, idempotency_key=key).first()
            if receipt is None:
                raise
    if receipt.command_type != command_type:
        return _error("This idempotency key was already used for another command.", 409), key
    if receipt.request_hash and receipt.request_hash != request_hash:
        return _error("This idempotency key was already used with different input.", 409), key
    if receipt.status_code == 102 and isinstance(receipt.response, dict) and receipt.response.get("pending"):
        return _error("This command is already in progress; retry the request.", 409), key
    response = JsonResponse(receipt.response, status=receipt.status_code)
    response["Idempotent-Replay"] = "true"
    return response, key


def _record_authoring(request, key: str | None, command_type: str, response: JsonResponse) -> JsonResponse:
    if not key or not request.user.is_authenticated:
        return response
    if response.status_code < 200 or response.status_code >= 300:
        AuthoringCommandReceipt.objects.filter(
            owner=request.user,
            idempotency_key=key,
            command_type=command_type,
            status_code=102,
        ).delete()
        return response
    try:
        payload = json.loads(response.content)
        updated = AuthoringCommandReceipt.objects.filter(
            owner=request.user,
            idempotency_key=key,
            command_type=command_type,
            status_code=102,
        ).update(response=payload, status_code=response.status_code)
        if not updated:
            AuthoringCommandReceipt.objects.create(
                owner=request.user,
                idempotency_key=key,
                command_type=command_type,
                request_hash=_request_hash(request),
                response=payload,
                status_code=response.status_code,
            )
    except IntegrityError:
        pass
    return response


def _participant_for_request(request, session: LiveSession) -> Participant | None:
    session_data = getattr(request, "session", {})
    participant_id = session_data.get(f"liveclassroom.participant.{session.id}")
    if participant_id:
        return Participant.objects.filter(pk=participant_id, session=session).first()
    if request.user.is_authenticated:
        return Participant.objects.filter(session=session, user=request.user).first()
    return None


def _can_author_course(user, course: Course) -> bool:
    """Return whether a user may create reusable content for a course."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or course.created_by_id == user.pk:
        return True
    return course.memberships.filter(user=user, role="teacher").exists()


def _public_activity(
    activity: LiveActivity | None,
    *,
    channel_state=None,
    force_show_prompt: bool = False,
    force_hide_answer: bool = False,
    force_hide_explanation: bool = False,
) -> dict | None:
    if not activity:
        return None
    revision = (
        getattr(channel_state, "current_revision", None)
        if channel_state is not None and channel_state.current_activity_id == activity.id
        else None
    )
    revision = revision or (activity.current_revision if activity.current_revision_id else None)
    snapshot = revision.definition_snapshot.copy() if revision is not None else activity.definition_snapshot.copy()
    snapshot = deepcopy(snapshot)
    show_prompt = force_show_prompt or channel_state is None or channel_state.show_prompt
    show_explanation = (
        activity.state == LiveActivity.State.REVEALED
        if channel_state is None
        else channel_state.show_explanation
    )
    reveal_answer = (
        activity.state == LiveActivity.State.REVEALED
        if channel_state is None
        else channel_state.show_answer
    )
    if force_hide_answer:
        reveal_answer = False
    if force_hide_explanation:
        show_explanation = False
    if not show_prompt:
        snapshot = {
            key: snapshot[key]
            for key in ("schema_version", "type_key", "kind", "title")
            if key in snapshot
        }
    else:
        def redact(value):
            if isinstance(value, dict):
                hidden_keys = set()
                if not reveal_answer:
                    hidden_keys.update({"answer", "correct_answer"})
                if not show_explanation:
                    hidden_keys.update({"explanation", "explanation_markdown"})
                return {
                    key: redact(item)
                    for key, item in value.items()
                    if key not in hidden_keys
                }
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value

        snapshot = redact(snapshot)
    return {
        "id": activity.id,
        "state": activity.state,
        "revision": revision.revision if revision is not None else 1,
        "definition": snapshot,
    }


@require_POST
def start(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "session.start")
    if replay is not None:
        return replay
    try:
        start_session(session=session, actor=request.user)
    except ClassroomError as exc:
        return _record(session, key, "session.start", request, _error(str(exc), 403))
    response = JsonResponse(
        {"id": session.id, "status": session.status, "version": session.state_version}
    )
    return _record(session, key, "session.start", request, response)


@require_POST
def pause(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "session.pause")
    if replay is not None:
        return replay
    try:
        pause_session(session=session, actor=request.user)
    except ClassroomError as exc:
        return _record(session, key, "session.pause", request, _error(str(exc), 403))
    response = JsonResponse({"id": session.id, "status": session.status, "version": session.state_version})
    return _record(session, key, "session.pause", request, response)


@require_POST
def end(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "session.end")
    if replay is not None:
        return replay
    try:
        end_session(session=session, actor=request.user)
    except ClassroomError as exc:
        return _record(session, key, "session.end", request, _error(str(exc), 403))
    response = JsonResponse({"id": session.id, "status": session.status, "version": session.state_version})
    return _record(session, key, "session.end", request, response)


@require_POST
def archive(request, session_id: int):
    """Archive or restore an ended session while retaining its records."""
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "session.archive")
    if replay is not None:
        return replay
    try:
        archived = _body(request).get("archived", True)
        archive_session(session=session, actor=request.user, archived=archived)
    except ClassroomError as exc:
        return _record(session, key, "session.archive", request, _error(str(exc), 403))
    response = JsonResponse(
        {
            "id": session.id,
            "status": session.status,
            "archived": session.archived_at is not None,
            "version": session.state_version,
        }
    )
    return _record(session, key, "session.archive", request, response)


@require_POST
def delete(request, session_id: int):
    """Permanently delete an archived session only after explicit confirmation."""
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "session.delete")
    if replay is not None:
        return replay
    try:
        if _body(request).get("confirm") is not True:
            raise ClassroomError("Explicit confirmation is required to delete a session.")
        delete_session(session=session, actor=request.user)
    except ClassroomError as exc:
        return _record(session, key, "session.delete", request, _error(str(exc), 403))
    response = JsonResponse({"id": session.id, "deleted": True})
    return _record(session, key, "session.delete", request, response)


@require_http_methods(["GET", "POST"])
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
    threads = AuthoringThread.objects.filter(owner=request.user).values(
        "id", "title", "created_at", "updated_at"
    )
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
            if not _can_author_course(request.user, course):
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


@require_POST
def launch(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "activity.launch")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        if body.get("flow_item_id"):
            item = get_object_or_404(FlowItem, pk=body["flow_item_id"])
        elif body.get("flow_step_id"):
            item = get_object_or_404(FlowStep, pk=body["flow_step_id"])
        elif body.get("activity_definition_id"):
            item = get_object_or_404(ActivityDefinition, pk=body["activity_definition_id"])
        else:
            raise KeyError("activity")
        activity = launch_item(session=session, item=item, actor=request.user)
    except KeyError:
        return _record(session, key, "activity.launch", request, _error("flow_item_id is required."))
    except ClassroomError as exc:
        return _record(session, key, "activity.launch", request, _error(str(exc), 403))
    except Http404:
        return _record(session, key, "activity.launch", request, _error("The selected activity was not found.", 404))
    response = JsonResponse(
        {"activity_id": activity.id, "version": session.state_version}, status=201
    )
    return _record(session, key, "activity.launch", request, response)


@require_POST
def transition(request, activity_id: int, state: str):
    activity = get_object_or_404(LiveActivity, pk=activity_id)
    replay, key = _replay(request, activity.session, f"activity.{state}")
    if replay is not None:
        return replay
    try:
        set_activity_state(activity=activity, state=state, actor=request.user)
    except ClassroomError as exc:
        return _record(activity.session, key, f"activity.{state}", request, _error(str(exc), 403))
    response = JsonResponse({"activity_id": activity.id, "state": activity.state})
    return _record(activity.session, key, f"activity.{state}", request, response)


@require_POST
def publish_channel(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "channel.publish")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        activity = get_object_or_404(LiveActivity, pk=body["activity_id"])
        channel_state = publish_activity_to_channel(
            session=session,
            activity=activity,
            channel=body["channel"],
            actor=request.user,
            allow_review=body.get("allow_review"),
        )
    except KeyError as exc:
        return _record(session, key, "channel.publish", request, _error(f"{exc.args[0]} is required."))
    except ClassroomError as exc:
        return _record(session, key, "channel.publish", request, _error(str(exc), 403))
    except Http404:
        return _record(session, key, "channel.publish", request, _error("The selected activity was not found.", 404))
    return _record(session, key, "channel.publish", request, JsonResponse(
        {
            "session_id": session.id,
            "channel": channel_state.channel,
            "activity_id": channel_state.current_activity_id,
            "version": channel_state.version,
        }
    ))


@require_POST
def channel_settings(request, session_id: int):
    """Set prompt, reveal, aggregate, status, and review policy for one channel."""
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "channel.settings")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        channel = body.pop("channel")
        state = update_channel_visibility(session=session, channel=channel, actor=request.user, **body)
    except KeyError as exc:
        return _record(session, key, "channel.settings", request, _error(f"{exc.args[0]} is required."))
    except ClassroomError as exc:
        return _record(session, key, "channel.settings", request, _error(str(exc), 403))
    payload = {
        "session_id": session.id,
        "channel": state.channel,
        "version": state.version,
        "visibility": {
            field: getattr(state, field)
            for field in (
                "show_prompt",
                "show_aggregate",
                "show_answer",
                "show_explanation",
                "show_own_status",
                "allow_review",
            )
        },
    }
    return _record(session, key, "channel.settings", request, JsonResponse(payload))


@require_POST
def revise(request, activity_id: int):
    activity = get_object_or_404(LiveActivity.objects.select_related("session"), pk=activity_id)
    replay, key = _replay(request, activity.session, "activity.revise")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        revision = revise_activity(
            activity=activity,
            definition_snapshot=body["definition"],
            actor=request.user,
        )
    except KeyError:
        return _record(activity.session, key, "activity.revise", request, _error("definition is required."))
    except ClassroomError as exc:
        return _record(activity.session, key, "activity.revise", request, _error(str(exc), 403))
    response = JsonResponse(
        {"activity_id": activity.id, "revision": revision.revision}, status=201
    )
    return _record(activity.session, key, "activity.revise", request, response)


@require_POST
def join(request, join_code: str):
    session = get_object_or_404(LiveSession, join_code__iexact=join_code)
    replay, key = _replay(request, session, "participant.join")
    if replay is not None:
        return replay
    try:
        data = _body(request)
        display_name = data["display_name"]
        if not isinstance(display_name, str):
            raise ClassroomError("Display name must be text.")
        display_name = display_name.strip()
        if not display_name:
            raise ClassroomError("Display name is required.")
        guest_id = request.session.get(f"liveclassroom.guest.{session.id}")
        participant = join_guest(session=session, display_name=display_name, guest_id=guest_id)
    except KeyError:
        return _record(session, key, "participant.join", request, _error("display_name is required."))
    except ClassroomError as exc:
        return _record(session, key, "participant.join", request, _error(str(exc)))
    request.session[f"liveclassroom.guest.{session.id}"] = participant.guest_id
    request.session[f"liveclassroom.participant.{session.id}"] = participant.id
    return _record(
        session,
        key,
        "participant.join",
        request,
        JsonResponse(
            {
                "session_id": session.id,
                "participant_id": participant.id,
                "admission_state": participant.admission_state,
            },
            status=201,
        ),
    )


@require_POST
def join_account(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "participant.join-account")
    if replay is not None:
        return replay
    try:
        participant = join_authenticated(
            session=session,
            user=request.user,
            display_name=_body(request).get("display_name"),
        )
    except ClassroomError as exc:
        return _record(session, key, "participant.join-account", request, _error(str(exc), 403))
    request.session[f"liveclassroom.participant.{session.id}"] = participant.id
    return _record(
        session,
        key,
        "participant.join-account",
        request,
        JsonResponse(
            {
                "session_id": session.id,
                "participant_id": participant.id,
                "admission_state": participant.admission_state,
            },
            status=201,
        ),
    )


@require_POST
def admission(request, session_id: int, participant_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "participant.admission")
    if replay is not None:
        return replay
    try:
        participant = get_object_or_404(Participant, pk=participant_id, session=session)
        body = _body(request)
        requested_state = body.get("state")
        admitted = body.get("admitted")
        if requested_state is None and not isinstance(admitted, bool):
            raise ClassroomError("admitted must be a boolean or state must be supplied.")
        set_participant_admission(
            participant=participant,
            admitted=admitted if isinstance(admitted, bool) else None,
            state=requested_state,
            actor=request.user,
        )
    except ClassroomError as exc:
        return _record(session, key, "participant.admission", request, _error(str(exc), 403))
    except Http404:
        return _record(session, key, "participant.admission", request, _error("The participant was not found.", 404))
    return _record(
        session,
        key,
        "participant.admission",
        request,
        JsonResponse({"participant_id": participant.id, "admission_state": participant.admission_state}),
    )


@require_GET
def chat_messages(request, session_id: int):
    """Return only named public messages for an admitted viewer or staff member."""
    session = get_object_or_404(LiveSession, pk=session_id)
    participant = _participant_for_request(request, session)
    if participant and participant.admission_state != Participant.AdmissionState.ADMITTED:
        return _error("You are not admitted to this classroom.", 403)
    if not participant and not can_view_session(request.user, session):
        return _error("Join the classroom before viewing chat.", 403)
    messages = (
        session.messages.filter(deleted_at__isnull=True).values("id", "display_name", "body", "created_at")
        if session.chat_enabled or can_view_session(request.user, session)
        else []
    )
    return JsonResponse({"enabled": session.chat_enabled, "messages": list(messages)})


@require_GET
def participants(request, session_id: int):
    """Return the named roster to teaching staff without exposing guest tokens."""
    session = get_object_or_404(LiveSession, pk=session_id)
    if not can_manage_admission(request.user, session):
        return _error("You do not have permission to view participants.", 403)
    roster = session.participants.order_by("joined_at", "id").values(
        "id",
        "display_name",
        "user_id",
        "role",
        "admission_state",
        "joined_at",
        "last_seen_at",
        "connected_at",
        "disconnected_at",
        "removed_at",
    )
    return JsonResponse({"session_id": session.id, "participants": list(roster)})


@require_POST
def chat_send(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "message.create")
    if replay is not None:
        return replay
    participant = _participant_for_request(request, session)
    try:
        message = post_message(
            session=session,
            body=_body(request).get("body", ""),
            actor=request.user,
            participant=participant,
        )
    except ClassroomError as exc:
        return _record(session, key, "message.create", request, _error(str(exc), 403))
    return _record(
        session,
        key,
        "message.create",
        request,
        JsonResponse(
            {
                "id": message.id,
                "display_name": message.display_name,
                "body": message.body,
                "created_at": message.created_at,
            },
            status=201,
        ),
    )


@require_POST
def chat_settings(request, session_id: int):
    """Enable or disable the named public chat for one classroom."""
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "chat.settings")
    if replay is not None:
        return replay
    try:
        enabled = _body(request)["enabled"]
        if not isinstance(enabled, bool):
            return _record(
                session,
                key,
                "chat.settings",
                request,
                _error("enabled must be a boolean."),
            )
        set_chat_enabled(session=session, enabled=enabled, actor=request.user)
    except KeyError as exc:
        return _record(session, key, "chat.settings", request, _error(f"{exc.args[0]} is required."))
    except ClassroomError as exc:
        return _record(session, key, "chat.settings", request, _error(str(exc), 403))
    return _record(
        session,
        key,
        "chat.settings",
        request,
        JsonResponse(
            {
                "session_id": session.id,
                "enabled": session.chat_enabled,
                "chat_enabled": session.chat_enabled,
                "version": session.state_version,
            }
        ),
    )


@require_GET
def state(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    participant = _participant_for_request(request, session)
    staff_view = can_view_session(request.user, session)
    requested_channel = request.GET.get("channel")
    if requested_channel not in {None, *SessionChannelState.Channel.values}:
        return _error("Unsupported session channel.")
    channel = requested_channel or (
        SessionChannelState.Channel.PARTICIPANTS
        if participant or (staff_view and not can_view_display(request.user, session))
        else SessionChannelState.Channel.DISPLAY
    )
    if channel == SessionChannelState.Channel.DISPLAY and not can_view_display(request.user, session):
        return _error("The classroom display is restricted to teaching staff.", 403)
    if channel == SessionChannelState.Channel.PARTICIPANTS and not staff_view:
        if participant is None:
            return _error("Join the classroom before viewing participant state.", 403)
        if participant.admission_state != Participant.AdmissionState.ADMITTED:
            if participant.admission_state == Participant.AdmissionState.PENDING:
                return JsonResponse(
                    {
                        "protocol_version": 1,
                        "session_id": session.id,
                        "state_version": session.state_version,
                        "session": {
                            "id": session.id,
                            "title": session.title,
                            "status": session.status,
                            "version": session.state_version,
                            "chat_enabled": session.chat_enabled,
                            "access_mode": session.access_mode,
                            "admission_mode": session.admission_mode,
                        },
                        "channel": channel,
                        "current_activity": None,
                        "channels": {},
                        "participant": {
                            "id": participant.id,
                            "display_name": participant.display_name,
                            "admission_state": participant.admission_state,
                        },
                        "my_submission": None,
                        "aggregate": None,
                    }
                )
            return _error("You are not admitted to this classroom.", 403)
    states = ensure_channel_states(session)
    channel_state = (
        session.channel_states.filter(channel=channel)
        .select_related("current_activity", "current_revision")
        .first()
    )
    activity = channel_state.current_activity if channel_state and channel_state.current_activity_id else None
    # Sessions created before channel state existed need a compatibility fallback.
    if activity is None and not any(item.current_activity_id for item in states):
        activity = session.activities.order_by("-sequence").first()
    submission = None
    if participant and activity:
        submission = activity.submissions.filter(participant=participant).values("id", "answer", "is_stale").first()
    channels = {}
    # Observers and assistants may read participant analytics, but must not receive
    # projector content through the broad staff response.
    visible_states = (
        states
        if staff_view and can_view_display(request.user, session)
        else [channel_state]
        if channel_state
        else []
    )
    for other_state in visible_states:
        aggregate = (
            result_summary(other_state.current_activity)
            if other_state.current_activity_id and other_state.show_aggregate
            else None
        )
        channels[other_state.channel] = {
            "version": other_state.version,
            "activity": _public_activity(other_state.current_activity, channel_state=other_state),
            "visibility": {
                "show_prompt": other_state.show_prompt,
                "show_aggregate": other_state.show_aggregate,
                "show_answer": other_state.show_answer,
                "show_explanation": other_state.show_explanation,
                "show_own_status": other_state.show_own_status,
                "allow_review": other_state.allow_review,
            },
            "aggregate": aggregate,
        }
    current_aggregate = (
        result_summary(activity)
        if activity and channel_state and channel_state.show_aggregate
        else None
    )
    return JsonResponse(
        {
            "protocol_version": 1,
            "session_id": session.id,
            "state_version": session.state_version,
            "session": {
                "id": session.id,
                "title": session.title,
                "status": session.status,
                "version": session.state_version,
                "access_mode": session.access_mode,
                "admission_mode": session.admission_mode,
                "chat_enabled": session.chat_enabled,
            },
            "channel": channel,
            "current_activity": _public_activity(activity, channel_state=channel_state),
            "channels": channels,
            "participant": (
                {
                    "id": participant.id,
                    "display_name": participant.display_name,
                    "admission_state": participant.admission_state,
                }
                if participant
                else None
            ),
            "my_submission": submission if (staff_view or not channel_state or channel_state.show_own_status) else None,
            "aggregate": current_aggregate,
        }
    )


@require_GET
def history(request, session_id: int):
    """Return reviewable prior activities without exposing hidden answer data."""
    session = get_object_or_404(LiveSession, pk=session_id)
    participant = _participant_for_request(request, session)
    staff_view = can_view_session(request.user, session)
    if not participant and not staff_view:
        return _error("Join the classroom before viewing activity history.", 403)
    if participant and not staff_view and participant.admission_state != Participant.AdmissionState.ADMITTED:
        return _error("You are not admitted to this classroom.", 403)
    activities = session.activities.order_by("sequence")
    if not staff_view:
        activities = activities.filter(reviewable=True)
    participant_channel = (
        session.channel_states.filter(channel=SessionChannelState.Channel.PARTICIPANTS).first()
        if not staff_view
        else None
    )
    return JsonResponse(
        {
            "session_id": session.id,
            "activities": [
                _public_activity(
                    activity,
                    channel_state=participant_channel,
                    force_show_prompt=True,
                    force_hide_answer=participant_channel is None or not participant_channel.show_answer,
                    force_hide_explanation=participant_channel is None or not participant_channel.show_explanation,
                )
                for activity in activities
            ],
        }
    )


@require_POST
def submit(request, activity_id: int):
    activity = get_object_or_404(LiveActivity.objects.select_related("session"), pk=activity_id)
    replay, key = _replay(request, activity.session, "submission.submit")
    if replay is not None:
        return replay
    participant = _participant_for_request(request, activity.session)
    if not participant:
        return _record(
            activity.session,
            key,
            "submission.submit",
            request,
            _error("Join the classroom before submitting.", 403),
        )
    try:
        submission = submit_answer(activity=activity, participant=participant, answer=_body(request).get("answer", {}))
    except ClassroomError as exc:
        return _record(activity.session, key, "submission.submit", request, _error(str(exc), 409))
    return _record(
        activity.session,
        key,
        "submission.submit",
        request,
        JsonResponse({"submission_id": submission.id}, status=201),
    )


@require_GET
def results(request, activity_id: int):
    activity = get_object_or_404(LiveActivity.objects.select_related("session"), pk=activity_id)
    if not can_view_session(request.user, activity.session):
        return _error("You do not have permission to view results.", 403)
    return JsonResponse(result_summary(activity))


@require_GET
def analytics(request, session_id: int):
    """Return named attendance and response analytics to session staff."""
    session = get_object_or_404(LiveSession, pk=session_id)
    if not can_view_session(request.user, session):
        return _error("You do not have permission to view analytics.", 403)
    return JsonResponse(session_analytics(session))


@require_GET
def export_session(request, session_id: int):
    """Export a teacher-readable session archive or one bounded CSV dataset."""
    session = get_object_or_404(LiveSession, pk=session_id)
    if not can_manage_admission(request.user, session):
        return _error("You do not have permission to export this session.", 403)

    activities = list(session.activities.order_by("sequence").prefetch_related("submissions"))
    participants_rows = list(
        session.participants.order_by("joined_at", "id").values(
            "id",
            "display_name",
            "user_id",
            "role",
            "admission_state",
            "joined_at",
            "last_seen_at",
            "connected_at",
            "disconnected_at",
            "removed_at",
        )
    )
    response_rows = []
    for activity in activities:
        for submission in (
            activity.submissions.select_related("participant")
            .prefetch_related("revisions")
            .order_by("participant_id", "id")
        ):
            response_rows.append(
                {
                    "activity_id": activity.id,
                    "activity_sequence": activity.sequence,
                    "activity_revision": submission.current_revision.activity_revision_id
                    if submission.current_revision_id
                    else None,
                    "submission_id": submission.id,
                    "participant_id": submission.participant_id,
                    "display_name": submission.participant.display_name,
                    "answer": submission.answer,
                    "is_stale": submission.is_stale,
                    "is_correct": submission.is_correct,
                    "score": submission.score,
                    "submitted_at": submission.submitted_at,
                    "revisions": [
                        {
                            "id": revision.id,
                            "revision": revision.revision,
                            "activity_revision_id": revision.activity_revision_id,
                            "answer": revision.answer,
                            "is_correct": revision.is_correct,
                            "score": revision.score,
                            "created_at": revision.created_at,
                        }
                        for revision in submission.revisions.all()
                    ],
                }
            )
    chat_rows = list(
        session.messages.filter(deleted_at__isnull=True)
        .order_by("created_at", "id")
        .values("id", "display_name", "body", "created_at")
    )

    dataset = request.GET.get("dataset", "summary")
    output_format = request.GET.get("format", "json").lower()
    if output_format == "json":
        payload = {
            "protocol_version": 1,
            "session": {
                "id": session.id,
                "title": session.title,
                "join_code": session.join_code,
                "status": session.status,
                "mode": session.mode,
                "access_mode": session.access_mode,
                "admission_mode": session.admission_mode,
                "created_at": session.created_at,
                "started_at": session.started_at,
                "ended_at": session.ended_at,
            },
            "participants": participants_rows,
            "activities": [
                {
                    "id": activity.id,
                    "sequence": activity.sequence,
                    "kind": activity.kind,
                    "state": activity.state,
                    "reviewable": activity.reviewable,
                    "definition_snapshot": activity.definition_snapshot,
                    "revisions": [
                        {
                            "id": revision.id,
                            "revision": revision.revision,
                            "definition_snapshot": revision.definition_snapshot,
                            "created_at": revision.created_at,
                        }
                        for revision in activity.revisions.all()
                    ],
                }
                for activity in activities
            ],
            "responses": response_rows,
            "chat": chat_rows,
            "events": list(
                session.events.order_by("sequence").values("sequence", "event_type", "payload", "created_at")
            ),
        }
        response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False})
        response["Content-Disposition"] = f'attachment; filename="liveclassroom-{session.id}.json"'
        return response

    if output_format != "csv":
        return _error("format must be json or csv.")
    rows: list[dict] = []
    if dataset == "summary":
        for activity in activities:
            summary = result_summary(activity)
            rows.append(
                {
                    "activity_id": activity.id,
                    "sequence": activity.sequence,
                    "kind": activity.kind,
                    "state": activity.state,
                    "submission_count": summary.get("submission_count", 0),
                    "stale_submission_count": summary.get("stale_submission_count", 0),
                    "choices": json.dumps(summary.get("choices", {}), ensure_ascii=False, sort_keys=True),
                }
            )
    elif dataset == "responses":
        rows = response_rows
    elif dataset == "participants":
        rows = participants_rows
    elif dataset == "chat":
        rows = chat_rows
    else:
        return _error("Unsupported CSV dataset.")
    if dataset == "responses":
        rows = [
            {
                **row,
                "answer": json.dumps(row["answer"], ensure_ascii=False, sort_keys=True),
                "revisions": json.dumps(row["revisions"], default=str, ensure_ascii=False, sort_keys=True),
            }
            for row in rows
        ]
    fieldnames = list(rows[0]) if rows else {
        "summary": [
            "activity_id",
            "sequence",
            "kind",
            "state",
            "submission_count",
            "stale_submission_count",
            "choices",
        ],
        "responses": [
            "activity_id",
            "activity_sequence",
            "activity_revision",
            "submission_id",
            "participant_id",
            "display_name",
            "answer",
            "is_stale",
            "is_correct",
            "score",
            "submitted_at",
            "revisions",
        ],
        "participants": [
            "id",
            "display_name",
            "user_id",
            "role",
            "admission_state",
            "joined_at",
            "last_seen_at",
            "connected_at",
            "disconnected_at",
            "removed_at",
        ],
        "chat": ["id", "display_name", "body", "created_at"],
    }[dataset]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="liveclassroom-{session.id}-{dataset}.csv"'
    return response
