"""Small, versioned contracts for optional LiveClassroom extensions.

This module contains metadata and validation only.  It does not import a host
application, an AI vendor, or a frontend package.  Optional implementations
are loaded only when a host explicitly lists them in ``LIVECLASSROOM``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Protocol, TypeVar, runtime_checkable

from django.conf import settings
from django.http import HttpResponseBase

from .providers import ContentReference

PROTOCOL_VERSION = 1
SUPPORTED_PROTOCOL_VERSIONS = frozenset({PROTOCOL_VERSION})
NAMESPACED_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)+$")
FRONTEND_SURFACES = ("editor", "student_renderer", "display_renderer", "analytics")

# These are intentionally finite.  A provider cannot acquire an undeclared
# privilege by inventing a capability name and hoping a future host interprets
# it broadly.
SAFE_CAPABILITIES = frozenset(
    {
        # Existing ActivityType capability names remain valid when adapted.
        "aggregate",
        "activity.validate",
        "activity.score",
        "choices",
        "content.read",
        "content",
        "correctness",
        "document.render",
        "export.read",
        "frontend.manifest",
        "grading.score",
        "grading.validate",
        "host.authorize",
        "host.identity",
        "ai.complete",
        "ai.job",
        "legacy",
        "manual",
        "numeric",
        "ranking",
        "rating",
        "slides.read",
        "text",
        "timed",
    }
)


class ExtensionError(RuntimeError):
    """Base class for concise, safe extension failures."""


class ExtensionConfigurationError(ExtensionError):
    """Raised when an extension declaration cannot be accepted."""


class ExtensionAuthorizationError(ExtensionError):
    """Raised when a caller did not provide an affirmative authorization."""


class ExtensionInvocationError(ExtensionError):
    """Raised when an extension fails or returns an unsafe payload."""


@runtime_checkable
class DocumentExtension(Protocol):
    """Render one already-authorized content reference."""

    key: str

    def render(self, request: Any, reference: ContentReference, *, mode: str) -> HttpResponseBase: ...


@runtime_checkable
class GradingExtension(Protocol):
    """Validate a definition and score one answer."""

    key: str

    def validate(self, definition: dict[str, Any]) -> dict[str, Any]: ...

    def score(self, answer: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class ExportExtension(Protocol):
    """Produce an authorized, safe projection of one package object."""

    key: str

    def export(self, *, actor: Any, object_kind: str, object_id: int) -> dict[str, Any]: ...


@runtime_checkable
class AIJobWorker(Protocol):
    """Optional queue adapter for an existing authoring job."""

    key: str

    def enqueue(self, *, actor: Any, request: Any, job: Mapping[str, Any]) -> dict[str, Any]: ...

    def run(self, *, job: Mapping[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class SlideProvider(Protocol):
    """The slide-capable subset of the existing content-provider contract."""

    key: str

    def parse_reference(self, url: str, *, request: Any | None = None) -> ContentReference: ...

    def describe(self, reference: ContentReference, *, request: Any | None = None) -> dict[str, Any]: ...

    def validate_reference(
        self, reference: ContentReference, *, request: Any | None = None
    ) -> ContentReference: ...

    def embed_url(self, reference: ContentReference, *, request: Any | None = None) -> str: ...


@dataclass(frozen=True)
class ExtensionMetadata:
    """Common version and capability metadata for one registration."""

    key: str
    protocol_version: int = PROTOCOL_VERSION
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        _validate_metadata(self.key, self.protocol_version, self.capabilities)


@dataclass(frozen=True)
class ExtensionRegistration:
    """Generic registration record used by the deterministic loader."""

    extension: Any
    key: str | None = None
    protocol_version: int | None = None
    capabilities: frozenset[str] | None = None
    kind: str = "extension"

    def metadata(self) -> ExtensionMetadata:
        extension_key = self.key if self.key is not None else getattr(self.extension, "key", None)
        version = self.protocol_version
        if version is None:
            version = getattr(self.extension, "protocol_version", None)
        capabilities = self.capabilities
        if capabilities is None:
            capabilities = getattr(self.extension, "capabilities", None)
        if version is None:
            raise ExtensionConfigurationError(f"Extension {extension_key!r} must declare protocol_version.")
        if capabilities is None:
            raise ExtensionConfigurationError(f"Extension {extension_key!r} must declare capabilities.")
        return ExtensionMetadata(extension_key, version, _capability_set(capabilities))


@dataclass(frozen=True)
class ActivityTypeRegistration:
    """Versioned adapter for the existing :class:`ActivityType` registry."""

    activity_type: Any
    key: str | None = None
    protocol_version: int = PROTOCOL_VERSION
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.key is None:
            object.__setattr__(self, "key", str(getattr(self.activity_type, "key", "")))

    @property
    def extension(self) -> Any:
        return self.activity_type


@dataclass(frozen=True)
class FrontendManifestRegistration:
    key: str
    manifest: Mapping[str, str]
    protocol_version: int = PROTOCOL_VERSION
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"frontend.manifest"}))

    @property
    def extension(self) -> FrontendManifestRegistration:
        return self


@dataclass(frozen=True)
class AIBackendRegistration:
    backend: Any
    key: str | None = None
    protocol_version: int = PROTOCOL_VERSION
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.key is None:
            object.__setattr__(self, "key", str(getattr(self.backend, "key", "")))

    @property
    def extension(self) -> Any:
        return self.backend


@dataclass(frozen=True)
class AIJobWorkerRegistration:
    worker: Any
    key: str | None = None
    protocol_version: int = PROTOCOL_VERSION
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"ai.job"}))

    def __post_init__(self) -> None:
        if self.key is None:
            object.__setattr__(self, "key", str(getattr(self.worker, "key", "")))

    @property
    def extension(self) -> Any:
        return self.worker


@dataclass(frozen=True)
class HostAdapterRegistration:
    adapter: Any
    key: str | None = None
    protocol_version: int = PROTOCOL_VERSION
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"host.authorize", "host.identity"}))

    def __post_init__(self) -> None:
        if self.key is None:
            object.__setattr__(self, "key", str(getattr(self.adapter, "key", "")))

    @property
    def extension(self) -> Any:
        return self.adapter


@dataclass(frozen=True)
class SlideProviderRegistration:
    provider: Any
    key: str | None = None
    protocol_version: int = PROTOCOL_VERSION
    capabilities: frozenset[str] = field(default_factory=lambda: frozenset({"slides.read"}))

    def __post_init__(self) -> None:
        if self.key is None:
            object.__setattr__(self, "key", str(getattr(self.provider, "key", "")))

    @property
    def extension(self) -> Any:
        return self.provider


# Common naming variants make the records easy to discover while retaining one
# implementation and one serialized shape.
ActivityTypeRecord = ActivityTypeRegistration
FrontendManifestRecord = FrontendManifestRegistration
AIBackendRecord = AIBackendRegistration
AIJobWorkerRecord = AIJobWorkerRegistration
HostAdapterRecord = HostAdapterRegistration
SlideProviderRecord = SlideProviderRegistration


T = TypeVar("T")


class ExtensionRegistry[T]:
    """Deterministic key registry with fail-closed validation."""

    def __init__(
        self,
        *,
        kind: str = "extension",
        required_methods: Iterable[str] = (),
        supported_versions: Iterable[int] = SUPPORTED_PROTOCOL_VERSIONS,
    ) -> None:
        self.kind = kind
        self.required_methods = tuple(required_methods)
        self.supported_versions = frozenset(supported_versions)
        if not self.supported_versions or any(
            not isinstance(item, int) or isinstance(item, bool) for item in self.supported_versions
        ):
            raise ExtensionConfigurationError("supported_versions must contain integer protocol versions.")
        self._entries: dict[str, ExtensionRegistration] = {}

    def register(
        self,
        value: T | ExtensionRegistration | str,
        extension: T | None = None,
        *,
        key: str | None = None,
        protocol_version: int | None = None,
        capabilities: Iterable[str] | None = None,
        replace: bool = False,
    ) -> ExtensionRegistration:
        if extension is not None:
            if not isinstance(value, str):
                raise ExtensionConfigurationError("A positional extension key must be text.")
            if key is not None:
                raise ExtensionConfigurationError("Extension key was supplied twice.")
            key = value
            value = extension
        if key is not None or protocol_version is not None or capabilities is not None:
            value = ExtensionRegistration(
                extension=value,
                key=key,
                protocol_version=protocol_version,
                capabilities=None if capabilities is None else _capability_set(capabilities),
                kind=self.kind,
            )
        record = value if isinstance(value, ExtensionRegistration) else _as_registration(value, kind=self.kind)
        metadata = record.metadata()
        extension = record.extension
        if metadata.protocol_version not in self.supported_versions:
            raise ExtensionConfigurationError(
                f"Extension {metadata.key!r} uses unsupported protocol version {metadata.protocol_version}."
            )
        missing = [name for name in self.required_methods if not callable(getattr(extension, name, None))]
        if missing:
            raise ExtensionConfigurationError(
                f"Extension {metadata.key!r} is missing methods: {', '.join(missing)}."
            )
        if metadata.key in self._entries and not replace:
            raise ExtensionConfigurationError(f"Duplicate extension key: {metadata.key!r}.")
        # Retain normalized metadata so a mutable or unusual source object
        # cannot change registration semantics after loading.
        normalized = ExtensionRegistration(
            extension=extension,
            key=metadata.key,
            protocol_version=metadata.protocol_version,
            capabilities=metadata.capabilities,
            kind=record.kind,
        )
        self._entries[metadata.key] = normalized
        return normalized

    def register_many(self, values: Iterable[T | ExtensionRegistration]) -> tuple[ExtensionRegistration, ...]:
        added = []
        for value in values:
            added.append(self.register(value))
        return tuple(added)

    def get(self, key: str) -> T:
        try:
            return self._entries[key].extension
        except KeyError as exc:
            raise ExtensionConfigurationError(f"Unknown {self.kind} extension: {key!r}.") from exc

    def record(self, key: str) -> ExtensionRegistration:
        try:
            return self._entries[key]
        except KeyError as exc:
            raise ExtensionConfigurationError(f"Unknown {self.kind} extension: {key!r}.") from exc

    def all(self) -> tuple[T, ...]:
        return tuple(self._entries[key].extension for key in sorted(self._entries))

    def records(self) -> tuple[ExtensionRegistration, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def unregister(self, key: str) -> None:
        self._entries.pop(key, None)


def _validate_metadata(key: Any, version: Any, capabilities: Any) -> None:
    if not isinstance(key, str) or not NAMESPACED_KEY_PATTERN.fullmatch(key):
        raise ExtensionConfigurationError(
            f"Extension key {key!r} must be a stable namespaced key such as 'example.liveclassroom.notes'."
        )
    if isinstance(version, bool) or not isinstance(version, int) or version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ExtensionConfigurationError(f"Extension {key!r} uses unsupported protocol version {version!r}.")
    _capability_set(capabilities)


def _capability_set(value: Any) -> frozenset[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise ExtensionConfigurationError("Extension capabilities must be a collection of safe names.")
    result = frozenset(value)
    if any(not isinstance(item, str) or not item or item not in SAFE_CAPABILITIES for item in result):
        raise ExtensionConfigurationError("Extension declares an unsupported capability.")
    return result


def _as_registration(value: Any, *, kind: str) -> ExtensionRegistration:
    if isinstance(value, ExtensionRegistration):
        return value
    # Typed records expose the wrapped implementation through ``extension``.
    # Copy the fields rather than registering the record object itself.
    if hasattr(value, "extension") and hasattr(value, "key"):
        return ExtensionRegistration(
            extension=value.extension,
            key=value.key,
            protocol_version=getattr(value, "protocol_version", None),
            capabilities=getattr(value, "capabilities", None),
            kind=kind,
        )
    return ExtensionRegistration(extension=value, kind=kind)


def _load_dotted(path: str) -> Any:
    if not isinstance(path, str):
        raise ExtensionConfigurationError("Configured extension paths must be strings.")
    module_name, separator, attribute = path.partition(":")
    if not separator:
        module_name, separator, attribute = path.rpartition(".")
    if not separator or not module_name or not attribute:
        raise ExtensionConfigurationError(f"Invalid extension path: {path!r}.")
    try:
        value = getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise ExtensionConfigurationError(f"Unable to load configured extension: {path!r}.") from exc
    if isinstance(value, type):
        try:
            value = value()
        except Exception as exc:
            raise ExtensionConfigurationError("Unable to instantiate configured extension.") from exc
    return value


def load_extensions(
    configured: Mapping[str, Any] | Iterable[Any] | None = None,
    *,
    kind: str = "extension",
    required_methods: Iterable[str] = (),
) -> ExtensionRegistry[Any]:
    """Load explicitly configured extensions in sorted, deterministic order.

    A mapping's values may be extension instances, registration records, dotted
    paths, or lists of those values.  Mapping keys are only labels; the
    extension's own stable key is authoritative.
    """
    if configured is None:
        configured = getattr(settings, "LIVECLASSROOM", {}).get("EXTENSIONS", {})
    if isinstance(configured, Mapping):
        values: list[Any] = []
        for label in sorted(configured, key=str):
            value = configured[label]
            values.extend(value if isinstance(value, (list, tuple)) else [value])
    elif isinstance(configured, (str, bytes)) or not isinstance(configured, Iterable):
        raise ExtensionConfigurationError("LIVECLASSROOM['EXTENSIONS'] must be a mapping or sequence.")
    else:
        values = list(configured)
    registry: ExtensionRegistry[Any] = ExtensionRegistry(kind=kind, required_methods=required_methods)
    for value in values:
        loaded = _load_dotted(value) if isinstance(value, str) else value
        try:
            registry.register(loaded)
        except ExtensionError:
            raise
        except Exception as exc:
            raise ExtensionConfigurationError("Unable to register configured extension.") from exc
    return registry


def adapt_activity_type(
    activity_type: Any,
    *,
    protocol_version: int = PROTOCOL_VERSION,
    capabilities: Iterable[str] | None = None,
) -> ActivityTypeRegistration:
    """Adapt an existing ``ActivityType`` without changing its registry."""
    if not callable(getattr(activity_type, "validate", None)) or not callable(getattr(activity_type, "score", None)):
        raise ExtensionConfigurationError("Activity type must provide validate and score methods.")
    declared = capabilities if capabilities is not None else getattr(activity_type, "capabilities", ())
    _validate_metadata(getattr(activity_type, "key", None), protocol_version, _capability_set(declared))
    return ActivityTypeRegistration(
        activity_type,
        protocol_version=protocol_version,
        capabilities=_capability_set(declared),
    )


def adapt_frontend_manifest(
    key: str,
    manifest: Mapping[str, str],
    *,
    protocol_version: int = PROTOCOL_VERSION,
    capabilities: Iterable[str] | None = None,
) -> FrontendManifestRegistration:
    if not isinstance(manifest, Mapping) or any(
        not isinstance(manifest.get(surface), str) or not manifest.get(surface, "").strip()
        for surface in FRONTEND_SURFACES
    ):
        raise ExtensionConfigurationError(
            f"Frontend manifest must define non-empty surfaces: {', '.join(FRONTEND_SURFACES)}."
        )
    declared = capabilities if capabilities is not None else {"frontend.manifest"}
    _validate_metadata(key, protocol_version, _capability_set(declared))
    return FrontendManifestRegistration(key, dict(manifest), protocol_version, _capability_set(declared))


def adapt_ai_backend(
    backend: Any,
    *,
    protocol_version: int = PROTOCOL_VERSION,
    capabilities: Iterable[str] | None = None,
) -> AIBackendRegistration:
    if not callable(getattr(backend, "list_models", None)) or not callable(getattr(backend, "complete", None)):
        raise ExtensionConfigurationError("AI backend must provide list_models and complete methods.")
    declared = capabilities if capabilities is not None else {"ai.complete"}
    _validate_metadata(getattr(backend, "key", None), protocol_version, _capability_set(declared))
    return AIBackendRegistration(backend, protocol_version=protocol_version, capabilities=_capability_set(declared))


def adapt_ai_job_worker(
    worker: Any,
    *,
    protocol_version: int = PROTOCOL_VERSION,
    capabilities: Iterable[str] | None = None,
) -> AIJobWorkerRegistration:
    if not callable(getattr(worker, "enqueue", None)) or not callable(getattr(worker, "run", None)):
        raise ExtensionConfigurationError("AI job worker must provide enqueue and run methods.")
    declared = capabilities if capabilities is not None else {"ai.job"}
    _validate_metadata(getattr(worker, "key", None), protocol_version, _capability_set(declared))
    return AIJobWorkerRegistration(worker, protocol_version=protocol_version, capabilities=_capability_set(declared))


def adapt_host_adapter(
    adapter: Any,
    *,
    protocol_version: int = PROTOCOL_VERSION,
    capabilities: Iterable[str] | None = None,
) -> HostAdapterRegistration:
    required = (
        "resolve_actor",
        "can_author",
        "can_deliver",
        "can_view_roster",
        "can_view_named_responses",
        "can_grade",
        "course_summary",
        "list_roster",
    )
    missing = [name for name in required if not callable(getattr(adapter, name, None))]
    if missing:
        raise ExtensionConfigurationError(f"Host adapter is missing methods: {', '.join(missing)}.")
    declared = capabilities if capabilities is not None else {"host.authorize", "host.identity"}
    _validate_metadata(getattr(adapter, "key", None), protocol_version, _capability_set(declared))
    return HostAdapterRegistration(adapter, protocol_version=protocol_version, capabilities=_capability_set(declared))


def adapt_slide_provider(
    provider: Any,
    *,
    protocol_version: int = PROTOCOL_VERSION,
    capabilities: Iterable[str] | None = None,
) -> SlideProviderRegistration:
    required = ("parse_reference", "describe", "validate_reference", "embed_url")
    missing = [name for name in required if not callable(getattr(provider, name, None))]
    if missing:
        raise ExtensionConfigurationError(f"Slide provider is missing methods: {', '.join(missing)}.")
    declared = capabilities if capabilities is not None else {"slides.read"}
    _validate_metadata(getattr(provider, "key", None), protocol_version, _capability_set(declared))
    return SlideProviderRegistration(
        provider,
        protocol_version=protocol_version,
        capabilities=_capability_set(declared),
    )


def _require_authorization(*, actor: Any, request: Any, resource: Any, authorize: Any) -> None:
    if actor is None or resource is None or not callable(authorize):
        raise ExtensionAuthorizationError("Extension access was denied.")
    try:
        decision = authorize(actor=actor, request=request, resource=resource)
    except Exception as exc:
        raise ExtensionAuthorizationError("Extension access was denied.") from exc
    if decision is not True:
        raise ExtensionAuthorizationError("Extension access was denied.")


def _safe_value(value: Any, *, depth: int = 0) -> bool:
    if depth > 16 or value is None or isinstance(value, (str, int, float, bool)):
        return depth <= 16 and (not isinstance(value, float) or math.isfinite(value))
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or any(
                token in key.casefold() for token in ("credential", "secret", "token", "reasoning", "traceback")
            ):
                return False
            if not _safe_value(item, depth=depth + 1):
                return False
        return True
    if isinstance(value, (list, tuple)):
        return all(_safe_value(item, depth=depth + 1) for item in value)
    return False


def _safe_payload(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not _safe_value(value):
        raise ExtensionInvocationError(f"Extension returned an unsafe {label}.")
    return value


def _require_extension_capability(extension: Any, capability: str) -> None:
    try:
        capabilities = _capability_set(getattr(extension, "capabilities", None))
    except ExtensionConfigurationError as exc:
        raise ExtensionAuthorizationError("Extension capability was not granted.") from exc
    if capability not in capabilities:
        raise ExtensionAuthorizationError("Extension capability was not granted.")


def invoke_document(
    extension: DocumentExtension,
    *,
    request: Any,
    reference: ContentReference,
    mode: str,
    actor: Any,
    resource: Any | None = None,
    authorize: Any,
) -> HttpResponseBase:
    _require_extension_capability(extension, "document.render")
    _require_authorization(
        actor=actor,
        request=request,
        resource=resource if resource is not None else reference,
        authorize=authorize,
    )
    try:
        response = extension.render(request, reference, mode=mode)
    except Exception as exc:
        raise ExtensionInvocationError("Document extension failed safely.") from exc
    if not isinstance(response, HttpResponseBase):
        raise ExtensionInvocationError("Document extension returned an invalid response.")
    return response


def invoke_grading_validate(
    extension: GradingExtension,
    definition: dict[str, Any],
    *,
    actor: Any,
    request: Any = None,
    resource: Any | None = None,
    authorize: Any,
) -> dict[str, Any]:
    _require_extension_capability(extension, "grading.validate")
    _require_authorization(
        actor=actor,
        request=request,
        resource=resource if resource is not None else definition,
        authorize=authorize,
    )
    if not isinstance(definition, dict):
        raise ExtensionInvocationError("Grading definition must be an object.")
    try:
        return _safe_payload(extension.validate(definition), label="grading definition")
    except ExtensionError:
        raise
    except Exception as exc:
        raise ExtensionInvocationError("Grading extension failed safely.") from exc


def invoke_grading_score(
    extension: GradingExtension,
    answer: dict[str, Any],
    definition: dict[str, Any],
    *,
    actor: Any,
    request: Any = None,
    resource: Any | None = None,
    authorize: Any,
) -> dict[str, Any]:
    _require_extension_capability(extension, "grading.score")
    _require_authorization(
        actor=actor,
        request=request,
        resource=resource if resource is not None else definition,
        authorize=authorize,
    )
    if not isinstance(answer, dict) or not isinstance(definition, dict):
        raise ExtensionInvocationError("Grading answer and definition must be objects.")
    try:
        return _safe_payload(extension.score(answer, definition), label="grading result")
    except ExtensionError:
        raise
    except Exception as exc:
        raise ExtensionInvocationError("Grading extension failed safely.") from exc


def invoke_export(
    extension: ExportExtension,
    *,
    actor: Any,
    object_kind: str,
    object_id: int,
    request: Any = None,
    resource: Any | None = None,
    authorize: Any,
) -> dict[str, Any]:
    _require_extension_capability(extension, "export.read")
    _require_authorization(
        actor=actor,
        request=request,
        resource=resource if resource is not None else (object_kind, object_id),
        authorize=authorize,
    )
    if (
        not isinstance(object_kind, str)
        or not object_kind.strip()
        or isinstance(object_id, bool)
        or not isinstance(object_id, int)
        or object_id <= 0
    ):
        raise ExtensionInvocationError("Export object identity is invalid.")
    try:
        return _safe_payload(
            extension.export(actor=actor, object_kind=object_kind, object_id=object_id), label="export"
        )
    except ExtensionError:
        raise
    except Exception as exc:
        raise ExtensionInvocationError("Export extension failed safely.") from exc


def require_capability(record: ExtensionRegistration, capability: str) -> None:
    """Fail closed when a caller asks for an undeclared operation."""
    if capability not in record.metadata().capabilities:
        raise ExtensionAuthorizationError("Extension capability was not granted.")


__all__ = [
    "AIBackendRecord",
    "AIBackendRegistration",
    "AIJobWorker",
    "AIJobWorkerRecord",
    "AIJobWorkerRegistration",
    "ActivityTypeRecord",
    "ActivityTypeRegistration",
    "DocumentExtension",
    "ExportExtension",
    "ExtensionAuthorizationError",
    "ExtensionConfigurationError",
    "ExtensionError",
    "ExtensionInvocationError",
    "ExtensionMetadata",
    "ExtensionRegistration",
    "ExtensionRegistry",
    "FrontendManifestRecord",
    "FrontendManifestRegistration",
    "GradingExtension",
    "HostAdapterRecord",
    "HostAdapterRegistration",
    "NAMESPACED_KEY_PATTERN",
    "PROTOCOL_VERSION",
    "SAFE_CAPABILITIES",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "SlideProvider",
    "SlideProviderRecord",
    "SlideProviderRegistration",
    "adapt_activity_type",
    "adapt_ai_backend",
    "adapt_ai_job_worker",
    "adapt_frontend_manifest",
    "adapt_host_adapter",
    "adapt_slide_provider",
    "invoke_document",
    "invoke_export",
    "invoke_grading_score",
    "invoke_grading_validate",
    "load_extensions",
    "require_capability",
]
