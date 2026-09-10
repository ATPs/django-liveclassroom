import hashlib
import json
from copy import deepcopy
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .integrations.host import host_can_view_named_responses
from .models import (
    ActivityDefinition,
    AuthoringCommandReceipt,
    ClassroomAsset,
    CommandReceipt,
    FlowStep,
    LiveActivity,
    LiveSession,
    Participant,
    SessionChannelState,
)
from .providers import ProviderError, content_providers
from .registry import activity_registry
from .services.analytics import session_analytics
from .services.assets import asset_descriptor
from .services.classroom import (
    ClassroomError,
    archive_session,
    can_manage_admission,
    can_manage_session,
    can_view_display,
    can_view_session,
    command_timer,
    delete_session,
    end_session,
    get_or_create_test_participant,
    join_authenticated,
    join_guest,
    launch_item,
    pause_session,
    post_message,
    public_result_summary,
    publish_activity_to_audiences,
    record_act_as_activation,
    remove_session_staff,
    result_summary,
    revise_activity,
    safe_activity_snapshot,
    session_capabilities,
    set_activity_state,
    set_chat_enabled,
    set_participant_admission,
    set_session_staff,
    start_session,
    submit_answer,
    timer_runtime_state,
    update_channel_visibility,
)
from .services.classroom import (
    close_and_show_answer as close_and_show_activity_answer,
)
from .services.exports import csv_export, json_archive
from .services.presentation import native_deck_state_payload, presentation_title


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
    return hashlib.sha256(request.method.encode() + b"\n" + request.path.encode() + b"\n" + raw).hexdigest()


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
            with transaction.atomic():
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
        with transaction.atomic():
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
            with transaction.atomic():
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
        with transaction.atomic():
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


def _act_as_context(request, session: LiveSession) -> tuple[Participant | None, bool]:
    """Resolve a short-lived teacher-selected participant without touching presence data."""
    token = request.GET.get("act_as_token")
    if not token and request.method != "GET":
        token = _body(request).get("act_as_token")
    if not token:
        return None, False
    try:
        payload = signing.loads(token, salt="liveclassroom.act-as", max_age=900)
        participant_id = payload["participant_id"]
        active = bool(payload.get("active"))
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        raise ClassroomError("The student-view token is invalid or has expired.") from exc
    if payload.get("session_id") != session.id or payload.get("actor_id") != request.user.pk:
        raise ClassroomError("The student-view token is not valid for this request.")
    if not can_manage_session(request.user, session):
        raise ClassroomError("You do not have permission to act as a participant.")
    participant = Participant.objects.filter(pk=participant_id, session=session).first()
    if participant is None:
        raise ClassroomError("The selected participant is no longer in this classroom.")
    return participant, active


def _student_view_token(*, session: LiveSession, participant: Participant, actor, active: bool) -> str:
    return signing.dumps(
        {"session_id": session.id, "participant_id": participant.id, "actor_id": actor.pk, "active": active},
        salt="liveclassroom.act-as",
        compress=True,
    )


def _public_activity(
    activity: LiveActivity | None,
    *,
    channel_state=None,
    request=None,
    session: LiveSession | None = None,
    participant: Participant | None = None,
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
    raw_snapshot = revision.definition_snapshot if revision is not None else activity.definition_snapshot
    snapshot = safe_activity_snapshot(raw_snapshot)
    snapshot = deepcopy(snapshot)
    def contains_content(value, keys):
        if isinstance(value, dict):
            if any(key in value and value[key] not in (None, "", []) for key in keys):
                return True
            return any(contains_content(item, keys) for item in value.values())
        if isinstance(value, list):
            return any(contains_content(item, keys) for item in value)
        return False

    has_answer = contains_content(snapshot, {"answer", "correct_answer"})
    has_explanation = contains_content(snapshot, {"explanation", "explanation_markdown", "feedback"})
    if isinstance(snapshot.get("title"), str):
        snapshot["title"] = presentation_title(snapshot["title"])
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
                    hidden_keys.update({"explanation", "explanation_markdown", "feedback"})
                return {
                    key: redact(item)
                    for key, item in value.items()
                    if key not in hidden_keys
                }
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value

        snapshot = redact(snapshot)
        metadata = snapshot.get("metadata")
        if isinstance(metadata, dict):
            feedback = metadata.get("feedback") if show_explanation else None
            if isinstance(feedback, dict) and feedback:
                snapshot["metadata"] = {"feedback": feedback}
            else:
                snapshot.pop("metadata", None)
    type_key = snapshot.get("type_key") if isinstance(snapshot, dict) else None
    if not isinstance(type_key, str) or not type_key:
        type_key = f"liveclassroom.{activity.kind}"
    try:
        manifest = dict(activity_registry.get(type_key).frontend_manifest)
    except KeyError:
        manifest = {}
    if type_key == "liveclassroom.file" and revision is not None and revision.asset_id:
        content = snapshot.get("content")
        if isinstance(content, dict):
            content = dict(content)
            content_url = None
            download_url = None
            document_note_url = None
            document_slides_url = None
            if request is not None and session is not None:
                content_url = reverse(
                    "liveclassroom:api-v1-session-asset-content",
                    args=[session.id, revision.id, revision.asset.public_id],
                )
                if can_manage_session(request.user, session):
                    download_url = f"{content_url}?download=1"
                if revision.asset.kind == ClassroomAsset.Kind.MARKDOWN:
                    document_note_url = reverse(
                        "liveclassroom:api-v1-session-document-root",
                        args=[session.id, revision.id, revision.asset.public_id],
                    )
                    document_slides_url = reverse(
                        "liveclassroom:api-v1-session-document-slides",
                        args=[session.id, revision.id, revision.asset.public_id, revision.asset.original_name],
                    )
            content["asset"] = asset_descriptor(
                revision.asset,
                content_url=content_url,
                download_url=download_url,
                document_note_url=document_note_url,
                document_slides_url=document_slides_url,
            )
            snapshot["content"] = content
    if (
        channel_state is not None
        and getattr(channel_state, "channel", None) == SessionChannelState.Channel.PARTICIPANTS
        and participant is not None
        and participant.admission_state == Participant.AdmissionState.ADMITTED
        and session is not None
    ):
        content = snapshot.get("content")
        if isinstance(content, dict) and content.get("provider") == "vaultpub" and isinstance(content.get("url"), str):
            content = dict(content)
            try:
                provider = content_providers().get("vaultpub")
                reference = provider.parse_reference(content["url"], request=request)
                grant = provider.grant_participant_access(
                    reference, session=session, participant=participant, request=request
                )
                embed_url = grant.get("embed_url") if isinstance(grant, dict) else None
                parsed_url = urlsplit(embed_url) if isinstance(embed_url, str) else None
                if (
                    parsed_url is None
                    or not embed_url.startswith("/")
                    or embed_url.startswith("//")
                    or parsed_url.scheme
                    or parsed_url.netloc
                ):
                    raise ProviderError("The VaultPub participant URL is unavailable.")
                content["url"] = embed_url
            except (ProviderError, TypeError, ValueError):
                content.pop("url", None)
                content["media_disabled"] = True
            snapshot["content"] = content
    if revision is not None and request is not None and session is not None and show_prompt:
        # The URL identifies a fixed run revision, but the fragment endpoint
        # repeats participant and release checks on every request.  Do not add
        # a link for a field that the normal public payload has redacted.
        from .fragment_views import fragment_markdown, revision_key

        fields = ["prompt"]
        if show_explanation:
            fields.extend(["explanation", "feedback_correct", "feedback_incorrect"])
        urls = {
            field: {
                "url": reverse(
                    "liveclassroom:api-v1-session-fragment",
                    args=[session.id, revision.id, field],
                ),
                "revision_key": revision_key(revision),
            }
            for field in fields
            if fragment_markdown(revision, field) is not None
        }
        if urls:
            snapshot["fragment_urls"] = urls
    return {
        "id": activity.id,
        "state": activity.state,
        "revision": revision.revision if revision is not None else 1,
        "revision_id": revision.id if revision is not None else None,
        "definition": snapshot,
        "has_answer": has_answer,
        "has_explanation": has_explanation,
        "frontend_manifest": manifest,
        "runtime": timer_runtime_state(activity) if activity.kind == "timer" else None,
    }


@require_POST
@transaction.atomic
def start(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "session.start")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        step_id = body.get("plan_step_id")
        step = None
        if step_id is not None:
            from .models import SessionPlanStep
            step = get_object_or_404(SessionPlanStep, pk=step_id, session=session, removed=False)
        start_session(session=session, actor=request.user, starting_item=step)
    except ClassroomError as exc:
        return _record(session, key, "session.start", request, _error(str(exc), 403))
    response = JsonResponse(
        {"id": session.id, "status": session.status, "version": session.state_version}
    )
    return _record(session, key, "session.start", request, response)


@require_POST
@transaction.atomic
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
@transaction.atomic
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
@transaction.atomic
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
@transaction.atomic
def delete(request, session_id: int):
    """Permanently delete an archived session only after explicit confirmation."""
    session = get_object_or_404(LiveSession, pk=session_id)
    deleted_session_id = session.id
    replay, key = _replay(request, session, "session.delete")
    if replay is not None:
        return replay
    try:
        if _body(request).get("confirm") is not True:
            raise ClassroomError("Explicit confirmation is required to delete a session.")
        delete_session(session=session, actor=request.user)
    except ClassroomError as exc:
        return _record(session, key, "session.delete", request, _error(str(exc), 403))
    # Session-scoped command receipts are removed by this cascading delete, so
    # a successful deletion cannot persist a replay record on the deleted row.
    return JsonResponse({"id": deleted_session_id, "deleted": True})


@require_POST
@transaction.atomic
def launch(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "activity.launch")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        if body.get("flow_step_id"):
            item = get_object_or_404(FlowStep, pk=body["flow_step_id"])
        elif body.get("activity_definition_id"):
            item = get_object_or_404(ActivityDefinition, pk=body["activity_definition_id"])
        else:
            raise KeyError("activity")
        activity = launch_item(
            session=session,
            item=item,
            actor=request.user,
            channel=body.get("channel", SessionChannelState.Channel.DISPLAY),
        )
    except KeyError:
        return _record(
            session,
            key,
            "activity.launch",
            request,
            _error("flow_step_id or activity_definition_id is required."),
        )
    except ClassroomError as exc:
        return _record(session, key, "activity.launch", request, _error(str(exc), 403))
    except Http404:
        return _record(session, key, "activity.launch", request, _error("The selected activity was not found.", 404))
    session.refresh_from_db(fields=["state_version"])
    response = JsonResponse(
        {"activity_id": activity.id, "version": session.state_version}, status=201
    )
    return _record(session, key, "activity.launch", request, response)


@require_POST
@transaction.atomic
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
@transaction.atomic
def close_and_show_answer(request, activity_id: int):
    """Close responses and reveal an answer as one replayable command."""
    activity = get_object_or_404(LiveActivity.objects.select_related("session"), pk=activity_id)
    replay, key = _replay(request, activity.session, "activity.close-and-show-answer")
    if replay is not None:
        return replay
    try:
        activity = close_and_show_activity_answer(activity=activity, actor=request.user)
    except ClassroomError as exc:
        return _record(
            activity.session, key, "activity.close-and-show-answer", request, _error(str(exc), 403)
        )
    return _record(
        activity.session,
        key,
        "activity.close-and-show-answer",
        request,
        JsonResponse({"activity_id": activity.id, "state": activity.state, "show_answer": True}),
    )


@require_POST
@transaction.atomic
def timer(request, activity_id: int):
    """Start, pause, resume, or reset a timer's server runtime state."""
    activity = get_object_or_404(LiveActivity.objects.select_related("session"), pk=activity_id)
    replay, key = _replay(request, activity.session, "timer.command")
    if replay is not None:
        return replay
    try:
        action = _body(request)["action"]
        runtime = command_timer(activity=activity, action=action, actor=request.user)
        activity.session.refresh_from_db(fields=["state_version"])
    except KeyError:
        return _record(activity.session, key, "timer.command", request, _error("action is required."))
    except ClassroomError as exc:
        return _record(activity.session, key, "timer.command", request, _error(str(exc), 403))
    return _record(
        activity.session,
        key,
        "timer.command",
        request,
        JsonResponse({
            "activity_id": activity.id,
            "runtime": runtime,
            "server_time": timezone.now().timestamp(),
            "version": activity.session.state_version,
        }),
    )


@require_POST
@transaction.atomic
def publish_channel(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "channel.publish")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        activity = get_object_or_404(LiveActivity, pk=body["activity_id"])
        channel = body["channel"]
        states = publish_activity_to_audiences(
            session=session,
            activity=activity,
            channels=["display", "participants"] if channel == "both" else [channel],
            actor=request.user,
            allow_review=body.get("allow_review"),
        )
        session.refresh_from_db(fields=["state_version"])
        channel_state = states[0]
    except KeyError as exc:
        return _record(session, key, "channel.publish", request, _error(f"{exc.args[0]} is required."))
    except ClassroomError as exc:
        return _record(session, key, "channel.publish", request, _error(str(exc), 403))
    except Http404:
        return _record(session, key, "channel.publish", request, _error("The selected activity was not found.", 404))
    return _record(session, key, "channel.publish", request, JsonResponse(
        {
            "session_id": session.id,
            "channel": body["channel"],
            "activity_id": channel_state.current_activity_id,
            "version": session.state_version,
        }
    ))


@require_POST
@transaction.atomic
def channel_settings(request, session_id: int):
    """Set prompt, reveal, aggregate, status, and review policy for one channel."""
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "channel.settings")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        channel = body.pop("channel")
        channels = (
            [SessionChannelState.Channel.DISPLAY, SessionChannelState.Channel.PARTICIPANTS]
            if channel == "both"
            else [channel]
        )
        with transaction.atomic():
            states = [
                update_channel_visibility(session=session, channel=target, actor=request.user, **body)
                for target in channels
            ]
        state = states[-1]
    except KeyError as exc:
        return _record(session, key, "channel.settings", request, _error(f"{exc.args[0]} is required."))
    except ClassroomError as exc:
        return _record(session, key, "channel.settings", request, _error(str(exc), 403))
    payload = {
        "session_id": session.id,
        "channel": channel,
        "version": state.version,
        "visibility": {
            field: (
                bool(state.current_activity_id and state.current_activity.reviewable)
                if field == "allow_review"
                else getattr(state, field)
            )
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
@transaction.atomic
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
@transaction.atomic
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
@transaction.atomic
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
@transaction.atomic
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
    try:
        participant, acting_as = _act_as_context(request, session)
    except ClassroomError as exc:
        return _error(str(exc), 403)
    participant = participant or _participant_for_request(request, session)
    if participant and participant.admission_state != Participant.AdmissionState.ADMITTED:
        return _error("You are not admitted to this classroom.", 403)
    if not participant and not can_view_session(request.user, session):
        return _error("Join the classroom before viewing chat.", 403)
    # The managed test identity is intentionally isolated from the classroom
    # chat stream. It exercises answers without simulating a student device.
    if participant and participant.is_test:
        return JsonResponse({"enabled": False, "messages": []})
    messages = (
        session.messages.filter(deleted_at__isnull=True).values("id", "display_name", "body", "created_at")
        if session.chat_enabled or (not acting_as and can_view_session(request.user, session))
        else []
    )
    return JsonResponse({"enabled": session.chat_enabled, "messages": list(messages)})


@require_GET
def participants(request, session_id: int):
    """Return the named roster to teaching staff without exposing guest tokens."""
    session = get_object_or_404(LiveSession, pk=session_id)
    if not can_manage_admission(request.user, session):
        return _error("You do not have permission to view participants.", 403)
    roster = list(session.participants.filter(is_test=False).order_by("joined_at", "id").values(
        "id",
        "display_name",
        "user_id",
        "admission_state",
        "joined_at",
        "last_seen_at",
        "connected_at",
        "disconnected_at",
        "removed_at",
    ))
    for participant in roster:
        participant["inspection_token"] = _student_view_token(
            session=session,
            participant=Participant(id=participant["id"], session_id=session.id),
            actor=request.user,
            active=False,
        )
    return JsonResponse({"session_id": session.id, "participants": roster})


@require_POST
@transaction.atomic
def activate_student_view(request, session_id: int):
    """Issue an audited action token after a manager explicitly confirms act-as."""
    session = get_object_or_404(LiveSession, pk=session_id)
    try:
        body = _body(request)
        participant_id = body["participant_id"]
        if body.get("confirm") is not True:
            raise ClassroomError("Explicit confirmation is required to act as a participant.")
        participant = get_object_or_404(Participant, pk=participant_id, session=session)
        record_act_as_activation(session=session, participant=participant, actor=request.user)
    except KeyError as exc:
        return _error(f"{exc.args[0]} is required.")
    except ClassroomError as exc:
        return _error(str(exc), 403)
    return JsonResponse({
        "act_as_token": _student_view_token(session=session, participant=participant, actor=request.user, active=True)
    })


@require_POST
@transaction.atomic
def test_student(request, session_id: int):
    """Create/reuse a manager-owned test participant and activate it."""
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "participant.test-student")
    if replay is not None:
        return replay
    try:
        participant = get_or_create_test_participant(session=session, actor=request.user)
        record_act_as_activation(session=session, participant=participant, actor=request.user)
    except ClassroomError as exc:
        return _record(session, key, "participant.test-student", request, _error(str(exc), 403))
    response = JsonResponse({
        "participant": {"id": participant.id, "display_name": participant.display_name, "is_test": True},
        "act_as_token": _student_view_token(session=session, participant=participant, actor=request.user, active=True),
        "expires_in": 900,
    })
    return _record(session, key, "participant.test-student", request, response)


@require_POST
def renew_test_student(request, session_id: int):
    """Refresh a manager-owned test token without creating another audit event."""
    session = get_object_or_404(LiveSession, pk=session_id)
    if not can_manage_session(request.user, session):
        return _error("You do not have permission to renew this test student.", 403)
    participant = Participant.objects.filter(
        session=session,
        test_owner=request.user,
        is_test=True,
        admission_state=Participant.AdmissionState.ADMITTED,
    ).first()
    if participant is None:
        return _error("Open the test student before renewing its token.", 404)
    return JsonResponse({
        "participant": {"id": participant.id, "display_name": participant.display_name, "is_test": True},
        "act_as_token": _student_view_token(session=session, participant=participant, actor=request.user, active=True),
        "expires_in": 900,
    })


def _staff_payload(assignment, session: LiveSession) -> dict:
    user = assignment.user
    return {
        "id": assignment.id,
        "user_id": user.id,
        "username": user.get_username(),
        "display_name": user.get_full_name() or user.get_username(),
        "role": assignment.role,
        "capabilities": list(session_capabilities(user, session)),
        "created_at": assignment.created_at,
    }


@require_GET
def staff(request, session_id: int):
    """Expose the session's explicit staff roles and caller capabilities."""
    session = get_object_or_404(LiveSession, pk=session_id)
    if not can_view_session(request.user, session):
        return _error("You do not have permission to view session staff.", 403)
    assignments = session.staff.select_related("user").order_by("created_at", "id")
    return JsonResponse(
        {
            "session_id": session.id,
            "my_capabilities": list(session_capabilities(request.user, session)),
            "staff": [_staff_payload(assignment, session) for assignment in assignments],
        }
    )


@require_POST
@transaction.atomic
def staff_assign(request, session_id: int):
    """Create or replace an explicit co-host, assistant, or observer role."""
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "staff.assign")
    if replay is not None:
        return replay
    try:
        data = _body(request)
        user_id = data["user_id"]
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            raise ClassroomError("user_id must be a positive integer.")
        role = data["role"]
        if not isinstance(role, str):
            raise ClassroomError("role must be text.")
        user = get_user_model().objects.get(pk=user_id)
        assignment = set_session_staff(session=session, user=user, role=role, actor=request.user)
    except KeyError as exc:
        return _record(session, key, "staff.assign", request, _error(f"{exc.args[0]} is required."))
    except get_user_model().DoesNotExist:
        return _record(session, key, "staff.assign", request, _error("The selected user was not found.", 404))
    except ClassroomError as exc:
        return _record(session, key, "staff.assign", request, _error(str(exc), 403))
    return _record(
        session,
        key,
        "staff.assign",
        request,
        JsonResponse(_staff_payload(assignment, session), status=201),
    )


@require_POST
@transaction.atomic
def staff_remove(request, session_id: int, staff_id: int):
    """Remove an explicit staff assignment without deleting audit history."""
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "staff.remove")
    if replay is not None:
        return replay
    assignment = session.staff.filter(pk=staff_id).first()
    if assignment is None:
        return _record(session, key, "staff.remove", request, _error("The staff assignment was not found.", 404))
    try:
        remove_session_staff(session=session, assignment=assignment, actor=request.user)
    except ClassroomError as exc:
        return _record(session, key, "staff.remove", request, _error(str(exc), 403))
    return _record(session, key, "staff.remove", request, JsonResponse({"id": staff_id, "removed": True}))


@require_POST
@transaction.atomic
def chat_send(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    replay, key = _replay(request, session, "message.create")
    if replay is not None:
        return replay
    try:
        participant, active = _act_as_context(request, session)
    except ClassroomError as exc:
        return _record(session, key, "message.create", request, _error(str(exc), 403))
    if participant is not None and not active:
        return _record(
            session,
            key,
            "message.create",
            request,
            _error("Activate act-as before sending as this participant.", 403),
        )
    participant = participant or _participant_for_request(request, session)
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
@transaction.atomic
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
    try:
        participant, active = _act_as_context(request, session)
    except ClassroomError as exc:
        return _error(str(exc), 403)
    acting_as = participant is not None
    preview = request.GET.get("preview") == "1"
    if preview and (acting_as or not can_manage_session(request.user, session)):
        return _error("You do not have permission to preview participant state.", 403)
    # Passive staff preview is deliberately identity-free, even when this
    # browser also carries a participant cookie from a separate test tab.
    # It must not render, submit, or expose any real student's own record.
    participant = None if preview else participant or _participant_for_request(request, session)
    staff_view = not preview and not acting_as and can_view_session(request.user, session)
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
    if channel == SessionChannelState.Channel.PARTICIPANTS and not staff_view and not preview:
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
    states = list(
        session.channel_states.select_related("current_activity", "current_revision").order_by("channel")
    )
    channel_state = (
        session.channel_states.filter(channel=channel)
        .select_related("current_activity", "current_revision")
        .first()
    )
    activity = channel_state.current_activity if channel_state and channel_state.current_activity_id else None
    from .services.presentation import native_deck_entry

    channel_has_native_deck = bool(channel_state and native_deck_entry(session, channel))
    if channel_has_native_deck:
        # A native deck is an independent delivery surface. Keep the prior
        # activity record for history, but do not expose it as the current
        # content for this audience.
        activity = None
    if not staff_view and session.status == LiveSession.Status.ENDED:
        activity = None
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
    if not staff_view and session.status == LiveSession.Status.ENDED:
        visible_states = []
    for other_state in visible_states:
        aggregate = (
            public_result_summary(other_state.current_activity)
            if other_state.current_activity_id and other_state.show_aggregate
            else None
        )
        native_deck = native_deck_state_payload(request=request, session=session, state=other_state)
        channels[other_state.channel] = {
            "version": other_state.version,
            "activity": _public_activity(
                None if native_deck else other_state.current_activity,
                channel_state=other_state,
                request=request,
                session=session,
                participant=participant,
            ),
            "visibility": {
                "show_prompt": other_state.show_prompt,
                "show_aggregate": other_state.show_aggregate,
                "show_answer": other_state.show_answer,
                "show_explanation": other_state.show_explanation,
                "show_own_status": other_state.show_own_status,
                "allow_review": bool(other_state.current_activity_id and other_state.current_activity.reviewable),
            },
            "presentation": {
                "page": other_state.document_page,
                "navigation_mode": other_state.document_navigation,
            },
            "deck": native_deck,
            "aggregate": aggregate,
        }
    current_aggregate = (
        public_result_summary(activity)
        if activity and channel_state and channel_state.show_aggregate
        else None
    )
    return JsonResponse(
        {
            "protocol_version": 1,
            "session_id": session.id,
            "state_version": session.state_version,
            "server_time": timezone.now().timestamp(),
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
            "current_activity": _public_activity(
                None if channel_has_native_deck else activity,
                channel_state=channel_state,
                request=request,
                session=session,
                participant=participant,
            ),
            "current_deck": (
                native_deck_state_payload(request=request, session=session, state=channel_state)
                if channel_state and (staff_view or session.status != LiveSession.Status.ENDED)
                else None
            ),
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
            "act_as_active": (active if acting_as else not preview) and session.status != LiveSession.Status.ENDED,
        }
    )


@require_POST
@transaction.atomic
def submit(request, activity_id: int):
    activity = get_object_or_404(LiveActivity.objects.select_related("session"), pk=activity_id)
    replay, key = _replay(request, activity.session, "submission.submit")
    if replay is not None:
        return replay
    try:
        participant, active = _act_as_context(request, activity.session)
    except ClassroomError as exc:
        return _record(activity.session, key, "submission.submit", request, _error(str(exc), 403))
    if participant is not None and not active:
        return _record(
            activity.session,
            key,
            "submission.submit",
            request,
            _error("Activate act-as before submitting.", 403),
        )
    participant = participant or _participant_for_request(request, activity.session)
    if not participant:
        return _record(
            activity.session,
            key,
            "submission.submit",
            request,
            _error("Join the classroom before submitting.", 403),
        )
    try:
        body = _body(request)
        revision_id = body.get("activity_revision_id")
        if isinstance(revision_id, bool) or not isinstance(revision_id, int) or revision_id <= 0:
            raise ClassroomError("activity_revision_id is required.")
        submission = submit_answer(
            activity=activity, participant=participant, answer=body.get("answer", {}), actor=request.user,
            activity_revision_id=revision_id, require_published=True,
        )
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
    if not host_can_view_named_responses(
        actor=request.user, session_id=session.id, request=request, package_allowed=True
    ):
        return _error("You do not have permission to view analytics.", 403)
    return JsonResponse(session_analytics(session))


@require_GET
def export_session(request, session_id: int):
    """Stream a teacher-readable session archive or one bounded CSV dataset."""
    session = get_object_or_404(LiveSession, pk=session_id)
    if not can_manage_admission(request.user, session):
        return _error("You do not have permission to export this session.", 403)
    if not host_can_view_named_responses(
        actor=request.user, session_id=session.id, request=request, package_allowed=True
    ):
        return _error("You do not have permission to export this session.", 403)

    dataset = request.GET.get("dataset", "summary")
    output_format = request.GET.get("format", "json").lower()
    if output_format == "json":
        response = StreamingHttpResponse(json_archive(session), content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="liveclassroom-{session.id}.json"'
        return response
    if output_format != "csv":
        return _error("format must be json or csv.")
    if dataset not in {"summary", "responses", "participants", "chat"}:
        return _error("Unsupported CSV dataset.")
    response = StreamingHttpResponse(csv_export(session, dataset), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="liveclassroom-{session.id}-{dataset}.csv"'
    return response
