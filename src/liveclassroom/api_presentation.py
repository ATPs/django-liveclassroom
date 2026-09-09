"""Session presentation source discovery and slide-cue endpoints."""

from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods

from .api import _body, _error, _record, _replay
from .models import LiveSession
from .providers import ProviderError, content_providers
from .services.classroom import ClassroomError, can_manage_session
from .services.presentation_cues import (
    create_presentation_cue,
    delete_presentation_cue,
    launch_presentation_cue,
    list_presentation_cues,
    prepare_provider_source,
    provider_search,
    replace_presentation_cue,
)


def _session(request, session_id: int) -> LiveSession | None:
    session = get_object_or_404(LiveSession, pk=session_id)
    if not can_manage_session(request.user, session):
        return None
    return session


def _permission_error() -> JsonResponse:
    return _error("You do not have permission to manage presentation sources.", 403, code="permission_denied")


@require_GET
def providers(request, session_id: int):
    session = _session(request, session_id)
    if session is None:
        return _permission_error()
    try:
        registry = content_providers()
        items = []
        for key in registry.keys():
            provider = registry.get(key)
            search_supported = getattr(provider, "search_supported", None)
            if not isinstance(search_supported, bool):
                search_supported = callable(getattr(provider, "search", None))
            items.append(
                {
                    "key": key,
                    "search_supported": search_supported,
                    "navigation_supported": bool(getattr(provider, "navigation_supported", False)),
                }
            )
    except (ProviderError, TypeError, ValueError) as exc:
        return _error(str(exc), 503, code="provider_unavailable")
    return JsonResponse({"providers": items})


@require_GET
def provider_search_api(request, session_id: int, provider: str):
    session = _session(request, session_id)
    if session is None:
        return _permission_error()
    query = request.GET.get("q", "")
    try:
        results = provider_search(actor=request.user, provider_key=provider, query=query, request=request)
    except ClassroomError as exc:
        return _error(str(exc), 503, code="provider_unavailable")
    return JsonResponse({"provider": provider, "results": results})


@require_http_methods(["POST"])
def provider_resolve(request, session_id: int):
    session = _session(request, session_id)
    if session is None:
        return _permission_error()
    try:
        body = _body(request)
        source = prepare_provider_source(actor=request.user, source=body, request=request)
    except ClassroomError as exc:
        return _error(str(exc), 400, code="provider_unavailable")
    return JsonResponse({"source": source})


@require_http_methods(["GET", "POST"])
def cues(request, session_id: int):
    session = _session(request, session_id)
    if session is None:
        return _permission_error()
    if request.method == "GET":
        try:
            return JsonResponse({"cues": list_presentation_cues(session=session, actor=request.user, request=request)})
        except ClassroomError as exc:
            return _error(str(exc), 403)
    replay, key = _replay(request, session, "presentation.cue.create")
    if replay is not None:
        return replay
    try:
        cue = create_presentation_cue(session=session, actor=request.user, data=_body(request), request=request)
        response = JsonResponse(cue, status=201)
    except ClassroomError as exc:
        response = _error(str(exc), 400)
    return _record(session, key, "presentation.cue.create", request, response)


@require_http_methods(["PATCH", "DELETE"])
def cue_detail(request, session_id: int, cue_id):
    session = _session(request, session_id)
    if session is None:
        return _permission_error()
    command_type = "presentation.cue.update" if request.method == "PATCH" else "presentation.cue.delete"
    replay, key = _replay(request, session, command_type)
    if replay is not None:
        return replay
    try:
        if request.method == "PATCH":
            response = JsonResponse(
                replace_presentation_cue(
                    session=session,
                    actor=request.user,
                    cue_id=str(cue_id),
                    data=_body(request),
                    request=request,
                )
            )
        else:
            delete_presentation_cue(session=session, actor=request.user, cue_id=str(cue_id))
            response = JsonResponse({"deleted": True})
    except ClassroomError as exc:
        response = _error(str(exc), 400)
    return _record(session, key, command_type, request, response)


@require_http_methods(["POST"])
def cue_launch(request, session_id: int, cue_id):
    session = _session(request, session_id)
    if session is None:
        return _permission_error()
    replay, key = _replay(request, session, "presentation.cue.launch")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        channel = body.get("channel", "display")
        if not isinstance(channel, str):
            raise ClassroomError("channel must be text.")
        result = launch_presentation_cue(
            session=session,
            actor=request.user,
            cue_id=str(cue_id),
            channel=channel,
            request=request,
        )
        response = JsonResponse(result)
    except ClassroomError as exc:
        response = _error(str(exc), 400)
    return _record(session, key, "presentation.cue.launch", request, response)
