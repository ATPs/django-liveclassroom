"""Server-authoritative navigation for independent assessment attempts.

The browser may render a smaller set of controls for a forward-only exam, but
the attempt's cursor and locked answers live in the database.  Every mutation
therefore goes through this module (or the write gate used by autosave).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction

from liveclassroom.models import AssessmentAttempt, AssessmentAttemptItem

from .assessment_timing import server_now
from .classroom import ClassroomError

NAVIGATION_MODES = frozenset({"free", "forward_only"})


class AttemptNavigationConflict(ClassroomError):
    """A navigation command cannot be applied to the persisted cursor."""

    status_code = 409

    def __init__(self, message: str, *, code: str = "stale_navigation", current=None):
        super().__init__(message)
        self.code = code
        self.current = current


def _item_uuid(value: Any) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ClassroomError("item_key must be a UUID.") from exc


def _version(value: Any, field: str = "navigation_version") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ClassroomError(f"{field} must be a positive integer.")
    return value


def _locked_keys(attempt: AssessmentAttempt) -> list[str]:
    value = attempt.locked_item_keys
    if not isinstance(value, list):
        raise ClassroomError("The attempt navigation state is invalid.")
    result = []
    for key in value:
        try:
            normalized = str(UUID(str(key)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ClassroomError("The attempt navigation state is invalid.") from exc
        if normalized not in result:
            result.append(normalized)
    return result


def _mode(attempt: AssessmentAttempt) -> str:
    mode = attempt.navigation_mode
    if mode not in NAVIGATION_MODES:
        raise ClassroomError("The attempt navigation mode is invalid.")
    return mode


def _items(attempt: AssessmentAttempt) -> list[AssessmentAttemptItem]:
    return list(attempt.items.all().order_by("position", "id"))


def _current_item(items: list[AssessmentAttemptItem], attempt: AssessmentAttempt) -> AssessmentAttemptItem:
    current = next((item for item in items if item.position == attempt.current_item_position), None)
    if current is None:
        raise ClassroomError("The attempt navigation state is invalid.")
    return current


def _payload(attempt: AssessmentAttempt, items: list[AssessmentAttemptItem] | None = None) -> dict[str, Any]:
    items = _items(attempt) if items is None else items
    current = _current_item(items, attempt)
    locked = _locked_keys(attempt)
    return {
        "mode": _mode(attempt),
        "current_item_key": str(current.key),
        "current_item_position": current.position,
        "highest_accessible_item_position": attempt.highest_accessible_item_position,
        "locked_item_keys": locked,
        "navigation_version": attempt.navigation_version,
        "can_go_previous": attempt.current_item_position > 1,
        "can_go_next": attempt.current_item_position < len(items),
    }


def navigation_payload(attempt: AssessmentAttempt) -> dict[str, Any]:
    """Return the persisted cursor in a client-safe shape."""
    return _payload(attempt)


def _check_actor(actor, attempt: AssessmentAttempt) -> None:
    if not getattr(actor, "is_authenticated", False):
        raise ClassroomError("Authentication required.")
    if attempt.user_id != actor.pk:
        raise ClassroomError("You do not have permission to navigate this attempt.")
    from .attempts import _can_access

    if not _can_access(actor, attempt.run):
        raise ClassroomError("You do not have access to this assessment.")


def _check_open(attempt: AssessmentAttempt, now: datetime | None) -> datetime:
    current = server_now(now)
    if attempt.status != AssessmentAttempt.Status.IN_PROGRESS:
        raise AttemptNavigationConflict("This attempt is already finalized.", code="attempt_closed")
    if attempt.deadline_at is not None and current >= attempt.deadline_at:
        raise AttemptNavigationConflict("The answer deadline has passed.", code="attempt_closed")
    return current


def assert_item_writable(*, attempt: AssessmentAttempt, item: AssessmentAttemptItem) -> None:
    """Reject autosaves for future or locked items in a forward-only attempt."""
    if item.attempt_id != attempt.pk:
        raise ClassroomError("The assessment item was not found.")
    if _mode(attempt) != "forward_only":
        return
    key = str(item.key)
    if key in _locked_keys(attempt):
        raise AttemptNavigationConflict(
            "This answer is locked after advancing.", code="item_locked", current=_payload(attempt)
        )
    if item.position > attempt.highest_accessible_item_position:
        raise AttemptNavigationConflict(
            "This question is not available yet.", code="item_not_accessible", current=_payload(attempt)
        )


@transaction.atomic
def navigate_attempt(
    *,
    actor,
    attempt: AssessmentAttempt,
    item_key,
    expected_navigation_version,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Move a student's cursor while enforcing the persisted forward-only gate.

    Reaching a previously answered item is allowed for review, but its answer
    remains read-only once it has been locked by an advance operation.
    """
    item_uuid = _item_uuid(item_key)
    expected = _version(expected_navigation_version)
    locked = AssessmentAttempt.objects.select_for_update().select_related("run").get(pk=attempt.pk)
    _check_actor(actor, locked)
    _check_open(locked, now)
    items = _items(locked)
    target = next((item for item in items if item.key == item_uuid), None)
    if target is None:
        raise ClassroomError("The assessment item was not found.")
    if expected != locked.navigation_version:
        raise AttemptNavigationConflict(
            "The attempt navigation changed; refresh before continuing.",
            current=_payload(locked, items),
        )
    mode = _mode(locked)
    if mode == "forward_only" and target.position > locked.highest_accessible_item_position:
        raise AttemptNavigationConflict(
            "This question is not available yet.", code="item_not_accessible", current=_payload(locked, items)
        )
    if target.position != locked.current_item_position:
        locked.current_item_position = target.position
        locked.navigation_version += 1
        locked.save(update_fields=["current_item_position", "navigation_version"])
    result = _payload(locked, items)
    result["read_only"] = mode == "forward_only" and str(target.key) in _locked_keys(locked)
    return result


@transaction.atomic
def save_and_advance_attempt(
    *,
    actor,
    attempt: AssessmentAttempt,
    current_item_key,
    expected_navigation_version,
    answer=None,
    expected_answer_version=None,
    answer_request_id=None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist the current answer and then advance the durable cursor.

    ``answer`` may be omitted when the item has already been saved.  When an
    answer is provided, both its optimistic version and request ID are
    required, so a retry cannot advance a stale tab or lose a save.
    """
    item_uuid = _item_uuid(current_item_key)
    expected_nav = _version(expected_navigation_version)
    locked = AssessmentAttempt.objects.select_for_update().select_related("run").get(pk=attempt.pk)
    _check_actor(actor, locked)
    current_now = _check_open(locked, now)
    items = _items(locked)
    current = next((item for item in items if item.key == item_uuid), None)
    if current is None:
        raise ClassroomError("The assessment item was not found.")
    if expected_nav != locked.navigation_version:
        raise AttemptNavigationConflict(
            "The attempt navigation changed; refresh before continuing.", current=_payload(locked, items)
        )
    if current.position != locked.current_item_position:
        raise AttemptNavigationConflict(
            "Advance the currently open question first.", code="stale_navigation", current=_payload(locked, items)
        )
    if answer is not None:
        if expected_answer_version is None or answer_request_id is None:
            raise ClassroomError("expected_answer_version and answer_request_id are required with answer.")
        from .attempts import save_attempt_answer

        revision = save_attempt_answer(
            actor=actor,
            attempt=locked,
            item_key=current.key,
            answer=answer,
            expected_version=expected_answer_version,
            request_id=answer_request_id,
            now=current_now,
        )
    else:
        revision = current.answer_revisions.order_by("-version").first()
    mode = _mode(locked)
    if mode == "forward_only":
        locked_keys = _locked_keys(locked)
        if revision is not None and str(current.key) not in locked_keys:
            locked_keys.append(str(current.key))
            locked.locked_item_keys = locked_keys
        next_item = next((item for item in items if item.position > current.position), None)
        if next_item is not None:
            locked.current_item_position = next_item.position
            locked.highest_accessible_item_position = max(
                locked.highest_accessible_item_position, next_item.position
            )
        locked.navigation_version += 1
        fields = ["current_item_position", "highest_accessible_item_position", "navigation_version"]
        if revision is not None:
            fields.append("locked_item_keys")
        locked.save(update_fields=fields)
    else:
        # Free navigation still persists a cursor, which lets reconnects return
        # to the last opened question without restricting answer writes.
        next_item = next((item for item in items if item.position > current.position), None)
        if next_item is not None:
            locked.current_item_position = next_item.position
            locked.navigation_version += 1
            locked.save(update_fields=["current_item_position", "navigation_version"])
    result = _payload(locked, items)
    result["advanced"] = next_item is not None
    if revision is not None:
        result["answer"] = {
            "item_key": str(revision.item.key),
            "version": revision.version,
            "answer": deepcopy(revision.answer),
        }
    return result


# A short alias makes call sites read naturally while retaining the explicit
# save-before-advance name for API and test consumers.
advance_attempt = save_and_advance_attempt


__all__ = [
    "NAVIGATION_MODES",
    "AttemptNavigationConflict",
    "advance_attempt",
    "assert_item_writable",
    "navigate_attempt",
    "navigation_payload",
    "save_and_advance_attempt",
]
