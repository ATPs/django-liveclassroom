"""Accessibility guardrails for the shared LiveClassroom design tokens."""

from __future__ import annotations

import re
from pathlib import Path

CSS_PATH = Path(__file__).resolve().parents[1] / "src/liveclassroom/static/liveclassroom/liveclassroom.css"
CSS = CSS_PATH.read_text(encoding="utf-8")


def _luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear, strict=True))


def _contrast(foreground: str, background: str) -> float:
    light, dark = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--lc-[a-z0-9-]+):\s*(#[0-9a-f]{6});", block))


def test_shared_tokens_meet_text_focus_and_interactive_boundary_contrast():
    light = _tokens(re.search(r"#liveclassroom-root \{\n  color-scheme:.*?\n\}", CSS, re.DOTALL).group(0))
    dark_pattern = r"@media \(prefers-color-scheme: dark\) \{\n  #liveclassroom-root \{(?P<tokens>.*?)\n  \}\n\}"
    dark = _tokens(
        re.search(
            dark_pattern,
            CSS,
            re.DOTALL,
        ).group("tokens")
    )
    for tokens in (light, dark):
        assert _contrast(tokens["--lc-text"], tokens["--lc-surface"]) >= 4.5
        assert _contrast(tokens["--lc-text-2"], tokens["--lc-surface"]) >= 4.5
        assert _contrast(tokens["--lc-text-3"], tokens["--lc-surface"]) >= 4.5
        assert _contrast(tokens["--lc-on-accent"], tokens["--lc-accent"]) >= 4.5
        assert _contrast(tokens["--lc-accent"], tokens["--lc-surface"]) >= 3
        assert _contrast(tokens["--lc-border-strong"], tokens["--lc-surface"]) >= 3
