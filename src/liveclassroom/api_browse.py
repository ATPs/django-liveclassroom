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
from .integrations.host import host_can_view_grade_summary
from .models import (
    AssessmentAttempt,
    AssessmentDefinition,
    AssessmentRun,
    Course,
    CourseMembership,
    Deck,
    Flow,
    LiveSession,
    TeachingCourse,
)
from .services.classroom import can_manage_session, can_view_session
from .services.permissions import can_author_course, can_teach, can_use_flow


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


def _session_link(session, *, teaching: bool):
    """Return a read-only session link without changing session state."""
    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "url": reverse(
            "liveclassroom:teacher-console" if teaching else "liveclassroom:student-session",
            args=[session.id],
        ),
    }


def _material_link(item, route_name):
    return {"id": item.id, "title": item.title, "url": reverse(route_name, args=[item.id])}


_PAGE_REFERENCES = {
    "page:home": ("Home", "liveclassroom:home", False),
    "page:help": ("Help", "liveclassroom:help", False),
    "page:join": ("Join a session", "liveclassroom:join", False),
    "page:learning": ("My courses", "liveclassroom:learning-home", True),
    "page:history": ("My attempts and results", "liveclassroom:assessment-history", True),
    "page:teacher": ("Teacher console", "liveclassroom:teacher-dashboard", True),
    "page:teaching-courses": ("Teaching courses", "liveclassroom:teacher-courses", True),
    "page:teaching-classes": ("Classes", "liveclassroom:teacher-classes", True),
    "page:teacher-sessions": ("Sessions", "liveclassroom:teacher-sessions", True),
    "page:teacher-results": ("Results and grading", "liveclassroom:teacher-results", True),
    "page:lessons": ("Lessons", "liveclassroom:teacher-library-lessons", True),
    "page:decks": ("Slide decks", "liveclassroom:teacher-library-decks", True),
    "page:assessments": ("Assessments", "liveclassroom:teacher-library-assessments", True),
    "page:questions": ("Question bank", "liveclassroom:teacher-library-questions", True),
    "page:shared": ("Shared with me", "liveclassroom:teacher-library-shared", True),
    "page:student-preview": ("Student preview", "liveclassroom:student-preview", True),
}


def _resolved_reference(actor, reference):
    """Resolve one stored navigation reference after reapplying route policy."""
    if not isinstance(reference, str) or len(reference) > 120:
        return None
    page = _PAGE_REFERENCES.get(reference)
    if page is not None:
        label, route_name, teacher_only = page
        if teacher_only and not can_teach(actor):
            return None
        return {"ref": reference, "label": label, "url": reverse(route_name), "kind": "page"}

    try:
        kind, raw_id, mode = reference.split(":", 2)
    except ValueError:
        kind = raw_id = mode = ""
    if kind == "class" and raw_id.isdigit() and mode in {"teaching", "learning"}:
        course = Course.objects.filter(pk=int(raw_id)).first()
        if course is None:
            return None
        if mode == "teaching":
            if not can_teach(actor) or not can_author_course(actor, course):
                return None
            route_name = "liveclassroom:teacher-class-detail"
        else:
            if not CourseMembership.objects.filter(
                course=course, user=actor, role=CourseMembership.Role.STUDENT
            ).exists():
                return None
            route_name = "liveclassroom:learn-class-detail"
        return {"ref": reference, "label": course.title, "url": reverse(route_name, args=[course.id]), "kind": "class"}
    if kind == "course" and raw_id.isdigit() and mode in {"teaching", "learning"}:
        course = TeachingCourse.objects.filter(pk=int(raw_id)).first()
        if course is None:
            return None
        if mode == "teaching":
            accessible = _teaching_classes(actor).filter(teaching_course=course).exists()
            if not can_teach(actor) or not (actor.is_superuser or course.created_by_id == actor.pk or accessible):
                return None
            route_name = "liveclassroom:teacher-course-detail"
        else:
            if not Course.objects.filter(
                teaching_course=course, memberships__user=actor, memberships__role=CourseMembership.Role.STUDENT
            ).exists():
                return None
            route_name = "liveclassroom:learn-course-detail"
        return {"ref": reference, "label": course.title, "url": reverse(route_name, args=[course.id]), "kind": "course"}
    if kind == "session" and raw_id.isdigit() and mode in {"teaching", "learning", "preview"}:
        session = LiveSession.objects.filter(pk=int(raw_id)).first()
        if session is None:
            return None
        if mode == "teaching":
            if not can_teach(actor) or not can_view_session(actor, session):
                return None
            route_name = "liveclassroom:teacher-console"
        elif mode == "preview":
            if not can_teach(actor) or not can_manage_session(actor, session):
                return None
            route_name = "liveclassroom:student-view"
        else:
            if not can_view_session(actor, session):
                return None
            route_name = "liveclassroom:student-session"
        return {
            "ref": reference,
            "label": session.title,
            "url": reverse(route_name, args=[session.id]),
            "kind": "session",
        }
    if reference.startswith("flow:") and reference[5:].isdigit():
        flow = Flow.objects.filter(pk=int(reference[5:])).first()
        if flow is None or not can_teach(actor) or not can_use_flow(actor, flow):
            return None
        return {
            "ref": reference,
            "label": flow.title,
            "url": reverse("liveclassroom:flow-builder-detail", args=[flow.id]),
            "kind": "flow",
        }
    if reference.startswith("deck:") and reference[5:].isdigit():
        deck = Deck.objects.filter(pk=int(reference[5:]), owner=actor).first()
        if deck is None or not can_teach(actor):
            return None
        return {
            "ref": reference,
            "label": deck.title,
            "url": reverse("liveclassroom:deck-workspace-detail", args=[deck.id]),
            "kind": "deck",
        }
    if reference.startswith("assessment:") and reference[11:].isdigit():
        assessment = AssessmentDefinition.objects.filter(pk=int(reference[11:]), owner=actor).first()
        if assessment is None or not can_teach(actor):
            return None
        return {
            "ref": reference,
            "label": assessment.title,
            "url": reverse("liveclassroom:assessment-workspace-detail", args=[assessment.id]),
            "kind": "assessment",
        }
    if reference.startswith("attempt:"):
        attempt = AssessmentAttempt.objects.filter(public_id=reference[8:], user=actor).select_related("run").first()
        if attempt is None:
            return None
        return {
            "ref": reference,
            "label": attempt.run.title,
            "url": reverse("liveclassroom:learn-attempt-detail", args=[attempt.public_id]),
            "kind": "attempt",
        }
    return None


@require_GET
def home(request):
    """Return bounded, permission-scoped resume work for the application home."""
    if not getattr(request.user, "is_authenticated", False):
        return JsonResponse({"mode": "guest", "sections": []})

    mode = request.GET.get("mode", "")
    teacher = can_teach(request.user)
    if mode not in {"", "teaching", "learning"}:
        return _error("mode must be teaching or learning.", 400, code="invalid_request")
    if mode == "teaching" and not teacher:
        return _error("Teacher access is required.", 403, code="permission_denied")
    selected_mode = mode or ("teaching" if teacher else "learning")
    actor = request.user

    if selected_mode == "teaching":
        classes = _teaching_classes(actor)
        sessions = (
            LiveSession.objects.filter(Q(teacher=actor) | Q(course__in=classes))
            .exclude(status=LiveSession.Status.ENDED)
            .select_related("course")
            .distinct()
            .order_by("-updated_at", "-id")[:6]
        )
        recent = []
        for item in Flow.objects.filter(created_by=actor).order_by("-updated_at", "-id")[:2]:
            recent.append(_material_link(item, "liveclassroom:flow-builder-detail"))
        for item in Deck.objects.filter(owner=actor).order_by("-updated_at", "-id")[:2]:
            recent.append(_material_link(item, "liveclassroom:deck-workspace-detail"))
        for item in AssessmentDefinition.objects.filter(owner=actor).order_by("-updated_at", "-id")[:2]:
            recent.append(_material_link(item, "liveclassroom:assessment-workspace-detail"))
        return JsonResponse(
            {
                "mode": "teaching",
                "sections": [
                    {
                        "key": "sessions",
                        "title": "Current sessions",
                        "items": [_session_link(row, teaching=True) for row in sessions],
                    },
                    {"key": "recent", "title": "Recent teaching work", "items": recent[:6]},
                    {
                        "key": "classes",
                        "title": "Courses and classes",
                        "items": [_class_summary(row, mode="teaching") for row in classes.order_by("title", "id")[:6]],
                    },
                ],
                "quick_actions": [
                    {"key": "lesson", "title": "New lesson", "url": reverse("liveclassroom:flow-builder")},
                    {"key": "deck", "title": "New slide deck", "url": reverse("liveclassroom:deck-workspace")},
                    {
                        "key": "assessment",
                        "title": "New assessment",
                        "url": reverse("liveclassroom:assessment-workspace"),
                    },
                    {"key": "session", "title": "Instant classroom", "url": reverse("liveclassroom:teacher-dashboard")},
                ],
            }
        )

    learner_classes = Course.objects.filter(
        memberships__user=actor, memberships__role=CourseMembership.Role.STUDENT
    ).distinct()
    attempts = (
        AssessmentAttempt.objects.filter(user=actor, status=AssessmentAttempt.Status.IN_PROGRESS)
        .select_related("run")[:6]
    )
    sessions = (
        LiveSession.objects.filter(
            course__in=learner_classes,
            status__in=[LiveSession.Status.LIVE, LiveSession.Status.PAUSED],
        )
        .select_related("course")
        .distinct()
        .order_by("-updated_at", "-id")[:6]
    )
    available_runs = (
        AssessmentRun.objects.filter(course__in=learner_classes, audience=AssessmentRun.Audience.CLASS)
        .order_by("-created_at", "-id")[:6]
    )
    return JsonResponse(
        {
            "mode": "learning",
            "sections": [
                {
                    "key": "resume",
                    "title": "Continue learning",
                    "items": [
                        {
                            "id": str(row.public_id),
                            "title": row.run.title,
                            "status": row.status,
                            "url": reverse("liveclassroom:learn-attempt-detail", args=[row.public_id]),
                        }
                        for row in attempts
                    ],
                },
                {
                    "key": "sessions",
                    "title": "Current sessions",
                    "items": [_session_link(row, teaching=False) for row in sessions],
                },
                {
                    "key": "assessments",
                    "title": "Available assessments",
                    "items": [_run_summary(row) for row in available_runs],
                },
                {
                    "key": "classes",
                    "title": "My courses",
                    "items": [
                        _class_summary(row, mode="learning")
                        for row in learner_classes.order_by("title", "id")[:6]
                    ],
                },
            ],
            "quick_actions": [],
        }
    )


@require_GET
def navigation(request):
    """Return permission-aware navigation references without persisting preferences."""
    if not getattr(request.user, "is_authenticated", False):
        return JsonResponse({"modes": ["guest"], "contexts": [], "resolved": []})
    actor = request.user
    teacher = can_teach(actor)
    contexts = []
    if teacher:
        for course in _teaching_classes(actor).order_by("title", "id")[:25]:
            contexts.append(
                {
                    "kind": "class",
                    "id": course.id,
                    "title": course.title,
                    "teaching_url": reverse("liveclassroom:teacher-class-detail", args=[course.id]),
                    **(
                        {"results_url": reverse("liveclassroom:teacher-class-results", args=[course.id])}
                        if host_can_view_grade_summary(
                            actor=actor,
                            course_id=course.id,
                            package_allowed=can_author_course(actor, course),
                        )
                        else {}
                    ),
                }
            )
    for course in Course.objects.filter(
        memberships__user=actor, memberships__role=CourseMembership.Role.STUDENT
    ).order_by("title", "id")[:25]:
        existing = next((row for row in contexts if row["id"] == course.id), None)
        if existing is not None:
            existing["learning_url"] = reverse("liveclassroom:learn-class-detail", args=[course.id])
        else:
            contexts.append(
                {
                    "kind": "class",
                    "id": course.id,
                    "title": course.title,
                    "learning_url": reverse("liveclassroom:learn-class-detail", args=[course.id]),
                }
            )
    refs = request.GET.getlist("ref")
    if len(refs) > 22:
        return _error("At most 22 navigation references may be resolved.", 400, code="invalid_request")
    resolved = []
    seen = set()
    for reference in refs:
        if reference in seen:
            continue
        seen.add(reference)
        item = _resolved_reference(actor, reference)
        if item is not None:
            resolved.append(item)
    return JsonResponse(
        {
            "modes": ["teaching", "learning", "student_preview"] if teacher else ["learning"],
            "contexts": contexts,
            "resolved": resolved,
        }
    )


def _class_sections(course, *, learner=False, actor=None):
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
        package_allowed = bool(actor and can_author_course(actor, course))
        payload["capabilities"] = {"manage": package_allowed}
        payload["counts"]["lessons"] = flow_query.count()
        result_route = (
            "liveclassroom:teacher-course-class-results"
            if course.teaching_course_id
            else "liveclassroom:teacher-class-results"
        )
        result_args = [course.teaching_course_id, course.id] if course.teaching_course_id else [course.id]
        if actor and host_can_view_grade_summary(
            actor=actor,
            course_id=course.id,
            package_allowed=package_allowed,
        ):
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
            "classes": [_class_sections(row, actor=request.user) for row in classes],
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
    return JsonResponse(_class_sections(course, actor=request.user))


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
            "classes": [_class_sections(row, learner=True, actor=request.user) for row in classes],
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
    return JsonResponse(_class_sections(course, learner=True, actor=request.user))
