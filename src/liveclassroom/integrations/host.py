"""Optional host identity, roster, and capability adapters.

The package never imports a host application's models.  Hosts provide a
dotted-path adapter through ``LIVECLASSROOM['HOST_ADAPTER']``; standalone
installations use the small default adapter and existing package permissions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol, runtime_checkable

from liveclassroom.conf import setting


class HostAdapterError(ValueError):
    """A host adapter is malformed or cannot be loaded safely."""


@dataclass(frozen=True)
class HostActor:
    """Minimal host identity passed to adapter capability methods."""

    id: str
    display_name: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("HostActor.id must be non-empty text.")
        if not isinstance(self.display_name, str) or not isinstance(self.fingerprint, str):
            raise ValueError("HostActor display_name and fingerprint must be text.")
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", hashlib.sha256(self.id.encode()).hexdigest())


@dataclass(frozen=True)
class HostCapabilities:
    """Optional declarative capability summary for host diagnostics."""

    author: bool = False
    deliver: bool = False
    view_roster: bool = False
    view_named_responses: bool = False
    grade: bool = False
    view_assessment_results: bool = False
    manage_assessment_results: bool = False
    view_grade_summary: bool = False


@runtime_checkable
class HostAdapter(Protocol):
    def resolve_actor(self, *, request) -> HostActor | None: ...

    def can_author(self, *, actor: HostActor, resource) -> bool: ...

    def can_deliver(self, *, actor: HostActor, resource) -> bool: ...

    def can_view_roster(self, *, actor: HostActor, course_id) -> bool: ...

    def can_view_named_responses(self, *, actor: HostActor, session_id) -> bool: ...

    def can_grade(self, *, actor: HostActor, attempt_id) -> bool: ...

    def can_view_assessment_results(self, *, actor: HostActor, run_id) -> bool: ...

    def can_manage_assessment_results(self, *, actor: HostActor, run_id) -> bool: ...

    def can_view_grade_summary(self, *, actor: HostActor, course_id) -> bool: ...

    def course_summary(self, *, actor: HostActor, course_id) -> dict | None: ...

    def list_roster(self, *, actor: HostActor, course_id) -> list[dict]: ...


_METHODS = (
    "resolve_actor",
    "can_author",
    "can_deliver",
    "can_view_roster",
    "can_view_named_responses",
    "can_grade",
    "course_summary",
    "list_roster",
)


def _as_actor(value: Any) -> HostActor | None:
    if value is None:
        return None
    if isinstance(value, HostActor):
        return value
    if isinstance(value, dict):
        try:
            actor = HostActor(
                id=str(value["id"]),
                display_name=str(value.get("display_name", "")),
                fingerprint=str(value.get("fingerprint", "")),
            )
        except (KeyError, TypeError, ValueError):
            return None
        return actor
    return None


class DefaultHostAdapter:
    """Safe standalone defaults; host-only identity APIs remain denied."""

    capabilities = HostCapabilities(author=True, deliver=True)

    def resolve_actor(self, *, request) -> HostActor | None:
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return None
        user_id = getattr(user, "pk", None)
        if user_id is None:
            return None
        display_name = getattr(user, "get_username", lambda: str(user))()
        return HostActor(id=str(user_id), display_name=str(display_name))

    def can_author(self, *, actor: HostActor, resource) -> bool:
        return bool(actor.id)

    def can_deliver(self, *, actor: HostActor, resource) -> bool:
        return bool(actor.id)

    def can_view_roster(self, *, actor: HostActor, course_id) -> bool:
        return False

    def can_view_named_responses(self, *, actor: HostActor, session_id) -> bool:
        return False

    def can_grade(self, *, actor: HostActor, attempt_id) -> bool:
        return False

    def can_view_assessment_results(self, *, actor: HostActor, run_id) -> bool:
        return False

    def can_manage_assessment_results(self, *, actor: HostActor, run_id) -> bool:
        return False

    def can_view_grade_summary(self, *, actor: HostActor, course_id) -> bool:
        return False

    def course_summary(self, *, actor: HostActor, course_id) -> dict | None:
        return None

    def list_roster(self, *, actor: HostActor, course_id) -> list[dict]:
        return []


def _load(path: str) -> Any:
    module_name, separator, attribute = path.rpartition(".")
    if not separator or not module_name or not attribute:
        raise HostAdapterError(f"Invalid host adapter path: {path!r}")
    try:
        return getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise HostAdapterError(f"Unable to load configured host adapter: {path!r}") from exc


def host_adapter() -> HostAdapter:
    """Load and validate the current adapter on every sensitive action."""
    configured = setting("HOST_ADAPTER")
    adapter = _load(configured) if isinstance(configured, str) else configured
    if adapter is None:
        adapter = DefaultHostAdapter()
    elif isinstance(adapter, type):
        try:
            adapter = adapter()
        except Exception as exc:
            raise HostAdapterError("Unable to instantiate the configured host adapter.") from exc
    missing = [name for name in _METHODS if not callable(getattr(adapter, name, None))]
    if missing:
        raise HostAdapterError(f"Host adapter is missing methods: {', '.join(missing)}.")
    return adapter


def _actor(adapter: HostAdapter, actor=None, *, request=None) -> HostActor | None:
    if request is not None:
        try:
            return _as_actor(adapter.resolve_actor(request=request))
        except Exception:
            return None
    if isinstance(actor, HostActor):
        return actor
    if actor is None or not getattr(actor, "is_authenticated", False) or getattr(actor, "pk", None) is None:
        return None
    display_name = getattr(actor, "get_username", lambda: str(actor))()
    return HostActor(id=str(actor.pk), display_name=str(display_name))


def _decision(adapter: HostAdapter, method: str, *, actor=None, request=None, **kwargs) -> bool:
    host_actor = _actor(adapter, actor, request=request)
    if host_actor is None:
        return False
    try:
        decision = getattr(adapter, method)(actor=host_actor, **kwargs)
    except Exception:
        return False
    return decision if isinstance(decision, bool) else False


def host_can_author(*, actor, resource=None, request=None) -> bool:
    try:
        return _decision(host_adapter(), "can_author", actor=actor, request=request, resource=resource)
    except (HostAdapterError, ValueError, TypeError):
        return False


def host_can_deliver(*, actor, resource=None, request=None) -> bool:
    try:
        return _decision(host_adapter(), "can_deliver", actor=actor, request=request, resource=resource)
    except (HostAdapterError, ValueError, TypeError):
        return False


def host_can_view_roster(*, actor, course_id, request=None, package_allowed=False) -> bool:
    try:
        adapter = host_adapter()
        result = _decision(adapter, "can_view_roster", actor=actor, request=request, course_id=course_id)
        return bool(result or (isinstance(adapter, DefaultHostAdapter) and package_allowed))
    except (HostAdapterError, ValueError, TypeError):
        return False


def host_can_view_named_responses(*, actor, session_id, request=None, package_allowed=False) -> bool:
    try:
        adapter = host_adapter()
        result = _decision(adapter, "can_view_named_responses", actor=actor, request=request, session_id=session_id)
        return bool(result or (isinstance(adapter, DefaultHostAdapter) and package_allowed))
    except (HostAdapterError, ValueError, TypeError):
        return False


def host_can_grade(*, actor, attempt_id, request=None, package_allowed=False) -> bool:
    try:
        adapter = host_adapter()
        result = _decision(adapter, "can_grade", actor=actor, request=request, attempt_id=attempt_id)
        return bool(result or (isinstance(adapter, DefaultHostAdapter) and package_allowed))
    except (HostAdapterError, ValueError, TypeError):
        return False


def _assessment_decision(method: str, *, actor, identifier, field: str, request=None, package_allowed=False) -> bool:
    """Apply an optional assessment hook, failing closed for configured hosts."""
    try:
        adapter = host_adapter()
        result = _decision(adapter, method, actor=actor, request=request, **{field: identifier})
        return bool(result or (isinstance(adapter, DefaultHostAdapter) and package_allowed))
    except (HostAdapterError, ValueError, TypeError):
        return False


def host_can_view_assessment_results(*, actor, run_id, request=None, package_allowed=False) -> bool:
    return _assessment_decision(
        "can_view_assessment_results", actor=actor, identifier=run_id, field="run_id",
        request=request, package_allowed=package_allowed,
    )


def host_can_manage_assessment_results(*, actor, run_id, request=None, package_allowed=False) -> bool:
    return _assessment_decision(
        "can_manage_assessment_results", actor=actor, identifier=run_id, field="run_id",
        request=request, package_allowed=package_allowed,
    )


def host_can_view_grade_summary(*, actor, course_id, request=None, package_allowed=False) -> bool:
    return _assessment_decision(
        "can_view_grade_summary", actor=actor, identifier=course_id, field="course_id",
        request=request, package_allowed=package_allowed,
    )


def host_course_summary(*, actor, course_id, request=None) -> dict | None:
    try:
        adapter = host_adapter()
        host_actor = _actor(adapter, actor, request=request)
        if host_actor is None:
            return None
        result = adapter.course_summary(actor=host_actor, course_id=course_id)
        return result if result is None or isinstance(result, dict) else None
    except (HostAdapterError, ValueError, TypeError):
        return None


def host_list_roster(*, actor, course_id, request=None, package_allowed=False) -> list[dict]:
    if not host_can_view_roster(actor=actor, course_id=course_id, request=request, package_allowed=package_allowed):
        return []
    try:
        adapter = host_adapter()
        host_actor = _actor(adapter, actor, request=request)
        if host_actor is None:
            return []
        rows = adapter.list_roster(actor=host_actor, course_id=course_id)
    except (HostAdapterError, ValueError, TypeError):
        return []
    if not isinstance(rows, list):
        return []
    safe = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not isinstance(row.get("id"), (str, int)) or not isinstance(row.get("display_name", ""), str):
            continue
        safe.append(
            {
                "id": str(row["id"]),
                "display_name": row.get("display_name", ""),
                "fingerprint": row.get("fingerprint")
                if isinstance(row.get("fingerprint"), str)
                else hashlib.sha256(str(row["id"]).encode()).hexdigest(),
            }
        )
    return safe


__all__ = [
    "DefaultHostAdapter",
    "HostActor",
    "HostAdapter",
    "HostAdapterError",
    "HostCapabilities",
    "host_adapter",
    "host_can_author",
    "host_can_deliver",
    "host_can_grade",
    "host_can_manage_assessment_results",
    "host_can_view_assessment_results",
    "host_can_view_grade_summary",
    "host_can_view_named_responses",
    "host_can_view_roster",
    "host_course_summary",
    "host_list_roster",
]
