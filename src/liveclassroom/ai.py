"""Host-neutral contracts for teacher authoring assistance."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol


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
        """Complete a teacher chat without persisting credentials or expanded sources."""


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


def authoring_ai_backends(configured: dict[str, AuthoringAIBackend] | None = None) -> AuthoringAIRegistry:
    """Build an AI registry from an explicit mapping supplied by the host."""
    return AuthoringAIRegistry(dict(configured or {}))
