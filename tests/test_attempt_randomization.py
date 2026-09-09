from random import Random
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from liveclassroom.models import AssessmentAttempt
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempt_assignment import assign_attempt_items, assigned_item_manifests
from liveclassroom.services.classroom import create_activity_definition


def _question(owner, title):
    return create_activity_definition(
        owner=owner,
        title=title,
        type_key="single_choice",
        definition={"prompt": title, "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}], "answer": "a"},
    )


@pytest.mark.django_db
def test_frozen_pool_assignments_are_deterministic_and_retain_option_ids():
    owner = get_user_model().objects.create_user(username="assignment-owner")
    learner = get_user_model().objects.create_user(username="assignment-learner")
    fixed = _question(owner, "Fixed")
    first = _question(owner, "One")
    second = _question(owner, "Two")
    assessment = create_assessment(
        actor=owner, data={"title": "Pool", "items": [{"revision_id": fixed.current_revision_id}]}
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    run.manifest["sections"] = [{"position": 1, "entries": [
        {"position": 1, "kind": "fixed", "item": run.manifest["items"][0]},
        {"position": 2, "kind": "pool", "sample_size": 1, "shuffle_options": True, "candidates": [
            {**run.manifest["items"][0], "key": str(uuid4()), "payload": first.definition},
            {**run.manifest["items"][0], "key": str(uuid4()), "payload": second.definition},
        ]},
    ]}]
    run.save(update_fields=["manifest"])
    expected = assigned_item_manifests(run=run, rng=Random(7))
    attempt = AssessmentAttempt.objects.create(run=run, user=learner, attempt_number=1)
    assigned = assign_attempt_items(run=run, attempt=attempt, rng=Random(7))
    assert [row.manifest["payload"]["prompt"] for row in assigned] == [row["payload"]["prompt"] for row in expected]
    assert assigned[1].manifest["option_order"] in (["a", "b"], ["b", "a"])
    assert {option["id"] for option in assigned[1].manifest["payload"]["options"]} == {"a", "b"}
    assert [row.position for row in assigned] == [1, 2]
