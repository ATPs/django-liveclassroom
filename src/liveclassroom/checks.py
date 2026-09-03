"""Django system checks for the LiveClassroom activity plugin system."""

import re
from typing import Any

from django.core.checks import Error, Tags, Warning, register

from .registry import activity_registry

REQUIRED_MANIFEST_KEYS: tuple[str, ...] = (
    "editor",
    "student_renderer",
    "display_renderer",
    "analytics",
)

KNOWN_CAPABILITIES: frozenset[str] = frozenset(
    {
        "choices",
        "correctness",
        "aggregate",
        "text",
        "numeric",
        "rating",
        "ranking",
        "content",
        "timed",
        "legacy",
    }
)

_NAMESPACED_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)+$")


@register(Tags.compatibility)
def check_activity_registry(app_configs: Any = None, **kwargs: Any) -> list[Error | Warning]:
    """Validate that all registered activity types satisfy plugin contracts."""
    messages: list[Error | Warning] = []

    for activity_type in activity_registry.all():
        key = getattr(activity_type, "key", None)
        # 1. Key validation (liveclassroom.E001)
        if not isinstance(key, str) or not _NAMESPACED_KEY_PATTERN.match(key):
            messages.append(
                Error(
                    f"Activity type key {key!r} must be a valid namespaced string (e.g. 'liveclassroom.poll').",
                    id="liveclassroom.E001",
                    obj=activity_type,
                )
            )

        # 2. Frontend manifest validation (liveclassroom.E002)
        manifest = getattr(activity_type, "frontend_manifest", None)
        if not isinstance(manifest, dict) or not manifest:
            messages.append(
                Error(
                    f"Activity type {key!r} must define a non-empty frontend_manifest.",
                    hint=f"Required surface keys: {', '.join(REQUIRED_MANIFEST_KEYS)}.",
                    id="liveclassroom.E002",
                    obj=activity_type,
                )
            )
        else:
            for surface_key in REQUIRED_MANIFEST_KEYS:
                val = manifest.get(surface_key)
                if not isinstance(val, str) or not val.strip():
                    messages.append(
                        Error(
                            f"Activity type {key!r} frontend_manifest is missing or has empty surface "
                            f"key: {surface_key!r}.",
                            hint=f"Required surface keys: {', '.join(REQUIRED_MANIFEST_KEYS)}.",
                            id="liveclassroom.E002",
                            obj=activity_type,
                        )
                    )

        # 3. Capabilities validation (liveclassroom.E003 / liveclassroom.W001)
        capabilities = getattr(activity_type, "capabilities", None)
        if not isinstance(capabilities, (set, frozenset, list, tuple)):
            messages.append(
                Error(
                    f"Activity type {key!r} capabilities must be a collection of non-empty strings.",
                    id="liveclassroom.E003",
                    obj=activity_type,
                )
            )
        else:
            for cap in capabilities:
                if not isinstance(cap, str) or not cap.strip():
                    messages.append(
                        Error(
                            f"Activity type {key!r} has invalid capability: {cap!r}.",
                            id="liveclassroom.E003",
                            obj=activity_type,
                        )
                    )
                elif cap not in KNOWN_CAPABILITIES:
                    messages.append(
                        Warning(
                            f"Activity type {key!r} declares unrecognized capability {cap!r}.",
                            hint=f"Recognized capabilities: {', '.join(sorted(KNOWN_CAPABILITIES))}.",
                            id="liveclassroom.W001",
                            obj=activity_type,
                        )
                    )

    return messages
