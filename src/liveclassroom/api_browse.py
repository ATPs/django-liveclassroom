"""Read-only, role-scoped navigation summaries.

These endpoints deliberately return discovery metadata only.  They do not
create a participant, start an assessment attempt, or expose a reusable draft
to a learner.
"""

from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from .api import _error
from .models import AssessmentAttempt, AssessmentRun, Course, CourseMembership, Flow, LiveSession, TeachingCourse
from .services.permissions import can_author_course, can_teach


def _teacher_denied(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    return None


def _teaching_classes(actor):
    if actor.is_superuser:
        return Course.objects.all()
    return Course.objects.filter(
        Q(created_by=actor)
        | Q(
            memberships__user=actor,
            memberships__role__in=[CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT],
        )
    ).distinct()


def _learner_denied(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    return None


def _class_summary(course, *, mode):
    root = "liveclassroom:teacher-class-detail" if mode == "teaching" else "liveclassroom:learn-class-detail"
    return {
        "id": course.id,
        "title": course.title,
        "description": course.description,
        "teaching_course_id": course.teaching_course_id,
        "url": reverse(root, args=[course.id]),
    }


def _teaching_course_summary(course, *, mode):
    root = "liveclassroom:teacher-course-detail" if mode == "teaching" else "liveclassroom:learn-course-detail"
    return {
        "id": course.id,
        "title": course.title,
        "description": course.description,
        "url": reverse(root, args=[course.id]),
    }


def _session_summary(session):
    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "url": reverse("liveclassroom:student-session", args=[session.id]),
    }


def _run_summary(run):
    return {
        "public_id": str(run.public_id),
        "title": run.title,
        "course_id": run.course_id,
        "url": reverse("liveclassroom:assessment-attempt", args=[run.public_id]),
    }


def _class_sections(course, *, learner=False):
    session_query = (
        LiveSession.objects.filter(course=course)
        .exclude(status=LiveSession.Status.DRAFT)
        .order_by("-created_at")
    )
    run_query = (
        AssessmentRun.objects.filter(course=course, audience=AssessmentRun.Audience.CLASS)
        .order_by("-created_at")
    )
    sessions = list(session_query[:50])
    runs = list(run_query[:50])
    payload = {
        "class": _class_summary(course, mode="learning" if learner else "teaching"),
        "sessions": [_session_summary(row) for row in sessions],
        "assessments": [_run_summary(row) for row in runs],
        "counts": {"sessions": session_query.count(), "assessments": run_query.count()},
    }
    if not learner:
        flow_query = Flow.objects.filter(associated_courses=course).order_by("title", "id")
        flows = list(flow_query[:100])
        payload["lessons"] = [
            {"id": row.id, "title": row.title, "url": reverse("liveclassroom:flow-builder-detail", args=[row.id])}
            for row in flows
        ]
        payload["capabilities"] = {"manage": True}
        payload["counts"]["lessons"] = flow_query.count()
        result_route = (
            "liveclassroom:teacher-course-class-results"
            if course.teaching_course_id
            else "liveclassroom:teacher-class-results"
        )
        result_args = [course.teaching_course_id, course.id] if course.teaching_course_id else [course.id]
        payload["results_url"] = reverse(result_route, args=result_args)
    return payload


@require_GET
def teaching_index(request):
    denied = _teacher_denied(request)
    if denied is not None:
        return denied
    actor = request.user
    classes = _teaching_classes(actor)
    if actor.is_superuser:
        programs = TeachingCourse.objects.all()
    else:
        programs = TeachingCourse.objects.filter(Q(created_by=actor) | Q(cohorts__in=classes)).distinct()
    return JsonResponse(
        {
            "courses": [_teaching_course_summary(row, mode="teaching") for row in programs],
            "independent_classes": [
                _class_summary(row, mode="teaching") for row in classes.filter(teaching_course__isnull=True)
            ],
        }
    )


@require_GET
def teaching_course(request, course_id):
    denied = _teacher_denied(request)
    if denied is not None:
        return denied
    try:
        program = TeachingCourse.objects.get(pk=course_id)
    except TeachingCourse.DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    accessible = _teaching_classes(request.user).filter(teaching_course=program)
    if not (request.user.is_superuser or program.created_by_id == request.user.pk or accessible.exists()):
        return _error("Not found.", 404, code="not_found")
    classes = accessible if not request.user.is_superuser else Course.objects.filter(teaching_course=program)
    return JsonResponse(
        {
            "course": _teaching_course_summary(program, mode="teaching"),
            "classes": [_class_sections(row) for row in classes],
        }
    )


@require_GET
def teaching_class(request, class_id):
    denied = _teacher_denied(request)
    if denied is not None:
        return denied
    try:
        course = Course.objects.get(pk=class_id)
    except Course.DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    if not can_author_course(request.user, course):
        return _error("Not found.", 404, code="not_found")
    return JsonResponse(_class_sections(course))


@require_GET
def learning_index(request):
    denied = _learner_denied(request)
    if denied is not None:
        return denied
    classes = (
        Course.objects.filter(memberships__user=request.user, memberships__role=CourseMembership.Role.STUDENT)
        .select_related("teaching_course")
        .distinct()
    )
    program_ids = {row.teaching_course_id for row in classes if row.teaching_course_id}
    programs = TeachingCourse.objects.filter(pk__in=program_ids)
    attempts = AssessmentAttempt.objects.filter(user=request.user).select_related("run").order_by("-started_at")[:100]
    return JsonResponse(
        {
            "courses": [_teaching_course_summary(row, mode="learning") for row in programs],
            "independent_classes": [
                _class_summary(row, mode="learning") for row in classes.filter(teaching_course__isnull=True)
            ],
            "attempts": [
                {
                    "id": str(row.public_id),
                    "run_id": str(row.run.public_id),
                    "title": row.run.title,
                    "status": row.status,
                    "url": reverse("liveclassroom:learn-attempt-detail", args=[row.public_id]),
                }
                for row in attempts
            ],
        }
    )


@require_GET
def learning_course(request, course_id):
    denied = _learner_denied(request)
    if denied is not None:
        return denied
    try:
        program = TeachingCourse.objects.get(pk=course_id)
    except TeachingCourse.DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    classes = Course.objects.filter(
        teaching_course=program, memberships__user=request.user, memberships__role=CourseMembership.Role.STUDENT
    ).distinct()
    if not classes.exists():
        return _error("Not found.", 404, code="not_found")
    return JsonResponse(
        {
            "course": _teaching_course_summary(program, mode="learning"),
            "classes": [_class_sections(row, learner=True) for row in classes],
        }
    )


@require_GET
def learning_class(request, class_id):
    denied = _learner_denied(request)
    if denied is not None:
        return denied
    try:
        course = Course.objects.get(
            pk=class_id, memberships__user=request.user, memberships__role=CourseMembership.Role.STUDENT
        )
    except Course.DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    return JsonResponse(_class_sections(course, learner=True))
