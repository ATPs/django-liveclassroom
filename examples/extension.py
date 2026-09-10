"""A dependency-free extension that can be configured in a standalone site.

Example settings::

    LIVECLASSROOM = {
        "EXTENSIONS": {
            "example": "examples.extension.ExampleGradingExtension",
        },
    }

The package still requires the caller to authorize each invocation.  Loading a
class from settings never grants a teacher access to a question or an answer.
"""

from __future__ import annotations

from typing import Any


class ExampleGradingExtension:
    """A tiny reviewed-answer grader for standalone demonstrations."""

    key = "example.liveclassroom.reviewed_grading"
    protocol_version = 1
    capabilities = frozenset({"grading.validate", "grading.score"})

    def validate(self, definition: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(definition, dict):
            raise ValueError("definition must be an object")
        prompt = definition.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        expected = definition.get("expected")
        if not isinstance(expected, str) or not expected.strip():
            raise ValueError("expected is required")
        return {"prompt": prompt.strip(), "expected": expected.strip()}

    def score(self, answer: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
        value = answer.get("value") if isinstance(answer, dict) else None
        expected = definition.get("expected") if isinstance(definition, dict) else None
        matched = (
            isinstance(value, str)
            and isinstance(expected, str)
            and value.strip().casefold() == expected.casefold()
        )
        return {"score": 1 if matched else 0, "max_score": 1, "matched": matched}


__all__ = ["ExampleGradingExtension"]
