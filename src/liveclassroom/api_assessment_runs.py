"""Teacher publication and safe entry metadata for immutable assessment runs."""

from __future__ import annotations

from django.http import Http404, JsonResponse
from django.views.decorators.http import require_http_methods

from .api import _authoring_replay, _body, _error, _record_authoring
from .models import AssessmentDefinition, AssessmentRun, CourseMembership
from .services.assessment_runs import available_run_payload, publish_assessment, run_payload
from .services.classroom import ClassroomError
from .services.permissions import can_teach


def _teacher(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    return None


def _assessment(actor, assessment_id: int) -> AssessmentDefinition:
    try:
        return AssessmentDefinition.objects.get(pk=assessment_id, owner=actor)
    except AssessmentDefinition.DoesNotExist as exc:
        raise Http404 from exc


def _run(actor, public_id) -> AssessmentRun:
    try:
        return AssessmentRun.objects.get(public_id=public_id, owner=actor)
    except AssessmentRun.DoesNotExist as exc:
        raise Http404 from exc


@require_http_methods(["GET", "POST"])
def assessment_runs(request, assessment_id: int):
    denied = _teacher(request)
    if denied is not None:
        return denied
    try:
        assessment = _assessment(request.user, assessment_id)
    except Http404:
        return _error("Not found.", 404, code="not_found")
    if request.method == "GET":
        rows = AssessmentRun.objects.filter(source_assessment=assessment, owner=request.user)
        return JsonResponse({"runs": [run_payload(run) for run in rows]})

    replay, key = _authoring_replay(request, "assessment.publish")
    if replay is not None:
        return replay
    try:
        body = _body(request)
        if set(body) - {"expected_version", "audience"} or "expected_version" not in body:
            raise ClassroomError("expected_version is required.")
        run = publish_assessment(
            actor=request.user,
            assessment=assessment,
            expected_version=body["expected_version"],
            audience=body.get("audience"),
        )
        response = JsonResponse(run_payload(run, include_manifest=True), status=201)
    except ClassroomError as exc:
        status = 409 if "changed" in str(exc).casefold() else 400
        response = _error(str(exc), status, code="stale_revision" if status == 409 else None)
    return _record_authoring(request, key, "assessment.publish", response)


@require_http_methods(["GET"])
def assessment_run_detail(request, public_id):
    denied = _teacher(request)
    if denied is not None:
        return denied
    try:
        return JsonResponse(run_payload(_run(request.user, public_id), include_manifest=True))
    except Http404:
        return _error("Not found.", 404, code="not_found")


@require_http_methods(["GET"])
def available_assessment_run(request, public_id):
    """Return safe metadata only; task 24 owns opening question content."""
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    try:
        run = AssessmentRun.objects.select_related("course").get(public_id=public_id)
    except AssessmentRun.DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    if run.audience == AssessmentRun.Audience.CLASS and not (
        getattr(request.user, "is_superuser", False)
        or run.owner_id == request.user.pk
        or CourseMembership.objects.filter(course_id=run.course_id, user=request.user).exists()
    ):
        return _error("Not found.", 404, code="not_found")
    return JsonResponse(available_run_payload(run))
