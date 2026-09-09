"""Versioned JSON endpoints for optional TeachingCourse organization."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, JsonResponse

from .api import _authoring_replay, _body, _error, _record_authoring
from .models import Course, TeachingCourse
from .services.classroom import ClassroomError
from .services.organization import (
    OrganizationConflict,
    assign_class,
    create_teaching_course,
    delete_teaching_course,
    list_teaching_courses,
    unassign_class,
    update_teaching_course,
)
from .services.permissions import can_teach


def _summary(teaching_course: TeachingCourse) -> dict:
    return {
        "id": teaching_course.id,
        "title": teaching_course.title,
        "description": teaching_course.description,
        "owner_id": teaching_course.created_by_id,
    }


def _association(cohort: Course) -> dict:
    return {"class_id": cohort.id, "teaching_course_id": cohort.teaching_course_id}


def _access(request):
    if not request.user.is_authenticated:
        return _error("Authentication required.", 401, code="authentication_required")
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    return None


def _method(request, allowed: set[str]):
    if request.method not in allowed:
        return _error("Method not allowed.", 405, code="method_not_allowed")
    return None


def _teaching_course(teaching_course_id: int) -> TeachingCourse:
    try:
        return TeachingCourse.objects.get(pk=teaching_course_id)
    except TeachingCourse.DoesNotExist as exc:
        raise Http404 from exc


def _cohort(class_id: int) -> Course:
    try:
        return Course.objects.get(pk=class_id)
    except Course.DoesNotExist as exc:
        raise Http404 from exc


def _visible_teaching_course(*, actor, teaching_course_id: int) -> TeachingCourse:
    teaching_course = _teaching_course(teaching_course_id)
    if not list_teaching_courses(actor=actor).filter(pk=teaching_course.pk).exists():
        raise PermissionDenied("You do not have permission to view this teaching course.")
    return teaching_course


def _class_id(payload: dict) -> int:
    class_id = payload.get("class_id")
    if isinstance(class_id, bool) or not isinstance(class_id, int) or class_id <= 0:
        raise ValidationError("class_id must be a positive integer.")
    if set(payload) != {"class_id"}:
        raise ValidationError("Only class_id may be supplied.")
    return class_id


def _json_error(exc: Exception):
    if isinstance(exc, PermissionDenied):
        return _error(str(exc), 403, code="permission_denied")
    if isinstance(exc, (Http404, TeachingCourse.DoesNotExist, Course.DoesNotExist)):
        return _error("Not found.", 404, code="not_found")
    if isinstance(exc, OrganizationConflict):
        return _error(str(exc), 409, code="association_conflict")
    if isinstance(exc, (ValidationError, ClassroomError, ValueError, TypeError, KeyError)):
        message = str(exc) if isinstance(exc, ClassroomError) else "Invalid request fields."
        return _error(message, 400, code="invalid_request")
    raise exc


def _mutation(request, command_type: str, action):
    denied = _access(request)
    if denied is not None:
        return denied
    with transaction.atomic():
        replay, key = _authoring_replay(request, command_type)
        if replay is not None:
            return replay
        try:
            with transaction.atomic():
                response = action()
        except Exception as exc:
            response = _json_error(exc)
        return _record_authoring(request, key, command_type, response)


def teaching_courses(request):
    invalid_method = _method(request, {"GET", "POST"})
    if invalid_method is not None:
        return invalid_method
    denied = _access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        teaching_courses = [_summary(item) for item in list_teaching_courses(actor=request.user)]
        return JsonResponse({"teaching_courses": teaching_courses})

    def action():
        payload = _body(request)
        if set(payload) - {"title", "description"}:
            raise ValidationError("Unsupported fields.")
        teaching_course = create_teaching_course(
            actor=request.user,
            title=payload.get("title"),
            description=payload.get("description", ""),
        )
        return JsonResponse(_summary(teaching_course), status=201)

    return _mutation(request, "organization.teaching_course.create", action)


def teaching_course_detail(request, teaching_course_id: int):
    invalid_method = _method(request, {"GET", "PATCH", "DELETE"})
    if invalid_method is not None:
        return invalid_method
    denied = _access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        try:
            teaching_course = _visible_teaching_course(actor=request.user, teaching_course_id=teaching_course_id)
        except Exception as exc:
            return _json_error(exc)
        payload = _summary(teaching_course)
        payload["classes"] = [
            {"id": cohort.id, "title": cohort.title}
            for cohort in teaching_course.cohorts.order_by("title", "id")
        ]
        return JsonResponse(payload)

    def action():
        teaching_course = _teaching_course(teaching_course_id)
        if request.method == "PATCH":
            teaching_course = update_teaching_course(
                actor=request.user,
                teaching_course=teaching_course,
                changes=_body(request),
            )
            return JsonResponse(_summary(teaching_course))
        delete_teaching_course(actor=request.user, teaching_course=teaching_course)
        return JsonResponse({"deleted": True})

    return _mutation(request, f"organization.teaching_course.{request.method.casefold()}", action)


def teaching_course_classes(request, teaching_course_id: int):
    invalid_method = _method(request, {"POST"})
    if invalid_method is not None:
        return invalid_method

    def action():
        teaching_course = _teaching_course(teaching_course_id)
        cohort = _cohort(_class_id(_body(request)))
        cohort = assign_class(actor=request.user, teaching_course=teaching_course, cohort=cohort)
        return JsonResponse(_association(cohort))

    return _mutation(request, "organization.teaching_course.assign_class", action)


def teaching_course_class(request, teaching_course_id: int, class_id: int):
    invalid_method = _method(request, {"DELETE"})
    if invalid_method is not None:
        return invalid_method

    def action():
        teaching_course = _teaching_course(teaching_course_id)
        cohort = _cohort(class_id)
        cohort = unassign_class(actor=request.user, teaching_course=teaching_course, cohort=cohort)
        return JsonResponse(_association(cohort))

    return _mutation(request, "organization.teaching_course.unassign_class", action)
