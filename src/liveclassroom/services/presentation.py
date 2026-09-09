"""Presentation helpers shared by live activities and native deck delivery.

Native deck presentation state lives in the existing session JSON settings. It
is intentionally separate from ``SessionChannelState.current_activity`` so a
projector can show a deck while a teacher publishes an activity to students.
Session versioning and events remain the source of truth for updates.
"""

import re
from copy import deepcopy

from django.db import transaction
from django.urls import reverse

from liveclassroom.models import DeckSnapshot, LiveSession, SessionChannelState

from .classroom import ClassroomError, _advance_version, _append_event, can_manage_session
from .events import notify_session_after_commit
from .permissions import can_teach

_BASH_DEMO_KEYS = {
    "welcome", "confidence_poll", "word_cloud", "terminal_map", "cheatsheet", "simulator", "timer",
    "true_false", "multiple_choice", "single_choice", "numeric", "rating", "ranking", "reflection",
}
_LEGACY_BASH_TITLE = re.compile(r"^\[bash-demo:(?:en|zh-Hans):([a-z0-9_]+)\]\s+(.+)$")


def presentation_title(title: object, fallback: str = "Activity") -> str:
    """Return a human-facing label without modifying stored title data."""
    value = title if isinstance(title, str) else fallback
    match = _LEGACY_BASH_TITLE.match(value)
    if match and match.group(1) in _BASH_DEMO_KEYS:
        return match.group(2)
    return value


_NATIVE_DECKS_KEY = "native_deck_presentations"


def _channel_list(channels) -> list[str]:
    if not isinstance(channels, (list, tuple)) or not channels:
        raise ClassroomError("At least one audience channel is required.")
    values = list(dict.fromkeys(channels))
    if len(values) != len(channels) or any(value not in SessionChannelState.Channel.values for value in values):
        raise ClassroomError("Unsupported session channel.")
    return values


def _slide(snapshot: DeckSnapshot, *, slide_index: int | None = None, slide_key: str | None = None) -> tuple[int, dict]:
    slides = snapshot.public_manifest if isinstance(snapshot.public_manifest, list) else []
    if not slides:
        raise ClassroomError("The selected deck snapshot has no slides.")
    if slide_key is not None:
        for index, item in enumerate(slides):
            if isinstance(item, dict) and str(item.get("key", "")) == slide_key:
                return index, item
        raise ClassroomError("The selected deck slide was not found.")
    if slide_index is None:
        slide_index = 0
    if isinstance(slide_index, bool) or not isinstance(slide_index, int) or not 0 <= slide_index < len(slides):
        raise ClassroomError("The deck slide index is out of range.")
    item = slides[slide_index]
    if not isinstance(item, dict) or not isinstance(item.get("key"), str):
        raise ClassroomError("The selected deck snapshot is invalid.")
    return slide_index, item


def _snapshot_for_actor(actor, snapshot: DeckSnapshot) -> None:
    source = snapshot.source_deck
    if not can_teach(actor):
        raise ClassroomError("You do not have permission to present a deck.")
    if getattr(actor, "is_superuser", False):
        return
    if source is None or source.owner_id != actor.pk:
        raise ClassroomError("You do not have permission to present this deck.")


def _native_store(session: LiveSession) -> dict[str, dict]:
    settings = session.creation_settings if isinstance(session.creation_settings, dict) else {}
    raw = settings.get(_NATIVE_DECKS_KEY, {})
    return deepcopy(raw) if isinstance(raw, dict) else {}


def _save_native_store(session: LiveSession, store: dict[str, dict]) -> None:
    settings = deepcopy(session.creation_settings) if isinstance(session.creation_settings, dict) else {}
    settings[_NATIVE_DECKS_KEY] = store
    session.creation_settings = settings
    session.save(update_fields=["creation_settings", "updated_at"])


@transaction.atomic
def present_deck(
    *, session: LiveSession, actor, snapshot: DeckSnapshot, channels=(SessionChannelState.Channel.DISPLAY,),
    slide_index: int = 0, allow_review: bool = False,
) -> dict:
    """Retain one immutable snapshot in one or both audience channels."""
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to control this session.")
    if not isinstance(allow_review, bool):
        raise ClassroomError("allow_review must be a boolean.")
    channels = _channel_list(channels)
    _snapshot_for_actor(actor, snapshot)
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    if locked.status == LiveSession.Status.ENDED:
        raise ClassroomError("An ended classroom cannot present a deck.")
    snapshot = DeckSnapshot.objects.get(pk=snapshot.pk)
    index, item = _slide(snapshot, slide_index=slide_index)
    store = _native_store(locked)
    # Clear stale native entries only for the channels explicitly replaced.
    version = _advance_version(locked)
    entry = {
        "snapshot_id": snapshot.id,
        "slide_key": str(item["key"]),
        "slide_index": index,
        "revision": version,
        "allow_review": allow_review,
    }
    for channel in channels:
        store[channel] = deepcopy(entry)
    _save_native_store(locked, store)
    for channel in channels:
        state, _ = SessionChannelState.objects.get_or_create(session=locked, channel=channel)
        state.document_page = index + 1
        state.document_navigation = (
            SessionChannelState.DocumentNavigation.FOLLOW
            if channel == SessionChannelState.Channel.PARTICIPANTS
            else state.document_navigation
        )
        state.version = version
        state.save(update_fields=["document_page", "document_navigation", "version", "updated_at"])
    event_id = _append_event(
        locked, "deck.presented", actor,
        {"channels": sorted(channels), "snapshot_id": snapshot.id, "slide_key": str(item["key"])},
    )
    notify_session_after_commit(
        locked.id,
        {"protocol": 1, "session_id": locked.id, "version": version, "event_id": event_id,
         "type": "deck.presented", "payload": {"channels": sorted(channels), "snapshot_id": snapshot.id}},
    )
    return native_deck_presentation_payload(snapshot, entry)


@transaction.atomic
def update_deck_presentation(
    *, session: LiveSession, actor, channels, slide_index: int | None = None,
    slide_key: str | None = None, action: str | None = None, expected_revision: int | None = None,
    navigation: str | None = None,
) -> dict:
    """Move native deck channels using the same durable session revision path."""
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to control this session.")
    channels = _channel_list(channels)
    if action not in {None, "previous", "next", "go_to"}:
        raise ClassroomError("Unsupported deck navigation command.")
    locked = LiveSession.objects.select_for_update().get(pk=session.pk)
    if locked.status == LiveSession.Status.ENDED:
        raise ClassroomError("An ended classroom cannot change deck presentation.")
    store = _native_store(locked)
    entries = [store.get(channel) for channel in channels]
    if any(not isinstance(entry, dict) for entry in entries):
        raise ClassroomError("The selected channel is not presenting a native deck.")
    if len({entry.get("snapshot_id") for entry in entries}) != 1:
        raise ClassroomError("Both channels must present the same deck before they can move together.")
    if expected_revision is not None and any(entry.get("revision") != expected_revision for entry in entries):
        raise ClassroomError("The deck presentation changed; refresh before navigating.")
    snapshot = DeckSnapshot.objects.get(pk=entries[0]["snapshot_id"])
    current_index = entries[0].get("slide_index")
    if not isinstance(current_index, int):
        current_index = 0
    if action == "previous":
        slide_index = current_index - 1
    elif action == "next":
        slide_index = current_index + 1
    elif action is None and slide_index is None and slide_key is None:
        slide_index = current_index
    index, item = _slide(snapshot, slide_index=slide_index, slide_key=slide_key)
    if navigation is not None and navigation not in SessionChannelState.DocumentNavigation.values:
        raise ClassroomError("Unsupported student document navigation mode.")
    version = _advance_version(locked)
    for channel, entry in zip(channels, entries):
        entry = deepcopy(entry)
        entry.update({"slide_index": index, "slide_key": str(item["key"]), "revision": version})
        if channel == SessionChannelState.Channel.PARTICIPANTS and navigation is not None:
            entry["navigation_mode"] = navigation
        store[channel] = entry
        state, _ = SessionChannelState.objects.get_or_create(session=locked, channel=channel)
        state.document_page = index + 1
        if channel == SessionChannelState.Channel.PARTICIPANTS and navigation is not None:
            state.document_navigation = navigation
        state.version = version
        fields = ["document_page", "version", "updated_at"]
        if channel == SessionChannelState.Channel.PARTICIPANTS and navigation is not None:
            fields.append("document_navigation")
        state.save(update_fields=fields)
    _save_native_store(locked, store)
    event_id = _append_event(
        locked, "deck.presentation.updated", actor,
        {"channels": sorted(channels), "snapshot_id": snapshot.id, "slide_key": str(item["key"])},
    )
    notify_session_after_commit(
        locked.id,
        {"protocol": 1, "session_id": locked.id, "version": version, "event_id": event_id,
         "type": "deck.presentation.updated", "payload": {"channels": sorted(channels), "snapshot_id": snapshot.id}},
    )
    return native_deck_presentation_payload(snapshot, store[channels[0]])


def native_deck_entry(session: LiveSession, channel: str) -> dict | None:
    entry = _native_store(session).get(channel)
    if not isinstance(entry, dict):
        return None
    if not isinstance(entry.get("snapshot_id"), int) or not isinstance(entry.get("slide_key"), str):
        return None
    return entry


def native_deck_presentation_payload(snapshot: DeckSnapshot, entry: dict, *, request=None) -> dict:
    slides = snapshot.public_manifest if isinstance(snapshot.public_manifest, list) else []
    index = entry.get("slide_index", 0)
    index = index if isinstance(index, int) and 0 <= index < len(slides) else 0
    payload = {
        "snapshot_id": snapshot.id,
        "title": snapshot.title,
        "theme": snapshot.theme,
        "fingerprint": snapshot.fingerprint,
        "slide_count": len(slides),
        "slide_index": index,
        "slide_key": str(entry.get("slide_key", "")),
        "revision": entry.get("revision"),
        "allow_review": bool(entry.get("allow_review", False)),
    }
    if request is not None:
        session_id = request.resolver_match.kwargs["session_id"]
        payload.update({
            "payload_url": reverse("liveclassroom:api-v1-session-deck-payload", args=[session_id, snapshot.id]),
            "slides_url": reverse("liveclassroom:api-v1-session-deck-slides", args=[session_id, snapshot.id]),
        })
    return payload


def native_deck_state_payload(*, request, session: LiveSession, state: SessionChannelState) -> dict | None:
    entry = native_deck_entry(session, state.channel)
    if entry is None:
        return None
    try:
        snapshot = DeckSnapshot.objects.get(pk=entry["snapshot_id"])
    except DeckSnapshot.DoesNotExist:
        return None
    return native_deck_presentation_payload(snapshot, entry, request=request)
