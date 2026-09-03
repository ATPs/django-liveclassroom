"""Host-neutral contracts for teacher authoring assistance."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol

from django.conf import settings


class AuthoringAIError(RuntimeError):
    """Raised when an authoring provider cannot complete a request safely."""


@dataclass(frozen=True)
class AIModel:
    """Safe model metadata exposed to an authorized teacher."""

    identifier: str
    label: str


@dataclass(frozen=True)
class AIMessage:
    """One teacher or assistant message in a non-secret authoring conversation."""

    role: str
    content: str


class AuthoringAIBackend(Protocol):
    """Interface for host-managed or explicitly selected custom AI providers."""

    key: str

    def list_models(self, *, request: Any | None = None) -> Iterable[AIModel]:
        """Return models the current teacher may select."""

    def complete(
        self,
        messages: Iterable[AIMessage],
        *,
        model: str,
        request: Any | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> AIMessage:
        """Complete a teacher chat without persisting credentials or expanded sources.

        Hosts that need transient custom-provider settings may read the
        request-local ``liveclassroom_ai_options`` attribute during this call;
        the package never serializes or logs that value.
        """


class AuthoringAIRegistry:
    """Resolve configured AI backends without binding the package to a vendor."""

    def __init__(self, backends: dict[str, AuthoringAIBackend]) -> None:
        self._backends = backends

    def get(self, key: str) -> AuthoringAIBackend:
        """Return one backend or raise a safe configuration error."""
        try:
            return self._backends[key]
        except KeyError as exc:
            raise AuthoringAIError(f"Unknown authoring AI backend: {key}") from exc

    def keys(self) -> tuple[str, ...]:
        """Return configured backend keys in deterministic order."""
        return tuple(sorted(self._backends))


def _load_backend(path: str) -> Any:
    module_name, separator, attribute = path.rpartition(".")
    if not separator or not module_name or not attribute:
        raise AuthoringAIError(f"Invalid authoring AI backend path: {path!r}")
    try:
        return getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise AuthoringAIError(f"Unable to load authoring AI backend: {path!r}") from exc


def authoring_ai_backends(
    configured: dict[str, AuthoringAIBackend] | None = None,
) -> AuthoringAIRegistry:
    """Build a registry from explicit backends or host ``LIVECLASSROOM`` settings."""
    if configured is None:
        configured = getattr(settings, "LIVECLASSROOM", {}).get("AI_BACKENDS", {})
    if not isinstance(configured, dict):
        raise AuthoringAIError("LIVECLASSROOM['AI_BACKENDS'] must be a mapping")

    backends: dict[str, AuthoringAIBackend] = {}
    for key, configured_backend in configured.items():
        backend = _load_backend(configured_backend) if isinstance(configured_backend, str) else configured_backend
        if isinstance(backend, type):
            backend = backend()
        backend_key = str(getattr(backend, "key", key))
        if backend_key != str(key):
            raise AuthoringAIError(f"Authoring AI backend key mismatch for {key!r}: {backend_key!r}")
        backends[backend_key] = backend
    return AuthoringAIRegistry(backends)
