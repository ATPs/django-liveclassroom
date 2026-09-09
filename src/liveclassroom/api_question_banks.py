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
    create_question_bank,
    delete_question_bank,
    list_bank_questions,
    remove_question_from_bank,
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
            results = list_bank_questions(actor=request.user, bank=bank, filters=filters)
            return JsonResponse(
                {
                    "questions": [_question(item) for item in results[offset : offset + limit]],
                    "count": len(results),
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


@require_http_methods(["DELETE"])
def question_bank_question(request, bank_id: int, definition_id: int):
    def action():
        bank = _bank(request.user, bank_id)
        definition = get_object_or_404(ActivityDefinition, pk=definition_id)
        remove_question_from_bank(actor=request.user, bank=bank, definition=definition)
        return JsonResponse({"deleted": True})

    return _mutate(request, "question_bank.remove_question", action)
