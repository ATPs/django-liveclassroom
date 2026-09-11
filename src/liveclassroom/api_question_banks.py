"""Versioned owner-only APIs for reusable question banks."""

from __future__ import annotations

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from .api import _authoring_replay, _body, _error, _record_authoring
from .models import ActivityDefinition, QuestionBank
from .services.classroom import ClassroomError
from .services.permissions import can_teach
from .services.question_banks import (
    add_question_to_bank,
    copy_question,
    create_question_bank,
    delete_question_bank,
    page_bank_questions,
    remove_question_from_bank,
    update_bank_question,
    update_question_bank,
)


def _access(request):
    if not getattr(request.user, "is_authenticated", False):
        return _error("Authentication required.", 401, code="authentication_required")
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    return None


def _bank(actor, bank_id: int) -> QuestionBank:
    try:
        return QuestionBank.objects.get(pk=bank_id, owner=actor)
    except QuestionBank.DoesNotExist as exc:
        raise Http404 from exc


def _summary(bank: QuestionBank) -> dict:
    return {
        "id": bank.id,
        "title": bank.title,
        "description": bank.description,
        "course_id": bank.course_id,
        "question_count": bank.items.count(),
        "updated_at": bank.updated_at.isoformat(),
    }


def _question(definition: ActivityDefinition) -> dict:
    metadata = definition.metadata if isinstance(definition.metadata, dict) else {}
    return {
        "id": definition.id,
        "title": definition.title,
        "type_key": definition.type_key,
        "metadata": metadata,
        "current_revision_id": definition.current_revision_id,
        "updated_at": definition.updated_at.isoformat(),
    }


def _question_detail(definition: ActivityDefinition) -> dict:
    """Private owner payload for preview/edit; never used in list responses."""
    payload = _question(definition)
    payload.update(
        {
            "definition": definition.definition,
            "asset_id": definition.asset_id,
            "status": definition.status,
            "schema_version": definition.schema_version,
            "revisions": [
                {
                    "id": revision.id,
                    "revision": revision.revision,
                    "payload": revision.payload,
                    "metadata": revision.metadata,
                    "created_at": revision.created_at.isoformat(),
                }
                for revision in definition.revisions.order_by("revision")
            ],
        }
    )
    return payload


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
        response = _error(str(exc), 400 if "permission" not in str(exc).casefold() else 403)
    return _record_authoring(request, key, command_type, response)


@require_http_methods(["GET", "POST"])
def question_banks(request):
    denied = _access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        banks = QuestionBank.objects.filter(owner=request.user).prefetch_related("items").order_by("-updated_at", "-id")
        return JsonResponse({"question_banks": [_summary(bank) for bank in banks]})

    def action():
        bank = create_question_bank(actor=request.user, data=_body(request))
        return JsonResponse(_summary(bank), status=201)

    return _mutate(request, "question_bank.create", action)


@require_http_methods(["GET", "PATCH", "DELETE"])
def question_bank_detail(request, bank_id: int):
    denied = _access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        try:
            return JsonResponse(_summary(_bank(request.user, bank_id)))
        except Http404:
            return _error("Not found.", 404, code="not_found")

    def action():
        bank = _bank(request.user, bank_id)
        if request.method == "PATCH":
            return JsonResponse(_summary(update_question_bank(actor=request.user, bank=bank, changes=_body(request))))
        delete_question_bank(actor=request.user, bank=bank)
        return JsonResponse({"deleted": True})

    return _mutate(request, f"question_bank.{request.method.casefold()}", action)


@require_http_methods(["GET", "POST"])
def question_bank_questions(request, bank_id: int):
    denied = _access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        try:
            bank = _bank(request.user, bank_id)
            filters = {key: request.GET.get(key) for key in ("q", "topic", "tag", "difficulty", "type_key")}
            offset = int(request.GET.get("offset", "0"))
            limit = int(request.GET.get("limit", "20"))
            if offset < 0 or limit < 1 or limit > 100:
                raise ClassroomError("offset and limit are out of range.")
            results, count = page_bank_questions(
                actor=request.user, bank=bank, filters=filters, offset=offset, limit=limit
            )
            return JsonResponse(
                {
                    "questions": [_question(item) for item in results],
                    "count": count,
                    "offset": offset,
                    "limit": limit,
                }
            )
        except (Http404, ValueError):
            return _error("Not found.", 404, code="not_found")
        except ClassroomError as exc:
            return _error(str(exc), 400)

    def action():
        body = _body(request)
        definition_id = body.get("definition_id")
        if set(body) != {"definition_id"} or isinstance(definition_id, bool) or not isinstance(definition_id, int):
            raise ClassroomError("definition_id must be a positive integer.")
        bank = _bank(request.user, bank_id)
        definition = get_object_or_404(ActivityDefinition, pk=definition_id)
        item = add_question_to_bank(actor=request.user, bank=bank, definition=definition)
        return JsonResponse({"id": item.id, "definition": _question(definition)}, status=201)

    return _mutate(request, "question_bank.add_question", action)


@require_http_methods(["GET", "PATCH", "DELETE"])
def question_bank_question(request, bank_id: int, definition_id: int):
    denied = _access(request)
    if denied is not None:
        return denied

    try:
        bank = _bank(request.user, bank_id)
        definition = get_object_or_404(ActivityDefinition, pk=definition_id)
    except Http404:
        return _error("Not found.", 404, code="not_found")
    if request.method == "GET":
        if not bank.items.filter(definition=definition).exists():
            return _error("Not found.", 404, code="not_found")
        return JsonResponse(_question_detail(definition))

    def action():
        if request.method == "PATCH":
            body = _body(request)
            updated = update_bank_question(
                actor=request.user,
                bank=bank,
                definition=definition,
                title=body.pop("title", None),
                payload=body,
            )
            return JsonResponse(_question_detail(updated))
        remove_question_from_bank(actor=request.user, bank=bank, definition=definition)
        return JsonResponse({"deleted": True})

    return _mutate(request, f"question_bank.{request.method.casefold()}_question", action)


@require_http_methods(["POST"])
def question_bank_question_copy(request, bank_id: int, definition_id: int):
    """Copy a private bank member and optionally add it to another own bank."""
    denied = _access(request)
    if denied is not None:
        return denied
    command_type = f"question_bank.copy_question.{bank_id}.{definition_id}"

    def action():
        body = _body(request)
        if set(body) - {"target_bank_id", "title", "metadata"}:
            raise ClassroomError("Unsupported copy fields.")
        target_bank_id = body.pop("target_bank_id", None)
        if target_bank_id is not None and (
            isinstance(target_bank_id, bool) or not isinstance(target_bank_id, int) or target_bank_id <= 0
        ):
            raise ClassroomError("target_bank_id must be a positive integer.")
        source_bank = _bank(request.user, bank_id)
        target_bank = _bank(request.user, target_bank_id) if target_bank_id is not None else None
        definition = get_object_or_404(ActivityDefinition, pk=definition_id)
        copied = copy_question(
            actor=request.user,
            source_bank=source_bank,
            definition=definition,
            title=body.pop("title", None),
            metadata=body.pop("metadata", None),
            target_bank=target_bank,
        )
        return JsonResponse(_question_detail(copied), status=201)

    return _mutate(request, command_type, action)
