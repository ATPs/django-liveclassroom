"""Shared validation for assessment result-release settings.

This module intentionally has no Django model imports.  Assessment authoring
uses it while the app models are being imported, and the result-release
service re-exports the same helpers for callers that need to validate a
published run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .services.classroom import ClassroomError

RELEASE_DIMENSIONS = ("scores", "answers", "explanations", "comments")
RELEASE_POLICIES = frozenset({"never", "after_submit", "after_close", "manual"})
DEFAULT_RELEASE_POLICY = {dimension: "manual" for dimension in RELEASE_DIMENSIONS}


def normalize_release_policy(value: Any = None, *, closes_at: Any = None) -> dict[str, str]:
    """Validate and complete the four independent release policy fields.

    Missing dimensions use the deliberately conservative ``manual`` default.
    The returned dictionary is safe to freeze into an assessment run manifest.
    ``after_close`` is only meaningful when a hard close time is configured;
    rejecting it here avoids an accidental immediate release.
    """
    if value is None:
        result = dict(DEFAULT_RELEASE_POLICY)
    elif not isinstance(value, Mapping):
        raise ClassroomError("release_policy must be an object.")
    else:
        unknown = set(value) - set(RELEASE_DIMENSIONS)
        if unknown:
            raise ClassroomError(
                f"Unsupported release policy dimensions: {', '.join(sorted(map(str, unknown)))}."
            )
        result = dict(DEFAULT_RELEASE_POLICY)
        for dimension in RELEASE_DIMENSIONS:
            if dimension not in value:
                continue
            policy = value[dimension]
            if not isinstance(policy, str) or policy not in RELEASE_POLICIES:
                raise ClassroomError(
                    f"release_policy.{dimension} must be never, after_submit, after_close or manual."
                )
            result[dimension] = policy

    if "after_close" in result.values() and closes_at is None:
        raise ClassroomError("after_close release requires closes_at.")
    return result


__all__ = [
    "DEFAULT_RELEASE_POLICY",
    "RELEASE_DIMENSIONS",
    "RELEASE_POLICIES",
    "normalize_release_policy",
]
