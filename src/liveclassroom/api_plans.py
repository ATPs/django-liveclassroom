"""Versioned teacher workspace and classroom-plan endpoints."""

from functools import wraps

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .api import _authoring_replay, _body, _error, _record_authoring
from .models import ActivityDefinition, Course, CourseMembership, Flow, FlowShare, LiveSession, SessionPlanStep
from .services.classroom import ClassroomError, can_view_session, session_capabilities
from .services.permissions import can_author_course, can_edit_flow, can_teach, can_use_flow
from .services.plan_changes import apply_changes, compare_changes
from .services.plans import (
    add_plan_step,
    create_session,
    edit_plan_step,
    launch_plan_step,
    reorder_plan,
)
from .services.presentation import presentation_title


def command(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _error("Authentication required.", 401)
        if not can_teach(request.user):
            return _error("Teacher access is required.", 403)
        if request.method == "GET":
            try:
                return view(request, *args, **kwargs)
            except ClassroomError as exc:
                return _error(str(exc), 403)
        with transaction.atomic():
            kind = f"workspace.{view.__name__}.{request.method}"
            replay, key = _authoring_replay(request, kind)
            if replay is not None:
                return replay
            try:
                with transaction.atomic():
                    response = view(request, *args, **kwargs)
            except (ClassroomError, ValueError, TypeError, KeyError) as exc:
                message = str(exc) if isinstance(exc, ClassroomError) else "Invalid request fields."
                code = "content_conflict" if "compare again" in message else None
                response = _error(message, 409 if code else 400, code=code)
            return _record_authoring(request, key, kind, response)

    return wrapped


def _course(course, user):
    return {
        "id": course.id,
        "title": course.title,
        "description": course.description,
        "defaults": course.session_defaults,
        "owner_id": course.created_by_id,
        "can_manage": user.is_superuser or course.created_by_id == user.pk,
    }


def accessible_courses(user):
    if user.is_superuser:
        return Course.objects.all()
    return Course.objects.filter(
        Q(created_by=user) | Q(memberships__user=user, memberships__role__in=["teacher", "assistant"])
    ).distinct()


def _session(session, user):
    from .services.demos import is_public_demo_session

    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "archived": session.archived_at is not None,
        "course_id": session.course_id,
        "flow_id": session.flow_id,
        "source_session_id": session.source_session_id,
        "plan_version": session.plan_version,
        "capabilities": session_capabilities(user, session),
        "console_url": reverse("liveclassroom:teacher-console", args=[session.id]),
        "student_view_url": reverse("liveclassroom:student-view", args=[session.id]),
        "join_code": session.join_code,
        "demo": is_public_demo_session(session),
        "can_delete": (
            "manage_session" in session_capabilities(user, session)
            and not is_public_demo_session(session)
            and session.status not in {LiveSession.Status.LIVE, LiveSession.Status.PAUSED}
        ),
    }


@require_GET
@command
def workspace(request):
    query = (
        LiveSession.objects.all()
        if request.user.is_superuser
        else LiveSession.objects.filter(
            Q(teacher=request.user)
            | Q(staff__user=request.user)
            | Q(course__created_by=request.user)
            | Q(course__memberships__user=request.user, course__memberships__role__in=["teacher", "assistant"])
        ).distinct()
    )
    from .services.demos import public_demo_sessions

    if not request.user.is_superuser:
        query = query | public_demo_sessions()
    return JsonResponse(
        {
            "courses": [_course(c, request.user) for c in accessible_courses(request.user)],
            "sessions": [_session(s, request.user) for s in query.select_related("course")[:200]],
        }
    )


@require_http_methods(["GET", "POST"])
@command
def courses(request):
    if request.method == "GET":
        return JsonResponse({"courses": [_course(c, request.user) for c in accessible_courses(request.user)]})
    body = _body(request)
    title = body.get("title", "")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ClassroomError("A class title of at most 200 characters is required.")
    import uuid

    course = Course.objects.create(
        title=title.strip(),
        created_by=request.user,
        slug=f"{slugify(title)[:35] or 'class'}-{uuid.uuid4().hex[:12]}",
        description=body.get("description", ""),
    )
    return JsonResponse(_course(course, request.user), status=201)


@require_http_methods(["GET", "PATCH", "POST"])
@command
def course_detail(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not can_author_course(request.user, course):
        raise ClassroomError("You do not have permission to view this class.")
    if request.method != "GET":
        if not (course.created_by_id == request.user.pk or request.user.is_superuser):
            raise ClassroomError("Only the class owner can change its settings.")
        body = _body(request)
        title = body.get("title", course.title)
        description = body.get("description", course.description)
        defaults = body.get("defaults", course.session_defaults)
        if not isinstance(title, str) or not title.strip() or len(title) > 200 or not isinstance(description, str):
            raise ClassroomError("A valid title and description are required.")
        if not isinstance(defaults, dict) or set(defaults) - {"access_mode", "admission_mode", "chat_enabled"}:
            raise ClassroomError("Unsupported classroom defaults.")
        from .services.plans import _settings

        _settings(request.user, course, defaults)
        course.title, course.description, course.session_defaults = title.strip(), description, defaults
        course.save(update_fields=["title", "description", "session_defaults", "updated_at"])
    payload = _course(course, request.user)
    payload["members"] = [
        {"id": m.id, "username": m.user.get_username(), "role": m.role}
        for m in course.memberships.select_related("user")
    ]
    payload["lesson_ids"] = list(course.library_flows.values_list("id", flat=True))
    return JsonResponse(payload)


@require_POST
@command
def course_members(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not (request.user.is_superuser or course.created_by_id == request.user.pk):
        raise ClassroomError("Only the class owner can manage its members.")
    body = _body(request)
    user = get_object_or_404(get_user_model(), **{get_user_model().USERNAME_FIELD: body.get("username", "")})
    if body.get("remove") is True:
        course.memberships.filter(user=user).delete()
    else:
        role = body.get("role", "student")
        if role not in CourseMembership.Role.values:
            raise ClassroomError("Unsupported class role.")
        CourseMembership.objects.update_or_create(course=course, user=user, defaults={"role": role})
    return JsonResponse({"saved": True})


@require_POST
@command
def associate_lesson(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    flow = get_object_or_404(Flow, pk=_body(request).get("flow_id"))
    if not can_author_course(request.user, course) or not can_use_flow(request.user, flow):
        raise ClassroomError("You do not have permission to associate this lesson.")
    if _body(request).get("remove") is True:
        flow.associated_courses.remove(course)
    else:
        flow.associated_courses.add(course)
    return JsonResponse({"saved": True})


@require_http_methods(["GET", "POST"])
@command
def shares(request, flow_id):
    flow = get_object_or_404(Flow, pk=flow_id)
    if not (flow.created_by_id == request.user.pk or request.user.is_superuser):
        raise ClassroomError("Only the lesson owner can manage sharing.")
    if request.method == "POST":
        body = _body(request)
        user = get_object_or_404(get_user_model(), **{get_user_model().USERNAME_FIELD: body.get("username", "")})
        if body.get("remove") is True:
            flow.shares.filter(user=user).delete()
        else:
            FlowShare.objects.get_or_create(flow=flow, user=user)
    return JsonResponse(
        {
            "shares": [
                {"user_id": share.user_id, "username": share.user.get_username()}
                for share in flow.shares.select_related("user")
            ]
        }
    )


@require_POST
@command
def sessions_create(request):
    body = _body(request)
    course = get_object_or_404(Course, pk=body["course_id"]) if body.get("course_id") else None
    flow = get_object_or_404(Flow, pk=body["flow_id"]) if body.get("flow_id") else None
    source = get_object_or_404(LiveSession, pk=body["source_session_id"]) if body.get("source_session_id") else None
    session = create_session(
        owner=request.user,
        title=body.get("title"),
        course=course,
        flow=flow,
        source=source,
        **{k: body[k] for k in ("access_mode", "admission_mode", "chat_enabled") if k in body},
    )
    return JsonResponse(_session(session, request.user), status=201)


def serialize_step(step):
    latest = step.runs.order_by("-sequence").first()
    snapshot = dict(step.snapshot)
    if isinstance(snapshot.get("title"), str):
        snapshot["title"] = presentation_title(snapshot["title"])
    return {
        "id": step.pk,
        "key": str(step.key),
        "position": step.position,
        "snapshot": snapshot,
        "title": presentation_title(step.snapshot.get("title", "Activity")),
        "activity_id": latest.pk if latest else None,
        "activity_state": latest.state if latest else None,
        "launched": latest is not None,
    }


@require_http_methods(["GET", "POST"])
@command
def session_plan(request, session_id):
    session = get_object_or_404(LiveSession, pk=session_id)
    if not can_view_session(request.user, session):
        raise ClassroomError("You do not have permission to view this classroom.")
    if request.method == "POST":
        body = _body(request)
        definition = (
            get_object_or_404(ActivityDefinition, pk=body["activity_definition_id"])
            if body.get("activity_definition_id")
            else None
        )
        if "plan_version" not in body:
            raise ClassroomError("plan_version is required.")
        add_plan_step(
            session=session,
            actor=request.user,
            definition=definition,
            snapshot=body.get("snapshot"),
            expected_version=body["plan_version"],
        )
        session.refresh_from_db()
    return JsonResponse(
        {
            "session": _session(session, request.user),
            "can_update_lesson": bool(session.flow_id and can_edit_flow(request.user, session.flow)),
            "can_pull_lesson": bool(session.flow_id and can_use_flow(request.user, session.flow)),
            "steps": [serialize_step(s) for s in session.plan_steps.filter(removed=False)],
        }
    )


@require_http_methods(["PATCH", "DELETE", "POST"])
@command
def plan_step(request, session_id, step_id):
    session = get_object_or_404(LiveSession, pk=session_id)
    step = get_object_or_404(SessionPlanStep, pk=step_id, session=session, removed=False)
    body = _body(request)
    if "plan_version" not in body:
        raise ClassroomError("plan_version is required.")
    step = edit_plan_step(
        session=session,
        step=step,
        actor=request.user,
        snapshot=body.get("snapshot"),
        remove=request.method == "DELETE" or body.get("remove") is True,
        expected_version=body["plan_version"],
    )
    return JsonResponse(serialize_step(step))


@require_POST
@command
def plan_reorder(request, session_id):
    session = get_object_or_404(LiveSession, pk=session_id)
    body = _body(request)
    if "plan_version" not in body:
        raise ClassroomError("plan_version is required.")
    reorder_plan(session=session, actor=request.user, keys=body.get("keys"), expected_version=body["plan_version"])
    return JsonResponse({"saved": True})


@require_POST
@command
def plan_launch(request, session_id, step_id):
    session = get_object_or_404(LiveSession, pk=session_id)
    step = get_object_or_404(SessionPlanStep, pk=step_id, session=session, removed=False)
    body = _body(request)
    if not isinstance(body.get("restart", False), bool):
        raise ClassroomError("restart must be a boolean.")
    channel = body.get("channel", "display")
    activity = launch_plan_step(
        session=session,
        step=step,
        actor=request.user,
        channel=channel,
        restart=body.get("restart", False),
    )
    return JsonResponse({"activity_id": activity.pk}, status=201)


@require_http_methods(["GET", "POST"])
@command
def plan_comparison(request, session_id):
    session = get_object_or_404(LiveSession, pk=session_id)
    if request.method == "GET":
        return JsonResponse(
            compare_changes(session=session, actor=request.user, direction=request.GET.get("direction", "to_lesson"))
        )
    body = _body(request)
    return JsonResponse(
        apply_changes(
            session=session,
            actor=request.user,
            direction=body.get("direction"),
            token=body.get("token"),
            keys=body.get("keys"),
            confirmed_conflicts=body.get("confirmed_conflicts"),
        )
    )


@require_POST
@command
def lesson_step_edit(request, flow_id, step_id):
    from .api_flows import _serialize_flow_with_steps
    from .models import FlowStep
    from .services.plans import copy_definition, lesson_token

    flow = get_object_or_404(Flow.objects.select_for_update(), pk=flow_id)
    if not can_edit_flow(request.user, flow):
        raise ClassroomError("You do not have permission to edit this lesson.")
    body = _body(request)
    if body.get("token") != lesson_token(flow):
        raise ClassroomError("The content changed; refresh and compare again.")
    step = get_object_or_404(FlowStep, flow=flow, pk=step_id)
    snapshot = body.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ClassroomError("An activity snapshot must be an object.")
    definition = copy_definition(
        actor=request.user,
        snapshot=snapshot,
        asset=step.activity_definition.asset if snapshot.get("type_key") == "liveclassroom.file" else None,
        course=flow.course,
    )
    step.activity_definition = definition
    step.save(update_fields=["activity_definition", "updated_at"])
    flow.save(update_fields=["updated_at"])
    return JsonResponse(_serialize_flow_with_steps(flow))
