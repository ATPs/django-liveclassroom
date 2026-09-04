import pytest
from django.contrib.auth import get_user_model

from liveclassroom.importers import ImportError, import_markdown_flow, parse_markdown
from liveclassroom.models import Course

SOURCE = """---
title: Demo
slug: demo
---
# Intro
:::quiz
type: single_choice
question: Pick one
choices: ["No", "Yes"]
answer: ["Yes"]
:::
"""


def test_parse_markdown_normalizes_answer_text_to_option_id():
    parsed = parse_markdown(SOURCE)
    question = parsed.items[1].question
    assert question["answer"] == ["B"]
    assert len(parsed.items) == 2


@pytest.mark.django_db
def test_import_markdown_creates_reusable_activity_definitions_and_flow_steps():
    user = get_user_model().objects.create_user(username="teacher")
    course = Course.objects.create(title="Course", slug="course", created_by=user)
    flow = import_markdown_flow(course=course, source=SOURCE)

    assert flow.slug == "demo"
    steps = list(flow.steps.select_related("activity_definition"))
    assert [step.kind for step in steps] == ["markdown", "activity"]
    assert steps[1].activity_definition.type_key == "liveclassroom.single_choice"
    assert steps[1].activity_definition.definition["answer"] == ["B"]
    assert flow.items.count() == 0


def test_rejects_invalid_quiz():
    with pytest.raises(ImportError, match="at least two choices"):
        parse_markdown("---\ntitle: Bad\n---\n:::quiz\nquestion: bad\nchoices: [only]\n:::")
