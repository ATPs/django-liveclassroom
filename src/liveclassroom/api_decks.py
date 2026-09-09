"""Private versioned deck authoring endpoints."""

from django.http import Http404, JsonResponse
from django.views.decorators.http import require_http_methods

from .api import _authoring_replay, _body, _error, _record_authoring
from .models import Deck
from .services.classroom import ClassroomError
from .services.decks import copy_deck, create_deck, deck_payload, replace_deck_slides, update_deck
from .services.permissions import can_teach


def _deck(actor, deck_id):
    try:
        return Deck.objects.get(pk=deck_id, owner=actor)
    except Deck.DoesNotExist as exc:
        raise Http404 from exc


def _mutate(request, command_type, action):
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    replay, key = _authoring_replay(request, command_type)
    if replay is not None:
        return replay
    try:
        response = action()
    except Http404:
        response = _error("Not found.", 404, code="not_found")
    except ClassroomError as exc:
        response = _error(str(exc), 409 if "changed" in str(exc).casefold() else 400)
    return _record_authoring(request, key, command_type, response)


@require_http_methods(["GET", "POST"])
def decks(request):
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    if request.method == "GET":
        decks = [deck_payload(deck, include_notes=False) for deck in Deck.objects.filter(owner=request.user)]
        return JsonResponse({"decks": decks})

    def action():
        deck = create_deck(actor=request.user, data=_body(request))
        return JsonResponse(deck_payload(deck), status=201)

    return _mutate(request, "deck.create", action)


@require_http_methods(["GET", "PATCH", "DELETE"])
def deck_detail(request, deck_id):
    if not can_teach(request.user):
        return _error("Teacher access is required.", 403, code="permission_denied")
    if request.method == "GET":
        try:
            return JsonResponse(deck_payload(_deck(request.user, deck_id)))
        except Http404:
            return _error("Not found.", 404, code="not_found")

    def action():
        deck = _deck(request.user, deck_id)
        if request.method == "DELETE":
            deck.delete()
            return JsonResponse({"deleted": True})
        body = _body(request)
        version = body.pop("expected_version", None)
        updated = update_deck(actor=request.user, deck=deck, expected_version=version, data=body)
        return JsonResponse(deck_payload(updated))

    return _mutate(request, f"deck.{request.method.casefold()}", action)


@require_http_methods(["PUT"])
def deck_slides(request, deck_id):
    def action():
        body = _body(request)
        if set(body) != {"expected_version", "slides"}:
            raise ClassroomError("expected_version and slides are required.")
        deck = replace_deck_slides(
            actor=request.user,
            deck=_deck(request.user, deck_id),
            expected_version=body["expected_version"],
            slides=body["slides"],
        )
        return JsonResponse(deck_payload(deck))

    return _mutate(request, "deck.replace_slides", action)


@require_http_methods(["POST"])
def deck_copy(request, deck_id):
    def action():
        body = _body(request)
        if set(body) - {"title"}:
            raise ClassroomError("Unsupported copy fields.")
        deck = copy_deck(actor=request.user, deck=_deck(request.user, deck_id), title=body.get("title"))
        return JsonResponse(deck_payload(deck), status=201)

    return _mutate(request, "deck.copy", action)
