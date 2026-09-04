"""Private file authoring and delivery endpoints for classroom presentations."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

from django.db import transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .api import _body, _error, _participant_for_request
from .models import ActivityRunRevision, ClassroomAsset, Flow, LiveSession, Participant, SessionChannelState
from .services.assets import (
    asset_descriptor,
    create_server_path_asset,
    create_uploaded_asset,
    discard_uploaded_asset,
    open_asset,
)
from .services.classroom import (
    ClassroomError,
    can_manage_session,
    can_view_session,
    create_activity_definition,
    launch_item,
    publish_activity_to_channel,
    update_document_presentation,
)
from .services.flows import add_flow_step, can_edit_flow


def _payload_and_asset(request) -> tuple[dict, ClassroomAsset]:
    if not getattr(request.user, "is_authenticated", False):
        raise ClassroomError("An authenticated teacher is required.")
    uploaded = request.FILES.get("file")
    if uploaded is not None:
        payload = request.POST.dict()
        # FormData carries channel lists as JSON; preserve the JSON endpoint's
        # data contract instead of treating its serialized list as a string.
        if "channels" in payload:
            try:
                payload["channels"] = json.loads(payload["channels"])
            except json.JSONDecodeError:
                pass
        return payload, create_uploaded_asset(owner=request.user, uploaded_file=uploaded)
    payload = _body(request)
    return payload, create_server_path_asset(owner=request.user, raw_path=payload.get("server_path"))


def _file_definition(asset: ClassroomAsset, payload: dict) -> tuple[str, dict]:
    title = str(payload.get("title") or asset.original_name).strip()[:200]
    if not title:
        raise ClassroomError("A presentation title is required.")
    caption = payload.get("caption", "")
    if not isinstance(caption, str):
        raise ClassroomError("caption must be text.")
    return title, {
        "asset_id": str(asset.public_id),
        "file_kind": asset.kind,
        "caption": caption.strip(),
    }


def _asset_response(asset: ClassroomAsset) -> dict:
    content_url = reverse("liveclassroom:api-v1-asset-content", args=[asset.public_id])
    return asset_descriptor(asset, content_url=content_url, download_url=f"{content_url}?download=1")


@require_POST
def flow_file(request, flow_id: int):
    """Create one private asset and a reusable file step in a single command."""
    flow = get_object_or_404(Flow, pk=flow_id)
    if not can_edit_flow(request.user, flow):
        return _error("You do not have permission to edit this flow.", 403)
    asset = None
    try:
        with transaction.atomic():
            payload, asset = _payload_and_asset(request)
            title, definition = _file_definition(asset, payload)
            activity = create_activity_definition(
                owner=request.user,
                title=title,
                type_key="liveclassroom.file",
                definition=definition,
                course=flow.course,
                asset=asset,
            )
            step = add_flow_step(flow=flow, actor=request.user, activity_definition=activity)
    except ClassroomError as exc:
        if asset is not None:
            discard_uploaded_asset(asset)
        return _error(str(exc), 400)
    return JsonResponse(
        {
            "asset": _asset_response(asset),
            "step": {
                "id": step.id,
                "position": step.position,
                "title": activity.title,
                "activity_definition_id": activity.id,
            },
        },
        status=201,
    )


@require_POST
def session_file(request, session_id: int):
    """Create an ad hoc file activity and present it to the requested channels."""
    session = get_object_or_404(LiveSession, pk=session_id)
    if not can_manage_session(request.user, session):
        return _error("You do not have permission to control this session.", 403)
    asset = None
    try:
        with transaction.atomic():
            payload, asset = _payload_and_asset(request)
            channels = payload.get("channels", [SessionChannelState.Channel.DISPLAY])
            if not isinstance(channels, list) or not channels or len(set(channels)) != len(channels):
                raise ClassroomError("channels must be a non-empty list of unique audience channels.")
            if any(channel not in SessionChannelState.Channel.values for channel in channels):
                raise ClassroomError("Unsupported session channel.")
            title, definition = _file_definition(asset, payload)
            activity_definition = create_activity_definition(
                owner=request.user,
                title=title,
                type_key="liveclassroom.file",
                definition=definition,
                course=session.course,
                asset=asset,
            )
            first_channel = (
                SessionChannelState.Channel.DISPLAY
                if SessionChannelState.Channel.DISPLAY in channels
                else SessionChannelState.Channel.PARTICIPANTS
            )
            activity = launch_item(session=session, item=activity_definition, actor=request.user, channel=first_channel)
            for channel in channels:
                if channel != first_channel:
                    publish_activity_to_channel(session=session, activity=activity, channel=channel, actor=request.user)
    except ClassroomError as exc:
        if asset is not None:
            discard_uploaded_asset(asset)
        return _error(str(exc), 400)
    return JsonResponse({"asset": _asset_response(asset), "activity_id": activity.id, "channels": channels}, status=201)


@require_POST
def presentation(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    try:
        body = _body(request)
        states = update_document_presentation(
            session=session,
            actor=request.user,
            channels=body.get("channels", []),
            page=body.get("page"),
            navigation=body.get("navigation_mode"),
        )
    except ClassroomError as exc:
        return _error(str(exc), 403)
    return JsonResponse(
        {
            "channels": [
                {"channel": state.channel, "page": state.document_page, "navigation_mode": state.document_navigation}
                for state in states
            ],
            "version": session.state_version,
        }
    )


def _can_read_session_asset(request, session: LiveSession, revision: ActivityRunRevision) -> bool:
    if can_view_session(request.user, session):
        return True
    participant = _participant_for_request(request, session)
    if participant is None or participant.admission_state != Participant.AdmissionState.ADMITTED:
        return False
    participant_state = session.channel_states.filter(channel=SessionChannelState.Channel.PARTICIPANTS).first()
    return bool(
        participant_state
        and (
            participant_state.current_revision_id == revision.id
            or revision.activity.reviewable
        )
    )


def _range_bounds(header: str, size: int) -> tuple[int, int] | None:
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not match:
        return None
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None
    if not start_text:
        length = int(end_text)
        if length < 1:
            return None
        return max(size - length, 0), size - 1
    start = int(start_text)
    end = int(end_text) if end_text else size - 1
    if start >= size or end < start:
        return None
    return start, min(end, size - 1)


def _chunks(handle, start: int, length: int) -> Iterator[bytes]:
    try:
        handle.seek(start)
        remaining = length
        while remaining:
            chunk = handle.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        handle.close()


def _stream_asset(request, asset: ClassroomAsset, *, allow_download: bool) -> StreamingHttpResponse:
    handle, size = open_asset(asset)
    requested_range = request.headers.get("Range", "")
    bounds = _range_bounds(requested_range, size) if requested_range else (0, size - 1)
    if bounds is None:
        handle.close()
        response = StreamingHttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        return response
    start, end = bounds
    response = StreamingHttpResponse(_chunks(handle, start, end - start + 1), content_type=asset.content_type)
    response.status_code = 206 if requested_range else 200
    response["Accept-Ranges"] = "bytes"
    response["Content-Length"] = str(end - start + 1)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    disposition = "attachment" if allow_download else "inline"
    filename = asset.original_name.replace("\\", "_").replace('"', "_").replace("\r", "_").replace("\n", "_")
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    if requested_range:
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    return response


@require_GET
def asset_content(request, asset_id):
    asset = get_object_or_404(ClassroomAsset, public_id=asset_id)
    if not getattr(request.user, "is_authenticated", False) or (
        asset.owner_id != request.user.pk and not request.user.is_superuser
    ):
        return _error("The requested file is unavailable.", 404)
    download = request.GET.get("download") == "1"
    try:
        return _stream_asset(request, asset, allow_download=download)
    except ClassroomError as exc:
        return _error(str(exc), 404)


@require_GET
def session_asset_content(request, session_id: int, revision_id: int, asset_id):
    session = get_object_or_404(LiveSession, pk=session_id)
    revision = get_object_or_404(
        ActivityRunRevision.objects.select_related("activity", "asset"),
        pk=revision_id,
        activity__session=session,
        asset__public_id=asset_id,
    )
    if not _can_read_session_asset(request, session, revision):
        return _error("The requested file is unavailable.", 404)
    download = request.GET.get("download") == "1"
    if download and not can_manage_session(request.user, session):
        return _error("Only teachers may download classroom files.", 403)
    try:
        return _stream_asset(request, revision.asset, allow_download=download)
    except ClassroomError as exc:
        return _error(str(exc), 404)
