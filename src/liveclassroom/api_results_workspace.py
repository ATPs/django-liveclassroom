"""Read-only, paginated discovery for the teacher results workspace."""

from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from .api import _error
from .models import AssessmentAttempt, AssessmentRun, Participant
from .services.assessment_exports import _attempt_row
from .services.assessment_progress import _accessible_runs, can_read_run_progress
from .services.grade_corrections import _can_manage_run, item_grade_fingerprint
from .services.manual_grading import _prompt, can_grade_attempt
from .services.permissions import can_teach


def _denied(request):
    if not request.user.is_authenticated:
        return _error("Authentication required.", 401, code="authentication_required")
    if not can_teach(request.user):
        return _error("Not found.", 404, code="not_found")
    return None


def _page(request, rows):
    try:
        number = int(request.GET.get("page", 1))
        requested_size = int(request.GET.get("page_size", 25))
        if number < 1 or requested_size < 1:
            raise ValueError
        size = min(100, requested_size)
    except (TypeError, ValueError):
        return _error("Invalid pagination.", 400, code="invalid_request")
    count = rows.count() if hasattr(rows, "query") else len(rows)

    def link(target):
        query = request.GET.copy()
        query["page"] = str(target)
        return f"{request.path}?{query.urlencode()}"

    return {
        "items": list(rows[(number - 1) * size:number * size]),
        "count": count, "page": number, "page_size": size,
        "next": link(number + 1) if number * size < count else None,
        "previous": link(number - 1) if number > 1 else None,
    }


def _response(payload):
    response = JsonResponse(payload)
    response["Cache-Control"] = "private, no-store"
    return response


@require_GET
def runs(request):
    denied = _denied(request)
    if denied is not None:
        return denied
    rows = _accessible_runs(request.user).filter(title__icontains=request.GET.get("q", ""))
    class_id = request.GET.get("class_id")
    course_id = request.GET.get("course_id")
    try:
        if class_id:
            rows = rows.filter(course_id=int(class_id))
        if course_id:
            rows = rows.filter(course__teaching_course_id=int(course_id))
    except ValueError:
        return _error("Invalid scope.", 400, code="invalid_request")
    order = {"title": "title", "-title": "-title", "recent": "-created_at"}.get(request.GET.get("sort"), "-created_at")
    # Host authorization must precede pagination and counts.
    allowed = [run for run in rows.order_by(order, "id") if can_read_run_progress(request.user, run)]
    payload = _page(request, allowed)
    if not isinstance(payload, dict):
        return payload
    payload["items"] = [{
        "public_id": str(run.public_id), "title": run.title,
        "class_id": run.course_id,
        "attempts_url": reverse("liveclassroom:api-v1-result-attempts", args=[run.public_id]),
    } for run in payload["items"]]
    return _response(payload)


@require_GET
def attempts(request, public_id):
    denied = _denied(request)
    if denied is not None:
        return denied
    run = AssessmentRun.objects.select_related("course").filter(public_id=public_id).first()
    if run is None or not can_read_run_progress(request.user, run):
        return _error("Not found.", 404, code="not_found")
    if request.GET.get("class_id") and request.GET["class_id"] != str(run.course_id):
        return _error("Not found.", 404, code="not_found")
    if request.GET.get("course_id") and (
        run.course is None or request.GET["course_id"] != str(run.course.teaching_course_id)
    ):
        return _error("Not found.", 404, code="not_found")
    test_ids = Participant.objects.filter(is_test=True, user_id__isnull=False).values_list("user_id", flat=True)
    rows = (
        AssessmentAttempt.objects.filter(run=run)
        .exclude(user_id__in=test_ids)
        .select_related("run", "user", "grade")
        .prefetch_related("items")
        .order_by("user_id", "-attempt_number", "id")
    )
    status = request.GET.get("status", "")
    if status:
        rows = rows.filter(status=status)
    payload = _page(request, rows)
    if not isinstance(payload, dict):
        return payload
    payload["items"] = [
        _attempt_row(attempt, details=False) | {
            "detail_url": reverse("liveclassroom:api-v1-result-attempt", args=[attempt.public_id])
            if can_grade_attempt(request.user, attempt) else None,
        } for attempt in payload["items"]
    ]
    payload["run"] = {"public_id": str(run.public_id), "title": run.title}
    return _response(payload)


@require_GET
def attempt_detail(request, public_id):
    denied = _denied(request)
    if denied is not None:
        return denied
    attempt = AssessmentAttempt.objects.select_related("run", "run__course", "user", "grade").prefetch_related(
        "items__answer_revisions", "items__grade_decisions", "items__grade",
    ).filter(public_id=public_id).first()
    # Retained answers use the existing grading authorization, never the
    # account-bound learner review API or a global can_teach assumption.
    if (
        attempt is None
        or not can_read_run_progress(request.user, attempt.run)
        or not can_grade_attempt(request.user, attempt)
    ):
        return _error("Not found.", 404, code="not_found")
    if Participant.objects.filter(is_test=True, user_id=attempt.user_id).exists():
        return _error("Not found.", 404, code="not_found")
    payload = _attempt_row(attempt, details=True)
    retained = {str(item.key): item for item in attempt.items.all()}
    for row in payload["items"]:
        row["prompt"] = _prompt(retained[row["item_key"]])
        row["grade_fingerprint"] = item_grade_fingerprint(attempt_item=retained[row["item_key"]])
        row["override_url"] = (
            reverse(
                "liveclassroom:api-v1-grade-override",
                args=[attempt.public_id, row["item_key"]],
            )
            if attempt.status == AssessmentAttempt.Status.SUBMITTED
            and _can_manage_run(request.user, attempt.run)
            else None
        )
    return _response(payload)
