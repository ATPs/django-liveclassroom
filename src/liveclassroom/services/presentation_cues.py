"""Teacher controlled slide cues and host neutral presentation sources.

Cues are deliberately retained with the live session rather than with a deck
or a lesson.  A cue is a small piece of session authoring state: it connects a
retained slide position to one existing session-plan step.  The source is
reauthorized whenever it is listed or launched, so a provider can revoke or
change a source without leaving an unbounded access grant behind.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from django.db import transaction

from liveclassroom.models import DeckSnapshot, LiveSession, SessionPlanStep
from liveclassroom.providers import ContentReference, ProviderError, content_providers

from .authoring import _safe_reference_value
from .classroom import ClassroomError, can_manage_session
from .plans import launch_plan_step
from .presentation import _slide, _snapshot_for_actor

_CUES_KEY = "presentation_cues"
_MAX_CUES = 200
_MAX_SLIDE_INDEX = 10_000


def _require_manager(actor, session: LiveSession) -> None:
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to manage presentation cues.")


def _positive_index(value: Any, *, field: str = "slide_index") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < _MAX_SLIDE_INDEX:
        raise ClassroomError(f"{field} must be an integer from 0 to {_MAX_SLIDE_INDEX - 1}.")
    return value


def _step(session: LiveSession, value: Any) -> SessionPlanStep:
    if not isinstance(value, str) or not value.strip():
        raise ClassroomError("step_key is required.")
    try:
        step = SessionPlanStep.objects.get(session=session, key=value, removed=False)
    except (SessionPlanStep.DoesNotExist, ValueError):
        raise ClassroomError("The selected lesson step is unavailable.") from None
    return step


def _store(session: LiveSession) -> list[dict[str, Any]]:
    settings = session.creation_settings if isinstance(session.creation_settings, dict) else {}
    cues = settings.get(_CUES_KEY, [])
    return [deepcopy(item) for item in cues if isinstance(item, dict)] if isinstance(cues, list) else []


def _save_store(session: LiveSession, cues: list[dict[str, Any]]) -> None:
    settings = deepcopy(session.creation_settings) if isinstance(session.creation_settings, dict) else {}
    if cues:
        settings[_CUES_KEY] = cues
    else:
        settings.pop(_CUES_KEY, None)
    session.creation_settings = settings
    session.save(update_fields=["creation_settings", "updated_at"])


def _source_fingerprint(reference: ContentReference, descriptor: Mapping[str, Any]) -> str:
    value = descriptor.get("source_fingerprint", descriptor.get("fingerprint", ""))
    if isinstance(value, str) and value.strip():
        return value.strip()[:128]
    # A provider may describe a stable source without supplying a digest.  A
    # local digest still gives us a useful identity while keeping source text
    # out of storage and logs.
    raw = json.dumps(
        {"provider": reference.provider, "kind": reference.kind, "value": reference.value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _provider_source(*, actor, source: Mapping[str, Any], request=None) -> dict[str, Any]:
    provider_key = source.get("provider")
    if not isinstance(provider_key, str) or not provider_key.strip():
        raise ClassroomError("A content provider is required.")
    provider_key = provider_key.strip()
    try:
        provider = content_providers().get(provider_key)
        raw = source.get("reference")
        if isinstance(raw, Mapping):
            reference = ContentReference(
                provider_key,
                str(raw.get("kind", "")),
                dict(raw.get("value", {})) if isinstance(raw.get("value"), Mapping) else {},
            )
        elif isinstance(source.get("url"), str):
            reference = provider.parse_reference(source["url"], request=request)
        else:
            raise ProviderError("A provider URL or reference is required.")
        validated = provider.validate_reference(reference, request=request)
        descriptor = provider.describe(validated, request=request)
    except (ProviderError, TypeError, ValueError, AttributeError) as exc:
        raise ClassroomError("The presentation source is unavailable or not authorized.") from exc
    if not isinstance(descriptor, Mapping):
        raise ClassroomError("The presentation provider returned invalid metadata.")
    try:
        safe_value = _safe_reference_value(validated.value)
    except ClassroomError:
        raise
    title = descriptor.get("title", "")
    if not isinstance(title, str):
        title = ""
    slide_capable = descriptor.get("slide_capable", descriptor.get("supports_slides", True))
    if not isinstance(slide_capable, bool):
        slide_capable = bool(slide_capable)
    embed_url = ""
    try:
        candidate = provider.embed_url(validated, request=request)
        if isinstance(candidate, str) and len(candidate) <= 4096:
            embed_url = candidate
    except (ProviderError, TypeError, ValueError, AttributeError):
        # A provider can support discovery without providing an iframe URL.
        pass
    return {
        "type": "external",
        "provider": validated.provider,
        "reference": {"provider": validated.provider, "kind": validated.kind, "value": safe_value},
        "title": title[:200],
        "slide_capable": slide_capable,
        "source_fingerprint": _source_fingerprint(validated, descriptor),
        "embed_url": embed_url,
    }


def prepare_provider_source(*, actor, source: Mapping[str, Any], request=None) -> dict[str, Any]:
    """Resolve a provider URL/reference into safe metadata for the picker."""
    if not isinstance(source, Mapping):
        raise ClassroomError("A presentation source must be an object.")
    return _provider_source(actor=actor, source=source, request=request)


def provider_search(*, actor, provider_key: str, query: str, request=None) -> list[dict[str, Any]]:
    """Search only through a configured provider's own authorization boundary."""
    if not isinstance(provider_key, str) or not provider_key.strip():
        raise ClassroomError("A content provider is required.")
    if not isinstance(query, str) or not query.strip():
        raise ClassroomError("A search query is required.")
    if len(query) > 200:
        raise ClassroomError("The search query is too long.")
    try:
        provider = content_providers().get(provider_key.strip())
        search = getattr(provider, "search", None)
        if not callable(search):
            raise ProviderError("This provider does not support search.")
        results = search(query.strip(), request=request)
    except (ProviderError, TypeError, ValueError, AttributeError) as exc:
        raise ClassroomError("Provider search is unavailable.") from exc
    if not isinstance(results, list):
        raise ClassroomError("The provider returned invalid search results.")
    normalized: list[dict[str, Any]] = []
    for item in results[:50]:
        if not isinstance(item, Mapping):
            continue
        source = item.get("source") if isinstance(item.get("source"), Mapping) else item
        try:
            resolved = _provider_source(actor=actor, source=source, request=request)
        except ClassroomError:
            # A stale or revoked search result should not make other results
            # disappear and should never be returned without reauthorization.
            continue
        normalized.append(resolved)
    return normalized


def _native_source(*, actor, source: Mapping[str, Any]) -> dict[str, Any]:
    snapshot_id = source.get("snapshot_id")
    if isinstance(snapshot_id, bool) or not isinstance(snapshot_id, int) or snapshot_id <= 0:
        raise ClassroomError("snapshot_id must be a positive integer.")
    try:
        snapshot = DeckSnapshot.objects.get(pk=snapshot_id)
    except DeckSnapshot.DoesNotExist:
        raise ClassroomError("The selected deck snapshot is unavailable.") from None
    _snapshot_for_actor(actor, snapshot)
    index = _positive_index(source.get("slide_index", 0))
    index, item = _slide(snapshot, slide_index=index)
    return {
        "type": "native",
        "snapshot_id": snapshot.pk,
        "title": snapshot.title[:200],
        "source_fingerprint": str(snapshot.fingerprint)[:128],
        "slide_key": str(item["key"]),
        "slide_index": index,
    }


def _normalize_source(*, actor, source: Any, request=None) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise ClassroomError("source must be an object.")
    source_type = source.get("type", source.get("source_type"))
    if source_type in {"native", "deck", "native_deck"} or "snapshot_id" in source:
        if source.get("provider") or source.get("url") or source.get("reference"):
            raise ClassroomError("A cue source must be native or external, not both.")
        return _native_source(actor=actor, source=source)
    if source_type not in {None, "external", "provider"}:
        raise ClassroomError("Unsupported presentation source type.")
    resolved = _provider_source(actor=actor, source=source, request=request)
    if "slide_index" in source:
        resolved["slide_index"] = _positive_index(source["slide_index"])
    else:
        resolved["slide_index"] = 0
    return resolved


def _find(cues: list[dict[str, Any]], cue_id: Any) -> dict[str, Any]:
    text = str(cue_id)
    for cue in cues:
        if str(cue.get("id", "")) == text:
            return cue
    raise ClassroomError("The presentation cue was not found.")


def _current_source(cue: Mapping[str, Any], *, actor, request=None) -> tuple[dict[str, Any], str | None]:
    source = cue.get("source")
    if not isinstance(source, Mapping):
        return {"valid": False, "status": "unavailable", "error_code": "invalid_source"}, None
    if source.get("type") == "native":
        try:
            fresh = _native_source(actor=actor, source=source)
        except ClassroomError:
            return {"valid": False, "status": "unavailable", "error_code": "source_unavailable"}, None
        if fresh["source_fingerprint"] != source.get("source_fingerprint"):
            return (
                {"valid": False, "status": "reattach_required", "error_code": "source_changed"},
                fresh["source_fingerprint"],
            )
        if fresh["slide_key"] != source.get("slide_key"):
            return (
                {"valid": False, "status": "reattach_required", "error_code": "slide_changed"},
                fresh["source_fingerprint"],
            )
        return {"valid": True, "status": "ready"}, fresh["source_fingerprint"]
    try:
        fresh = _provider_source(actor=actor, source=source, request=request)
    except ClassroomError:
        return {"valid": False, "status": "unavailable", "error_code": "source_unavailable"}, None
    if fresh["source_fingerprint"] != source.get("source_fingerprint"):
        return (
            {"valid": False, "status": "reattach_required", "error_code": "source_changed"},
            fresh["source_fingerprint"],
        )
    return {"valid": True, "status": "ready"}, fresh["source_fingerprint"]


def cue_payload(cue: Mapping[str, Any], *, actor, request=None) -> dict[str, Any]:
    result = {
        "id": str(cue.get("id", "")),
        "step_key": str(cue.get("step_key", "")),
        "action": cue.get("action", "offer_activity"),
        "source": deepcopy(cue.get("source", {})),
    }
    status, current_fingerprint = _current_source(cue, actor=actor, request=request)
    result.update(status)
    if current_fingerprint:
        result["current_source_fingerprint"] = current_fingerprint
    return result


def list_presentation_cues(*, session: LiveSession, actor, request=None) -> list[dict[str, Any]]:
    _require_manager(actor, session)
    # Callers commonly keep the session instance used to create the classroom;
    # reload so a just-attached cue is visible after another transaction.
    current = LiveSession.objects.get(pk=session.pk)
    return [cue_payload(cue, actor=actor, request=request) for cue in _store(current)]


@transaction.atomic
def create_presentation_cue(*, session: LiveSession, actor, data: Mapping[str, Any], request=None) -> dict[str, Any]:
    _require_manager(actor, session)
    if not isinstance(data, Mapping):
        raise ClassroomError("A cue must be an object.")
    step = _step(session, data.get("step_key"))
    source = _normalize_source(actor=actor, source=data.get("source", data), request=request)
    cue = {"id": str(uuid.uuid4()), "step_key": str(step.key), "action": "offer_activity", "source": source}
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    # Read after taking the lock so concurrent cue creation cannot lose a
    # sibling cue.
    cues = _store(locked)
    if len(cues) >= _MAX_CUES:
        raise ClassroomError("This classroom has reached its cue limit.")
    cues.append(cue)
    _save_store(locked, cues)
    return cue_payload(cue, actor=actor, request=request)


@transaction.atomic
def replace_presentation_cue(
    *, session: LiveSession, actor, cue_id: str, data: Mapping[str, Any], request=None
) -> dict[str, Any]:
    _require_manager(actor, session)
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    cues = _store(locked)
    cue = _find(cues, cue_id)
    if "step_key" in data:
        step = _step(locked, data["step_key"])
        cue["step_key"] = str(step.key)
    if "source" in data:
        cue["source"] = _normalize_source(actor=actor, source=data["source"], request=request)
    else:
        # A changed external source must be explicitly reattached; do not
        # silently refresh its stored fingerprint while editing a step.
        _current_source(cue, actor=actor, request=request)
    _save_store(locked, cues)
    return cue_payload(cue, actor=actor, request=request)


@transaction.atomic
def delete_presentation_cue(*, session: LiveSession, actor, cue_id: str) -> None:
    _require_manager(actor, session)
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    cues = _store(locked)
    _find(cues, cue_id)
    _save_store(locked, [cue for cue in cues if str(cue.get("id")) != str(cue_id)])


@transaction.atomic
def launch_presentation_cue(
    *, session: LiveSession, actor, cue_id: str, channel: str = "display", request=None
) -> dict[str, Any]:
    _require_manager(actor, session)
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    cue = _find(_store(locked), cue_id)
    status, _ = _current_source(cue, actor=actor, request=request)
    if not status.get("valid"):
        raise ClassroomError("Reattach the presentation cue before launching it.")
    step = _step(locked, cue.get("step_key"))
    activity = launch_plan_step(session=locked, step=step, actor=actor, channel=channel, restart=False)
    return {"cue": cue_payload(cue, actor=actor, request=request), "activity_id": activity.pk, "channel": channel}
