"""Focused service checks for native Markdown deck portability."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from liveclassroom.importers.decks import DeckImportError, import_deck, preview_deck_import
from liveclassroom.models import ClassroomAsset, Deck
from liveclassroom.services.classroom import ClassroomError
from liveclassroom.services.deck_export import export_deck_markdown
from liveclassroom.services.decks import create_deck


@pytest.fixture
def deck_teacher(db):
    return get_user_model().objects.create_user(username=f"deck-portability-{uuid4().hex[:8]}")


@pytest.mark.django_db
def test_preview_uses_vaultpub_boundaries_and_keeps_fenced_separators(deck_teacher):
    source = """---
title: "Unicode 生物课"
theme: dark
---

# Opening

```yaml
---
still code
---
```

---

## Equations

$E = mc^2$

---

# Closing
"""
    before = Deck.objects.count()
    result = preview_deck_import(deck_teacher, source)
    assert result["valid"] is True
    assert result["errors"] == []
    assert result["draft"]["title"] == "Unicode 生物课"
    assert result["draft"]["theme"] == "dark"
    assert len(result["draft"]["slides"]) == 3
    assert "---\nstill code\n---" in result["draft"]["slides"][0]["markdown"]
    assert Deck.objects.count() == before


@pytest.mark.django_db
def test_private_notes_round_trip_only_when_teacher_explicitly_exports(deck_teacher):
    deck = create_deck(
        actor=deck_teacher,
        data={
            "title": "Notes 生物课",
            "theme": "dark",
            "slides": [
                {"markdown": "# One\n\nPublic", "notes": "Ask for an example."},
                {"markdown": "# Two", "notes": "第二页备注"},
            ],
        },
    )
    public = export_deck_markdown(actor=deck_teacher, deck=deck)
    assert "liveclassroom:notes" not in public
    public_preview = preview_deck_import(deck_teacher, public)
    assert public_preview["valid"] is True
    assert all(not slide["notes"] for slide in public_preview["draft"]["slides"])

    with_notes = export_deck_markdown(actor=deck_teacher, deck=deck, include_notes=True)
    assert "<!-- liveclassroom:notes -->" in with_notes
    restored = preview_deck_import(deck_teacher, with_notes)
    assert restored["valid"] is True
    assert [slide["notes"] for slide in restored["draft"]["slides"]] == ["Ask for an example.", "第二页备注"]
    assert [slide["markdown"] for slide in restored["draft"]["slides"]] == ["# One\n\nPublic", "# Two"]


@pytest.mark.django_db
def test_preview_reports_unresolved_and_unsafe_asset_references_without_writes(deck_teacher):
    asset = ClassroomAsset.objects.create(
        owner=deck_teacher,
        source=ClassroomAsset.Source.UPLOAD,
        original_name="figure.png",
        kind=ClassroomAsset.Kind.PDF,
        content_type="image/png",
        byte_size=3,
    )
    source = f"# Figures\n\n![approved](asset:{asset.public_id})\n\n![missing](https://bad.example/a.png)"
    before = Deck.objects.count()
    result = preview_deck_import(deck_teacher, source, [asset])
    assert result["valid"] is False
    assert any("External image URLs" in error["message"] for error in result["errors"])
    assert Deck.objects.count() == before


@pytest.mark.django_db
def test_preview_rejects_malformed_or_unsupported_frontmatter_before_writes(deck_teacher):
    malformed = preview_deck_import(deck_teacher, "---\ntitle: [broken\n---\n# Slide")
    assert malformed["valid"] is False
    assert malformed["draft"]["slides"] == []
    unsupported = preview_deck_import(deck_teacher, "---\ntitle: Bad\ntheme: dracula\n---\n# Slide")
    assert unsupported["valid"] is False
    assert "Unsupported theme" in unsupported["errors"][0]["message"]


@pytest.mark.django_db
def test_import_creates_independent_owned_deck_and_invalid_draft_writes_nothing(deck_teacher):
    result = preview_deck_import(deck_teacher, "---\ntitle: Copy\ntheme: light\n---\n# Slide")
    deck = import_deck(deck_teacher, result)
    assert deck.owner_id == deck_teacher.id
    assert deck.title == "Copy"
    assert list(deck.slides.values_list("markdown", flat=True)) == ["# Slide"]

    before = Deck.objects.count()
    invalid = {"title": "Bad", "theme": "unknown", "slides": result["draft"]["slides"]}
    with pytest.raises(DeckImportError):
        import_deck(deck_teacher, invalid)
    assert Deck.objects.count() == before


@pytest.mark.django_db
def test_deck_export_is_owner_only_and_include_notes_is_strict(deck_teacher):
    other = get_user_model().objects.create_user(username=f"deck-other-{uuid4().hex[:8]}")
    deck = create_deck(actor=deck_teacher, data={"title": "Private", "slides": [{"markdown": "# A"}]})
    with pytest.raises(ClassroomError):
        export_deck_markdown(actor=other, deck=deck)
    with pytest.raises(ClassroomError):
        export_deck_markdown(actor=deck_teacher, deck=deck, include_notes=1)  # type: ignore[arg-type]
