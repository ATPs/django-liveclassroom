"""Owner-authorized Markdown export for native decks."""

from __future__ import annotations

from typing import Any

import yaml

from liveclassroom.models import Deck

from .classroom import ClassroomError
from .decks import _owner

_NOTES_OPEN = "<!-- liveclassroom:notes -->"
_NOTES_CLOSE = "<!-- /liveclassroom:notes -->"


def _frontmatter(deck: Deck) -> str:
    # Keep title/theme at the top level.  The importer also accepts VaultPub's
    # nested slide.theme form, while this form is useful to other Markdown tools.
    values = {"title": deck.title, "theme": deck.theme}
    encoded = yaml.safe_dump(values, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip()
    return f"---\n{encoded}\n---"


def _safe_notes(notes: str) -> str:
    """Prevent a note body from terminating the exported private block."""
    # Notes are private text, but the marker is a transport delimiter.  Prefix
    # a backslash only on a line which could otherwise be interpreted as one.
    return "\n".join(
        "\\" + line if line.strip() in {_NOTES_OPEN, _NOTES_CLOSE} else line
        for line in notes.splitlines()
    )


def export_deck_markdown(*, actor: Any, deck: Deck, include_notes: bool = False) -> str:
    """Export an owned deck as Markdown with notes excluded by default.

    ``include_notes`` is deliberately a strict boolean.  A caller must opt in
    explicitly, and ownership is checked even when the ``Deck`` instance came
    from an untrusted lookup.  The result contains no database IDs or server
    paths; asset links already present in slide Markdown remain unchanged.
    """
    if not isinstance(include_notes, bool):
        raise ClassroomError("include_notes must be a boolean.")
    _owner(actor, deck)
    slides = list(deck.slides.order_by("position", "id"))
    if not slides:
        raise ClassroomError("Cannot export a deck without slides.")
    parts = [_frontmatter(deck)]
    for slide in slides:
        markdown = slide.markdown.strip()
        if not markdown:
            markdown = "<!-- Empty slide -->"
        if include_notes and slide.notes.strip():
            markdown = (
                f"{markdown}\n\n{_NOTES_OPEN}\n{_safe_notes(slide.notes.strip())}\n{_NOTES_CLOSE}"
            )
        parts.append(markdown)
    return "\n\n---\n\n".join(parts) + "\n"


# Names kept as small conveniences for callers that use the noun first.
deck_export_markdown = export_deck_markdown
export_markdown = export_deck_markdown
