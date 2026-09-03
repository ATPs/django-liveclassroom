"""Clean REST API endpoints for flow authoring, steps management, and flow imports."""

from __future__ import annotations

from typing import Any

from django.db import models
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods, require_POST

from .api import _authoring_replay, _body, _error, _record, _record_authoring, _replay
from .importers import ImportError, import_json_flow, import_markdown_flow
from .models import ActivityDefinition, Course, CourseMembership, Flow, FlowStep, LiveSession
from .services.classroom import ClassroomError, can_manage_session, create_activity_definition
from .services.flows import (
    add_flow_step,
    can_author_course,
    can_edit_flow,
    create_flow,
    duplicate_flow,
    remove_flow_step,
    reorder_flow_steps,
    save_session_as_flow,
    update_flow,
)
from .services.permissions import can_use_activity_definition


def _serialize_flow(flow: Flow) -> dict[str, Any]:
    return {
        "id": flow.id,
        "title": flow.title,
        "slug": flow.slug,
        "description": flow.description,
        "course_id": flow.course_id,
        "created_by_id": flow.created_by_id,
        "created_at": flow.created_at.isoformat() if flow.created_at else None,
        "updated_at": flow.updated_at.isoformat() if flow.updated_at else None,
    }


def _serialize_flow_summary(flow: Flow) -> dict[str, Any]:
    data = _serialize_flow(flow)
    data["steps_count"] = flow.steps.count()
    return data


def _serialize_step(step: FlowStep) -> dict[str, Any]:
    activity_data = None
    if step.activity_definition:
        activity_data = {
            "id": step.activity_definition.id,
            "title": step.activity_definition.title,
            "type_key": step.activity_definition.type_key,
            "schema_version": step.activity_definition.schema_version,
            "status": step.activity_definition.status,
            "definition": step.activity_definition.definition,
        }
    return {
        "id": step.id,
        "position": step.position,
        "kind": step.kind,
        "title": step.title,
        "content": step.content,
        "activity_definition_id": step.activity_definition_id,
        "activity_definition": activity_data,
        "created_at": step.created_at.isoformat() if step.created_at else None,
        "updated_at": step.updated_at.isoformat() if step.updated_at else None,
    }


def _serialize_flow_with_steps(flow: Flow) -> dict[str, Any]:
    payload = _serialize_flow(flow)
    payload["steps"] = [
        _serialize_step(step)
        for step in flow.steps.select_related("activity_definition").order_by("position")
    ]
    return payload


@require_http_methods(["GET", "POST"])
def flows_collection(request):
    """List accessible flows or create a new flow."""
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401)

    if request.method == "POST":
        command_type = "flow.create"
        replay, key = _authoring_replay(request, command_type)
        if replay is not None:
            return replay

        try:
            body = _body(request)
            title = body.get("title")
            if not title or not str(title).strip():
                return _record_authoring(request, key, command_type, _error("Flow title is required."))

            course_id = body.get("course_id")
            course = None
            if course_id is not None:
                course = get_object_or_404(Course, pk=course_id)
                if not can_author_course(request.user, course):
                    return _record_authoring(
                        request,
                        key,
                        command_type,
                        _error("You do not have permission to author content for this course.", 403),
                    )

            flow = create_flow(
                title=str(title).strip(),
                creator=request.user,
                course=course,
                slug=body.get("slug"),
                description=body.get("description", ""),
            )
        except ClassroomError as exc:
            return _record_authoring(request, key, command_type, _error(str(exc), 400))

        return _record_authoring(
            request,
            key,
            command_type,
            JsonResponse(_serialize_flow(flow), status=201),
        )

    # GET: List accessible flows (creator or course staff)
    if request.user.is_superuser:
        flows = Flow.objects.all()
    else:
        course_ids = CourseMembership.objects.filter(
            user=request.user,
            role__in=[CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT],
        ).values_list("course_id", flat=True)
        flows = Flow.objects.filter(
            models.Q(created_by=request.user)
            | models.Q(course__created_by=request.user)
            | models.Q(course_id__in=course_ids)
        ).distinct()

    flows = flows.select_related("course", "created_by").order_by("-updated_at")
    return JsonResponse({"flows": [_serialize_flow_summary(f) for f in flows]})


@require_http_methods(["GET", "PATCH", "PUT"])
def flow_detail(request, flow_id: int):
    """Retrieve flow details with its steps or update flow metadata."""
    flow = get_object_or_404(Flow, pk=flow_id)
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401)
    if not can_edit_flow(request.user, flow):
        return _error("You do not have permission to access this flow.", 403)

    if request.method == "GET":
        return JsonResponse(_serialize_flow_with_steps(flow))

    # PATCH / PUT
    command_type = f"flow.update.{flow_id}"
    replay, key = _authoring_replay(request, command_type)
    if replay is not None:
        return replay

    try:
        body = _body(request)
        flow = update_flow(
            flow=flow,
            actor=request.user,
            title=body.get("title"),
            description=body.get("description"),
        )
    except ClassroomError as exc:
        return _record_authoring(request, key, command_type, _error(str(exc), 400))

    return _record_authoring(
        request,
        key,
        command_type,
        JsonResponse(_serialize_flow(flow)),
    )


@require_POST
def duplicate_flow_api(request, flow_id: int):
    """Duplicate an existing flow and its steps."""
    flow = get_object_or_404(Flow, pk=flow_id)
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401)
    if not can_edit_flow(request.user, flow):
        return _error("You do not have permission to duplicate this flow.", 403)

    command_type = f"flow.duplicate.{flow_id}"
    replay, key = _authoring_replay(request, command_type)
    if replay is not None:
        return replay

    try:
        body = _body(request)
        new_flow = duplicate_flow(
            flow=flow,
            creator=request.user,
            title=body.get("title"),
            slug=body.get("slug"),
        )
    except ClassroomError as exc:
        return _record_authoring(request, key, command_type, _error(str(exc), 400))

    return _record_authoring(
        request,
        key,
        command_type,
        JsonResponse(_serialize_flow_with_steps(new_flow), status=201),
    )


@require_POST
def add_step_api(request, flow_id: int):
    """Add a new step to a flow with an existing or inline activity definition."""
    flow = get_object_or_404(Flow, pk=flow_id)
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401)
    if not can_edit_flow(request.user, flow):
        return _error("You do not have permission to edit this flow.", 403)

    command_type = f"flow.add_step.{flow_id}"
    replay, key = _authoring_replay(request, command_type)
    if replay is not None:
        return replay

    try:
        body = _body(request)
        activity_def = None
        if body.get("activity_definition_id"):
            activity_def = get_object_or_404(ActivityDefinition, pk=body["activity_definition_id"])
            if not can_use_activity_definition(request.user, activity_def):
                return _record_authoring(
                    request,
                    key,
                    command_type,
                    _error("You do not have permission to use this activity.", 403),
                )
        elif body.get("activity_definition") and isinstance(body["activity_definition"], dict):
            inline = body["activity_definition"]
            type_key = inline.get("type_key") or inline.get("type")
            if not type_key:
                return _record_authoring(
                    request,
                    key,
                    command_type,
                    _error("type_key is required for inline activity definition."),
                )
            def_title = inline.get("title") or body.get("title") or "Activity"
            def_content = inline.get("definition") if "definition" in inline else inline.get("content", {})
            activity_def = create_activity_definition(
                owner=request.user,
                title=def_title,
                type_key=type_key,
                definition=def_content,
                course=flow.course,
            )
        elif body.get("type_key") or (body.get("kind") and body.get("kind") not in ("markdown", "activity")):
            type_key = body.get("type_key") or body.get("kind")
            def_title = body.get("title") or "Activity"
            def_content = body.get("definition") if "definition" in body else body.get("content", {})
            activity_def = create_activity_definition(
                owner=request.user,
                title=def_title,
                type_key=type_key,
                definition=def_content,
                course=flow.course,
            )

        step = add_flow_step(
            flow=flow,
            actor=request.user,
            activity_definition=activity_def,
            kind=body.get("kind", "activity"),
            position=body.get("position"),
            title=body.get("title", ""),
            content=body.get("content"),
        )
    except ClassroomError as exc:
        return _record_authoring(request, key, command_type, _error(str(exc), 400))
    except Http404:
        return _record_authoring(request, key, command_type, _error("The referenced activity was not found.", 404))

    return _record_authoring(
        request,
        key,
        command_type,
        JsonResponse(_serialize_step(step), status=201),
    )


@require_http_methods(["PUT", "POST"])
def reorder_steps_api(request, flow_id: int):
    """Reorder steps in a flow according to an array of step IDs."""
    flow = get_object_or_404(Flow, pk=flow_id)
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401)
    if not can_edit_flow(request.user, flow):
        return _error("You do not have permission to edit this flow.", 403)

    command_type = f"flow.reorder_steps.{flow_id}"
    replay, key = _authoring_replay(request, command_type)
    if replay is not None:
        return replay

    try:
        body = _body(request)
        step_ids = body.get("step_ids")
        if not isinstance(step_ids, list):
            return _record_authoring(request, key, command_type, _error("step_ids must be a list of integers."))
        steps = reorder_flow_steps(flow=flow, actor=request.user, step_ids=step_ids)
    except ClassroomError as exc:
        return _record_authoring(request, key, command_type, _error(str(exc), 400))

    return _record_authoring(
        request,
        key,
        command_type,
        JsonResponse({"steps": [_serialize_step(s) for s in steps]}),
    )


@require_http_methods(["DELETE", "POST"])
def delete_step_api(request, flow_id: int, step_id: int):
    """Remove a step from a flow."""
    flow = get_object_or_404(Flow, pk=flow_id)
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401)
    if not can_edit_flow(request.user, flow):
        return _error("You do not have permission to edit this flow.", 403)

    command_type = f"flow.remove_step.{flow_id}.{step_id}"
    replay, key = _authoring_replay(request, command_type)
    if replay is not None:
        return replay

    try:
        remove_flow_step(flow=flow, actor=request.user, step_id=step_id)
    except ClassroomError as exc:
        return _record_authoring(request, key, command_type, _error(str(exc), 400))

    return _record_authoring(
        request,
        key,
        command_type,
        JsonResponse({"deleted": True, "step_id": step_id}),
    )


@require_POST
def import_flow_api(request):
    """Import a flow from a JSON or Markdown/YAML source."""
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401)

    command_type = "flow.import"
    replay, key = _authoring_replay(request, command_type)
    if replay is not None:
        return replay

    try:
        body = _body(request)
        source = body.get("source")
        if source is None:
            return _record_authoring(request, key, command_type, _error("source is required."))
        fmt = str(body.get("format") or "").strip().lower()
        course_id = body.get("course_id")
        fallback_slug = body.get("slug")
        course = None
        if course_id is not None:
            course = get_object_or_404(Course, pk=course_id)
            if not can_author_course(request.user, course):
                return _record_authoring(
                    request,
                    key,
                    command_type,
                    _error("You do not have permission to author content for this course.", 403),
                )

        # Auto-detect format if not provided
        if not fmt:
            if isinstance(source, dict) or (isinstance(source, str) and source.strip().startswith("{")):
                fmt = "json"
            else:
                fmt = "markdown"

        if fmt == "json":
            flow = import_json_flow(
                source=source,
                course=course,
                creator=request.user,
                fallback_slug=fallback_slug,
            )
        elif fmt in ("markdown", "md", "yaml"):
            if not isinstance(source, str):
                return _record_authoring(
                    request,
                    key,
                    command_type,
                    _error("Markdown/YAML source must be a string."),
                )
            flow = import_markdown_flow(
                course=course,
                source=source,
                creator=request.user,
                fallback_slug=fallback_slug,
            )
        else:
            return _record_authoring(
                request,
                key,
                command_type,
                _error(f"Unsupported import format: {fmt!r}."),
            )
    except (ImportError, ClassroomError, ValueError) as exc:
        return _record_authoring(request, key, command_type, _error(str(exc), 400))

    return _record_authoring(
        request,
        key,
        command_type,
        JsonResponse(_serialize_flow_with_steps(flow), status=201),
    )


@require_POST
def save_session_flow_api(request, session_id: int):
    """Save an active or ended session's activities as a reusable flow."""
    session = get_object_or_404(LiveSession, pk=session_id)
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401)
    if not can_manage_session(request.user, session):
        return _error("You do not have permission to control this session.", 403)

    command_type = f"session.save_flow.{session_id}"
    replay, key = _replay(request, session, command_type)
    if replay is not None:
        return replay

    try:
        body = _body(request)
        title = body.get("title")
        if not title or not str(title).strip():
            return _record(session, key, command_type, request, _error("Flow title is required."))
        flow = save_session_as_flow(
            session=session,
            creator=request.user,
            title=str(title).strip(),
            slug=body.get("slug"),
        )
    except ClassroomError as exc:
        return _record(session, key, command_type, request, _error(str(exc), 400))

    return _record(
        session,
        key,
        command_type,
        request,
        JsonResponse(_serialize_flow_with_steps(flow), status=201),
    )
