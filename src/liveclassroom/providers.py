"""Host-neutral content-provider contracts and configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol

from django.conf import settings


class ProviderError(ValueError):
    """Raised when a content-provider reference cannot be parsed or authorized."""


@dataclass(frozen=True)
class ContentReference:
    """Canonical reference stored by an activity instead of a mounted URL."""

    provider: str
    kind: str
    value: dict[str, Any]


class ContentProvider(Protocol):
    """Interface implemented by optional host integrations such as VaultPub."""

    key: str

    def parse_reference(self, url: str, *, request: Any | None = None) -> ContentReference:
        """Parse and validate a user-supplied content URL."""

    def describe(self, reference: ContentReference, *, request: Any | None = None) -> dict[str, Any]:
        """Return safe display metadata and a source fingerprint."""

    def validate_reference(self, reference: ContentReference, *, request: Any | None = None) -> ContentReference:
        """Re-authorize and normalize a stored reference before use."""

    def search(self, query: str, *, request: Any | None = None) -> list[dict[str, Any]]:
        """Return descriptors visible to the current teacher, when supported."""

    def embed_url(self, reference: ContentReference, *, request: Any | None = None) -> str:
        """Return a URL suitable for the authorized display surface."""

    def grant_participant_access(
        self,
        reference: ContentReference,
        *,
        session: Any,
        participant: Any,
        request: Any | None = None,
    ) -> dict[str, Any]:
        """Create a narrowly scoped participant grant for protected content."""

    def revoke_participant_access(self, grant: dict[str, Any]) -> None:
        """Revoke a previously created participant grant."""


class ContentProviderRegistry:
    """Resolve configured content providers without importing host-specific apps."""

    def __init__(self, providers: dict[str, ContentProvider]) -> None:
        self._providers = providers

    def get(self, key: str) -> ContentProvider:
        """Return one configured provider or raise a safe provider error."""
        try:
            return self._providers[key]
        except KeyError as exc:
            raise ProviderError(f"Unknown content provider: {key}") from exc

    def keys(self) -> tuple[str, ...]:
        """Return configured provider keys in deterministic order."""
        return tuple(sorted(self._providers))


def _load_dotted_path(path: str) -> Any:
    module_name, separator, attribute = path.rpartition(".")
    if not separator or not module_name or not attribute:
        raise ProviderError(f"Invalid dotted provider path: {path!r}")
    try:
        return getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise ProviderError(f"Unable to load configured provider: {path!r}") from exc


def content_providers() -> ContentProviderRegistry:
    """Build the provider registry from ``LIVECLASSROOM`` host settings."""
    configured = getattr(settings, "LIVECLASSROOM", {}).get("CONTENT_PROVIDERS", {})
    if not isinstance(configured, dict):
        raise ProviderError("LIVECLASSROOM['CONTENT_PROVIDERS'] must be a mapping")

    providers: dict[str, ContentProvider] = {}
    for key, configured_provider in configured.items():
        provider = (
            _load_dotted_path(configured_provider)
            if isinstance(configured_provider, str)
            else configured_provider
        )
        if isinstance(provider, type):
            provider = provider()
        provider_key = str(getattr(provider, "key", key))
        if provider_key != str(key):
            raise ProviderError(f"Provider key mismatch for {key!r}: {provider_key!r}")
        providers[provider_key] = provider
    return ContentProviderRegistry(providers)
