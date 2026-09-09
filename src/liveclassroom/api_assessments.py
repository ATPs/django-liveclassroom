"""Owner-scoped APIs for reusable assessment drafts."""

from __future__ import annotations

from django.http import Http404, JsonResponse
from django.views.decorators.http import require_http_methods

from .api import _authoring_replay, _body, _error, _record_authoring
from .models import AssessmentDefinition
from .services.assessment_sections import replace_sections
from .services.assessments import (
    assessment_payload,
    copy_assessment,
    create_assessment,
    replace_items,
    update_assessment,
)
from .services.classroom import ClassroomError
from .services.permissions import can_teach


def _access(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    return None


def _assessment(actor, assessment_id: int) -> AssessmentDefinition:
    try:
        return AssessmentDefinition.objects.prefetch_related("items__question_revision__definition").get(
            pk=assessment_id, owner=actor
        )
    except AssessmentDefinition.DoesNotExist as exc:
        raise Http404 from exc


def _mutate(request, command_type: str, action):
    denied = _access(request)
    if denied is not None:
        return denied
    replay, key = _authoring_replay(request, command_type)
    if replay is not None:
        return replay
    try:
        response = action()
    except Http404:
        response = _error("Not found.", 404, code="not_found")
    except ClassroomError as exc:
        status = 409 if "changed" in str(exc).casefold() else 400
        response = _error(str(exc), status, code="stale_revision" if status == 409 else None)
    return _record_authoring(request, key, command_type, response)


@require_http_methods(["GET", "POST"])
def assessments(request):
    denied = _access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        rows = AssessmentDefinition.objects.filter(owner=request.user).prefetch_related(
            "items__question_revision__definition"
        )
        return JsonResponse(
            {"assessments": [assessment_payload(row, include_revision=False) for row in rows]}
        )

    def action():
        assessment = create_assessment(actor=request.user, data=_body(request))
        assessment = AssessmentDefinition.objects.prefetch_related("items__question_revision__definition").get(
            pk=assessment.pk
        )
        return JsonResponse(assessment_payload(assessment), status=201)

    return _mutate(request, "assessment.create", action)


@require_http_methods(["GET", "PATCH", "DELETE"])
def assessment_detail(request, assessment_id: int):
    denied = _access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        try:
            return JsonResponse(assessment_payload(_assessment(request.user, assessment_id)))
        except Http404:
            return _error("Not found.", 404, code="not_found")

    def action():
        assessment = _assessment(request.user, assessment_id)
        if request.method == "DELETE":
            assessment.delete()
            return JsonResponse({"deleted": True})
        body = _body(request)
        expected_version = body.pop("expected_version", None)
        updated = update_assessment(
            actor=request.user,
            assessment=assessment,
            expected_version=expected_version,
            data=body,
        )
        updated = AssessmentDefinition.objects.prefetch_related("items__question_revision__definition").get(
            pk=updated.pk
        )
        return JsonResponse(assessment_payload(updated))

    return _mutate(request, f"assessment.{request.method.casefold()}", action)


@require_http_methods(["GET", "PUT"])
def assessment_items(request, assessment_id: int):
    denied = _access(request)
    if denied is not None:
        return denied
    try:
        assessment = _assessment(request.user, assessment_id)
    except Http404:
        return _error("Not found.", 404, code="not_found")
    if request.method == "GET":
        payload = assessment_payload(assessment)
        return JsonResponse({"assessment_id": assessment.id, "version": assessment.version, "items": payload["items"]})

    def action():
        body = _body(request)
        if set(body) != {"expected_version", "items"}:
            raise ClassroomError("expected_version and items are required.")
        updated = replace_items(
            actor=request.user,
            assessment=assessment,
            expected_version=body["expected_version"],
            items=body["items"],
        )
        updated = AssessmentDefinition.objects.prefetch_related("items__question_revision__definition").get(
            pk=updated.pk
        )
        return JsonResponse(assessment_payload(updated))

    return _mutate(request, "assessment.replace_items", action)


@require_http_methods(["GET", "PUT"])
def assessment_sections(request, assessment_id: int):
    """Read or atomically replace the ordered section/pool draft."""
    denied = _access(request)
    if denied is not None:
        return denied
    try:
        assessment = _assessment(request.user, assessment_id)
    except Http404:
        return _error("Not found.", 404, code="not_found")
    if request.method == "GET":
        payload = assessment_payload(assessment)
        return JsonResponse(
            {"assessment_id": assessment.id, "version": assessment.version, "sections": payload["sections"]}
        )

    def action():
        body = _body(request)
        if set(body) != {"expected_version", "sections"}:
            raise ClassroomError("expected_version and sections are required.")
        updated = replace_sections(
            actor=request.user,
            assessment=assessment,
            expected_version=body["expected_version"],
            sections=body["sections"],
        )
        updated = AssessmentDefinition.objects.prefetch_related(
            "items__question_revision__definition", "sections__entries__item", "sections__entries__bank"
        ).get(pk=updated.pk)
        return JsonResponse(assessment_payload(updated))

    return _mutate(request, "assessment.replace_sections", action)


@require_http_methods(["POST"])
def assessment_copy(request, assessment_id: int):
    def action():
        body = _body(request)
        if set(body) - {"title"}:
            raise ClassroomError("Unsupported copy fields.")
        copied = copy_assessment(
            actor=request.user,
            assessment=_assessment(request.user, assessment_id),
            title=body.get("title"),
        )
        copied = AssessmentDefinition.objects.prefetch_related("items__question_revision__definition").get(
            pk=copied.pk
        )
        return JsonResponse(assessment_payload(copied), status=201)

    return _mutate(request, "assessment.copy", action)
