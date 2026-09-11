"""Bounded learner destinations, without joining or starting anything."""

from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from .api import _error
from .api_browse import _learning_classes
from .api_results_workspace import _page
from .models import AssessmentRun, LiveSession
from .services.attempts import _can_access


@require_GET
def items(request, kind):
    if not request.user.is_authenticated:
        return _error("Authentication required.", 401, code="authentication_required")
    if kind not in {"sessions", "assessments"}:
        return _error("Not found.", 404, code="not_found")
    classes = _learning_classes(request.user)
    try:
        if request.GET.get("class_id"):
            classes = classes.filter(pk=int(request.GET["class_id"]))
        if request.GET.get("course_id"):
            classes = classes.filter(teaching_course_id=int(request.GET["course_id"]))
    except ValueError:
        return _error("Invalid scope.", 400, code="invalid_request")
    sort = request.GET.get("sort") or "title"
    sort_fields = {
        "title": ("title", "id"),
        "-title": ("-title", "-id"),
    }
    if kind == "sessions":
        sort_fields.update({"recent": ("-updated_at", "-id"), "-recent": ("updated_at", "id")})
    elif kind == "assessments":
        # Published runs are immutable, so creation time is their recency field.
        sort_fields.update({"recent": ("-created_at", "-id"), "-recent": ("created_at", "id")})
    if sort not in sort_fields:
        return _error("sort is not a supported browse sort.", 400, code="invalid_request")
    query = request.GET.get("q", "").strip()
    if kind == "sessions":
        rows = LiveSession.objects.filter(course__in=classes).exclude(status=LiveSession.Status.DRAFT)
        if query:
            rows = rows.filter(title__icontains=query)
        rows = rows.order_by(*sort_fields[sort])
        payload = _page(request, rows)
        if not isinstance(payload, dict):
            return payload
        payload["items"] = [{"id": row.id, "title": row.title, "status": row.status,
            "url": reverse("liveclassroom:student-session", args=[row.id])} for row in payload["items"]]
    elif kind == "assessments":
        rows = AssessmentRun.objects.filter(course__in=classes).select_related("course")
        if query:
            rows = rows.filter(title__icontains=query)
        rows = rows.order_by(*sort_fields[sort])
        allowed = [row for row in rows if _can_access(request.user, row)]
        payload = _page(request, allowed)
        if not isinstance(payload, dict):
            return payload
        payload["items"] = [{"public_id": str(row.public_id), "title": row.title,
            "url": reverse("liveclassroom:assessment-attempt", args=[row.public_id])} for row in payload["items"]]
    response = JsonResponse(payload)
    response["Cache-Control"] = "private, no-store"
    return response
