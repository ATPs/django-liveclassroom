"""Small presentation-only compatibility helpers.

Raw snapshots remain historical/auditable.  These helpers are deliberately
limited to labels exposed to people so older seeded Bash copies do not show
their former machine matching prefix.
"""

import re

_BASH_DEMO_KEYS = {
    "welcome", "confidence_poll", "word_cloud", "terminal_map", "cheatsheet", "simulator", "timer",
    "true_false", "multiple_choice", "single_choice", "numeric", "rating", "ranking", "reflection",
}
_LEGACY_BASH_TITLE = re.compile(r"^\[bash-demo:(?:en|zh-Hans):([a-z0-9_]+)\]\s+(.+)$")


def presentation_title(title: object, fallback: str = "Activity") -> str:
    """Return a human-facing label without modifying stored title data."""
    value = title if isinstance(title, str) else fallback
    match = _LEGACY_BASH_TITLE.match(value)
    if match and match.group(1) in _BASH_DEMO_KEYS:
        return match.group(2)
    return value
