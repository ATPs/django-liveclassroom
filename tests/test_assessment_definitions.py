import json
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import AssessmentDefinition, AssessmentItem
from liveclassroom.services.assessments import (
    copy_assessment,
    create_assessment,
    replace_items,
    update_assessment,
)
from liveclassroom.services.classroom import ClassroomError, create_activity_definition, revise_activity_definition


def question(owner, *, type_key="single_choice", metadata=None, answer="A"):
    definition = {
        "prompt": "Which option?",
        "options": [{"id": "A", "text": "A"}, {"id": "B", "text": "B"}],
        "answer": answer,
    }
    if type_key == "short_text":
        definition = {"prompt": "Name it", "answer": answer}
    return create_activity_definition(
        owner=owner,
        title=f"Question {type_key}",
        type_key=type_key,
        definition=definition,
        metadata=metadata,
    )


@pytest.mark.django_db
def test_assessment_pins_revisions_defaults_points_and_copies_independently():
    user = get_user_model().objects.create_user(username="assessment-owner")
    choice = question(user, metadata={"default_points": "2.50"})
    text = question(user, type_key="short_text")
    assessment = create_assessment(
        actor=user,
        data={
            "title": "Cell quiz",
            "instructions": "Answer all questions.",
            "settings": {"max_attempts": 1, "pass_percent": 70, "audience": "authenticated_link"},
            "items": [
                {"revision_id": choice.current_revision_id},
                {"revision_id": text.current_revision_id, "points": "5"},
            ],
        },
    )
    assert assessment.settings == {
        "max_attempts": 1,
        "pass_percent": "70",
        "audience": "authenticated_link",
    }
    assert list(assessment.items.values_list("points", flat=True)) == [Decimal("2.500000"), Decimal("5.000000")]
    assert sum(assessment.items.values_list("points", flat=True), Decimal("0")) == Decimal("7.500000")

    old_revision_id = assessment.items.get(position=1).question_revision_id
    revised = revise_activity_definition(
        activity=choice,
        actor=user,
        definition={
            "prompt": "Changed question",
            "options": [{"id": "A", "text": "A"}, {"id": "B", "text": "B"}],
            "answer": "B",
        },
    )
    assessment.refresh_from_db()
    assert revised.id != old_revision_id
    assert assessment.items.get(position=1).question_revision_id == old_revision_id

    copied = copy_assessment(actor=user, assessment=assessment)
    assert copied.pk != assessment.pk
    assert copied.title == "Cell quiz (Copy)"
    assert {item.key for item in copied.items.all()}.isdisjoint({item.key for item in assessment.items.all()})
    assert list(copied.items.values_list("question_revision_id", flat=True)) == list(
        assessment.items.values_list("question_revision_id", flat=True)
    )


@pytest.mark.django_db
def test_assessment_updates_are_versioned_and_invalid_replacements_are_atomic():
    user = get_user_model().objects.create_user(username="assessment-version")
    first = question(user)
    second = question(user, type_key="short_text")
    assessment = create_assessment(
        actor=user,
        data={"title": "Draft", "items": [{"revision_id": first.current_revision_id}]},
    )
    update_assessment(actor=user, assessment=assessment, expected_version=1, data={"title": "Updated"})
    with pytest.raises(ClassroomError, match="changed"):
        update_assessment(actor=user, assessment=assessment, expected_version=1, data={"title": "Stale"})
    assessment.refresh_from_db()
    before = list(assessment.items.values_list("question_revision_id", flat=True))
    with pytest.raises(ClassroomError):
        replace_items(
            actor=user,
            assessment=assessment,
            expected_version=2,
            items=[
                {"revision_id": second.current_revision_id},
                {"revision_id": "not-an-id"},
            ],
        )
    assert list(
        AssessmentItem.objects.filter(assessment=assessment).values_list("question_revision_id", flat=True)
    ) == before


@pytest.mark.django_db
def test_assessment_rejects_foreign_and_unscored_questions_and_settings():
    users = get_user_model()
    owner = users.objects.create_user(username="assessment-private-owner")
    other = users.objects.create_user(username="assessment-private-other")
    foreign = question(other)
    poll = question(owner, type_key="poll")
    with pytest.raises(ClassroomError, match="permission"):
        create_assessment(
            actor=owner,
            data={"title": "Denied", "items": [{"revision_id": foreign.current_revision_id}]},
        )
    with pytest.raises(ClassroomError, match="graded"):
        create_assessment(actor=owner, data={"title": "Poll", "items": [{"revision_id": poll.current_revision_id}]})
    with pytest.raises(ClassroomError, match="max_attempts"):
        create_assessment(actor=owner, data={"title": "Invalid", "settings": {"max_attempts": 0}})
    assert not AssessmentDefinition.objects.filter(owner=owner).exists()


@pytest.mark.django_db
def test_assessment_api_is_owner_scoped_and_supports_items_copy_and_mount_prefix():
    user = get_user_model().objects.create_user(username="assessment-api-owner")
    other = get_user_model().objects.create_user(username="assessment-api-other")
    revision = question(user).current_revision_id
    client = Client()
    client.force_login(user)
    create = client.post(
        reverse("liveclassroom:api-v1-assessments"),
        data=json.dumps({"title": "API quiz", "items": [{"revision_id": revision}]}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="assessment-create",
    )
    assert create.status_code == 201
    assert create.json()["total_points"] == "1"
    assessment_id = create.json()["id"]
    assert client.get(reverse("liveclassroom:api-v1-assessments")).json()["assessments"][0]["items"][0].get(
        "definition"
    ) is None
    items_url = reverse("liveclassroom:api-v1-assessment-items", args=[assessment_id])
    replaced = client.put(
        items_url,
        data=json.dumps({"expected_version": 1, "items": [{"revision_id": revision, "points": "3"}]}),
        content_type="application/json",
    )
    assert replaced.status_code == 200
    assert replaced.json()["version"] == 2
    copied = client.post(
        reverse("liveclassroom:api-v1-assessment-copy", args=[assessment_id]),
        data="{}",
        content_type="application/json",
    )
    assert copied.status_code == 201
    assert copied.json()["title"] == "API quiz (Copy)"
    intruder = Client()
    intruder.force_login(other)
    assert intruder.get(reverse("liveclassroom:api-v1-assessment-detail", args=[assessment_id])).status_code == 404
