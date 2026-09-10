"""Streaming authorized assessment-result export endpoints."""

from __future__ import annotations

from django.http import StreamingHttpResponse
from django.views.decorators.http import require_GET

from .api import _error
from .models import AssessmentAttempt, AssessmentRun
from .services.assessment_exports import (
    AssessmentExportError,
    student_csv_export,
    student_json_export,
    student_result_projection,
    teacher_class_export,
    teacher_csv_export,
    teacher_json_export,
    teacher_run_export,
)


def _format(request) -> str:
    value = request.GET.get("format", "csv").casefold()
    if value not in {"csv", "json"}:
        raise AssessmentExportError("format must be csv or json.")
    return value


def _details(request) -> bool:
    value = request.GET.get("details", "false").casefold()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no", ""}:
        return False
    raise AssessmentExportError("details must be a boolean.")


def _download(iterator, *, output_format: str, filename: str) -> StreamingHttpResponse:
    content_type = "text/csv; charset=utf-8" if output_format == "csv" else "application/json; charset=utf-8"
    response = StreamingHttpResponse(iterator, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}.{output_format}"'
    response["Cache-Control"] = "private, no-store"
    return response


def _teacher_response(request, projection_factory, *, filename: str):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    try:
        output_format = _format(request)
        details = _details(request)
        projection = projection_factory(details=details)
    except AssessmentExportError as exc:
        message = str(exc)
        status = 400 if "must be" in message else 404 if "not found" in message.casefold() else 403
        return _error(
            message if status == 400 else "Not found." if status == 404 else message,
            status,
            code="invalid_request" if status == 400 else "not_found" if status == 404 else "permission_denied",
        )
    iterator = (
        teacher_csv_export(projection, details=details) if output_format == "csv" else teacher_json_export(projection)
    )
    return _download(iterator, output_format=output_format, filename=filename)


@require_GET
def assessment_run_export(request, public_id):
    try:
        run = AssessmentRun.objects.get(public_id=public_id)
        filename = f"assessment-results-{run.public_id}"
    except AssessmentRun.DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    return _teacher_response(
        request, lambda *, details: teacher_run_export(request.user, run, details=details), filename=filename
    )


@require_GET
def class_export(request, class_id: int):
    return _teacher_response(
        request,
        lambda *, details: teacher_class_export(request.user, class_id, details=details),
        filename=f"assessment-results-class-{class_id}",
    )


@require_GET
def attempt_export(request, public_id):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    try:
        output_format = _format(request)
        projection = student_result_projection(
            request.user, AssessmentAttempt.objects.select_related("run").get(public_id=public_id)
        )
    except AssessmentExportError as exc:
        message = str(exc)
        if "must be" in message:
            return _error(message, 400, code="invalid_request")
        return _error("Not found.", 404, code="not_found")
    except AssessmentAttempt.DoesNotExist:
        return _error("Not found.", 404, code="not_found")
    iterator = student_csv_export(projection) if output_format == "csv" else student_json_export(projection)
    return _download(iterator, output_format=output_format, filename=f"assessment-result-{public_id}")


__all__ = ["assessment_run_export", "attempt_export", "class_export"]
