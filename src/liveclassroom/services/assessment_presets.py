"""Simple named delivery presets for assessment drafts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from django.db import transaction

from liveclassroom.models import AssessmentDefinition
from liveclassroom.release_policy import DEFAULT_RELEASE_POLICY

from .assessments import MODES, _expected_version, _owner, _settings
from .classroom import ClassroomError

PRESET_MODES = ("practice", "assignment", "quiz", "exam")
PRESET_MODE_LABELS = {
    "practice": {"en": "Practice", "zh": "练习"},
    "assignment": {"en": "Assignment", "zh": "作业"},
    "quiz": {"en": "Quiz", "zh": "测验"},
    "exam": {"en": "Exam", "zh": "考试"},
}


def _release_policy(*, mode: str, closes_at: Any = None) -> dict[str, str]:
    if mode == "practice":
        return {dimension: "after_submit" for dimension in DEFAULT_RELEASE_POLICY}
    if mode == "assignment" and closes_at is not None:
        return {dimension: "after_close" for dimension in DEFAULT_RELEASE_POLICY}
    return dict(DEFAULT_RELEASE_POLICY)


def preset_settings(*, mode: str, current: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return validated settings for a named mode while retaining safe options."""
    if not isinstance(mode, str) or mode not in MODES:
        raise ClassroomError("mode must be practice, assignment, quiz or exam.")
    existing = dict(current) if isinstance(current, Mapping) else {}
    # Re-validate existing values before carrying optional dates/limits into a
    # new mode. This prevents a preset action from preserving malformed legacy
    # JSON that normal authoring would reject.
    normalized = _settings(existing)
    closes_at = normalized.get("closes_at")
    if mode == "practice":
        normalized.update(
            {
                "mode": mode,
                "max_attempts": None,
                "navigation": "free",
                "scoring": False,
                "release_policy": _release_policy(mode=mode, closes_at=closes_at),
            }
        )
        for field in ("due_at", "opens_at", "closes_at", "duration_seconds"):
            normalized.pop(field, None)
    elif mode == "assignment":
        normalized.update(
            {
                "mode": mode,
                "max_attempts": 1,
                "navigation": "free",
                "scoring": True,
                "release_policy": _release_policy(mode=mode, closes_at=closes_at),
            }
        )
        normalized.pop("duration_seconds", None)
        normalized.pop("opens_at", None)
    elif mode == "quiz":
        normalized.update(
            {
                "mode": mode,
                "max_attempts": 1,
                "navigation": "free",
                "scoring": True,
                "release_policy": dict(DEFAULT_RELEASE_POLICY),
            }
        )
        for field in ("due_at", "opens_at", "closes_at"):
            normalized.pop(field, None)
    else:
        normalized.update(
            {
                "mode": mode,
                "max_attempts": 1,
                "audience": "authenticated_link",
                "navigation": "forward_only",
                "scoring": True,
                "release_policy": dict(DEFAULT_RELEASE_POLICY),
            }
        )
    # A final pass uses the canonical assessment settings validator and keeps
    # the preset output free of unknown fields.
    return _settings(normalized)


def preset_readiness(*, mode: str, settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Describe whether the saved preset has the timing needed to run."""
    if not isinstance(mode, str) or mode not in MODES:
        raise ClassroomError("mode must be practice, assignment, quiz or exam.")
    values = settings if isinstance(settings, Mapping) else {}
    missing: list[str] = []
    if mode == "exam" and not values.get("duration_seconds") and not (
        values.get("opens_at") and values.get("closes_at")
    ):
        missing.append("duration_seconds or opens_at and closes_at")
    return {"mode": mode, "ready": not missing, "missing": missing}


@transaction.atomic
def apply_assessment_preset(
    *, actor, assessment: AssessmentDefinition, mode: str, expected_version: int
) -> AssessmentDefinition:
    """Apply a preset to a draft using the same optimistic version contract."""
    _owner(actor, assessment)
    locked = AssessmentDefinition.objects.select_for_update().get(pk=assessment.pk)
    _expected_version(locked, expected_version)
    locked.settings = preset_settings(mode=mode, current=locked.settings)
    locked.version += 1
    locked.save(update_fields=["settings", "version", "updated_at"])
    return locked


def preset_payload(assessment: AssessmentDefinition) -> dict[str, Any]:
    """Expose mode and readiness without creating a separate model."""
    settings = assessment.settings if isinstance(assessment.settings, dict) else {}
    mode = settings.get("mode", "quiz")
    return {
        "mode": mode,
        "settings": deepcopy(settings),
        "readiness": preset_readiness(mode=mode, settings=settings),
    }


__all__ = [
    "PRESET_MODE_LABELS",
    "PRESET_MODES",
    "apply_assessment_preset",
    "preset_payload",
    "preset_readiness",
    "preset_settings",
]
