"""Focused service checks for the VaultPub-backed Markdown/YAML adapter."""

from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model

from liveclassroom.models import ActivityDefinition, AuthoringCommandReceipt, Deck
from liveclassroom.services.markdown_import import (
    MarkdownImportError,
    commit_markdown_import,
    preview_markdown_import,
)


def _teacher(label: str):
    return get_user_model().objects.create_user(username=f"markdown-portable-{label}")


@pytest.mark.django_db
def test_preview_uses_vaultpub_slide_boundaries_and_preserves_fenced_markdown():
    teacher = _teacher("deck")
    source = """---
kind: deck
title: Biology deck
slide:
  theme: light
---
# First

```python
---
```

---
# Second

$$x^2$$ and Mermaid source stay as Markdown.
"""
    before = (Deck.objects.count(), ActivityDefinition.objects.count())
    draft = preview_markdown_import(actor=teacher, filename="biology.md", content=source)
    assert draft.valid is True
    assert draft.kind == "deck"
    assert len(draft.payload["decks"][0]["slides"]) == 2
    assert "---" in draft.payload["decks"][0]["slides"][0]["markdown"]
    assert "$$x^2$$" in draft.payload["decks"][0]["slides"][1]["markdown"]
    assert (Deck.objects.count(), ActivityDefinition.objects.count()) == before


@pytest.mark.django_db
def test_question_yaml_uses_the_same_portable_activity_validator():
    teacher = _teacher("question")
    source = """kind: question
title: Cell question
type: single_choice
options:
  - id: A
    text: "Nucleus"
  - id: B
    text: "Ribosome"
answer: A
metadata:
  topic: biology
"""
    draft = preview_markdown_import(actor=teacher, filename="question.yaml", content=source)
    assert draft.valid
    activity = draft.payload["activities"][0]
    assert activity["definition"]["answer"] == "A"
    assert activity["metadata"] == {"topic": "biology"}


@pytest.mark.django_db
def test_lesson_delegates_quiz_syntax_to_existing_importer():
    teacher = _teacher("lesson")
    source = """---
kind: lesson
title: Review lesson
---
# Intro

:::quiz
type: single_choice
question: Pick one
choices:
  - "A"
  - "B"
answer: A
:::
"""
    draft = preview_markdown_import(actor=teacher, filename="lesson.md", content=source)
    assert draft.valid
    assert [row["type_key"] for row in draft.payload["activities"]] == [
        "liveclassroom.markdown",
        "liveclassroom.single_choice",
    ]
    assert draft.payload["flows"][0]["steps"] == ["activity-1", "activity-2"]


@pytest.mark.django_db
def test_assessment_commit_is_atomic_and_idempotent():
    teacher = _teacher("assessment")
    source = """kind: assessment
title: Quick check
items:
  - key: item-1
    type: single_choice
    title: One question
    definition:
      prompt: Pick one
      options:
        - id: A
          text: "Yes"
        - id: B
          text: "No"
      answer: A
    points: "2"
"""
    draft = preview_markdown_import(actor=teacher, filename="assessment.yml", content=source)
    assert draft.valid, draft.as_dict()
    result = commit_markdown_import(actor=teacher, draft=draft, idempotency_key="assessment-import-1")
    assert len(result.assessments) == 1
    assert result.assessments[0].items.count() == 1
    created = (ActivityDefinition.objects.count(), AuthoringCommandReceipt.objects.count())
    replay = commit_markdown_import(actor=teacher, draft=draft, idempotency_key="assessment-import-1")
    assert replay.assessments[0].pk == result.assessments[0].pk
    assert (ActivityDefinition.objects.count(), AuthoringCommandReceipt.objects.count()) == created


@pytest.mark.django_db
def test_stale_draft_and_invalid_yaml_do_not_write():
    teacher = _teacher("errors")
    valid = preview_markdown_import(
        actor=teacher,
        filename="q.md",
        content="---\nkind: question\ntitle: Q\ntype: markdown\n---\nHello",
    )
    stale = replace(valid, content="---\nkind: question\ntitle: Changed\ntype: markdown\n---\nHello")
    with pytest.raises(MarkdownImportError, match="source changed"):
        commit_markdown_import(actor=teacher, draft=stale)
    invalid = preview_markdown_import(
        actor=teacher,
        filename="bad.md",
        content="---\nkind: question\ntitle: Q\nkind: deck\n---\nBody",
    )
    assert not invalid.valid
    assert invalid.errors[0].code == "invalid_yaml"
    assert invalid.errors[0].line is not None
    assert ActivityDefinition.objects.count() == 0


@pytest.mark.django_db
def test_unsafe_urls_unknown_fields_and_paths_are_rejected():
    teacher = _teacher("security")
    unsafe = preview_markdown_import(
        actor=teacher,
        filename="unsafe.md",
        content="---\nkind: deck\ntitle: Unsafe\n---\n![x](https://example.test/x.png)",
    )
    assert not unsafe.valid
    assert any(error.code == "unsafe_url" for error in unsafe.errors)
    unknown = preview_markdown_import(
        actor=teacher,
        filename="unknown.md",
        content="---\nkind: question\ntitle: Q\nnot_allowed: true\n---\nBody",
    )
    assert not unknown.valid
    assert unknown.errors[0].code == "unknown_field"
    path = preview_markdown_import(actor=teacher, filename="../unsafe.md", content="kind: question")
    assert not path.valid
    assert path.errors[0].code == "unsafe_path"


@pytest.mark.django_db
def test_unclosed_fence_is_reported_without_treating_its_separator_as_a_slide():
    teacher = _teacher("fence")
    draft = preview_markdown_import(
        actor=teacher,
        filename="fence.md",
        content="---\nkind: deck\ntitle: Fence\n---\n# One\n```\n---\n",
    )
    assert not draft.valid
    assert any(error.code == "invalid_fence" for error in draft.errors)
