import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import AssessmentRun
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.classroom import ClassroomError, create_activity_definition, revise_activity_definition


def _question(owner):
    return create_activity_definition(
        owner=owner,
        title="Cell question",
        type_key="single_choice",
        definition={"prompt": "Old prompt", "options": [{"id": "a", "text": "A"}], "answer": "a"},
    )


@pytest.mark.django_db
def test_publication_copies_exact_question_content_and_retains_source_provenance():
    owner = get_user_model().objects.create_user(username="run-owner")
    question = _question(owner)
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Cells",
            "instructions": "Do it.",
            "items": [{"revision_id": question.current_revision_id}],
        },
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    assert run.audience == "authenticated_link"
    assert run.manifest["items"][0]["payload"]["prompt"] == "Old prompt"
    revise_activity_definition(
        activity=question, actor=owner,
        definition={"prompt": "New prompt", "options": [{"id": "a", "text": "A"}], "answer": "a"},
    )
    run.refresh_from_db()
    assert run.manifest["items"][0]["payload"]["prompt"] == "Old prompt"
    assessment.delete()
    run.refresh_from_db()
    assert run.source_assessment is None
    assert run.manifest["items"][0]["payload"]["answer"] == "a"


@pytest.mark.django_db
def test_publication_rejects_stale_or_empty_drafts_without_writes():
    owner = get_user_model().objects.create_user(username="run-invalid")
    empty = create_assessment(actor=owner, data={"title": "Empty", "items": []})
    with pytest.raises(ClassroomError, match="at least one"):
        publish_assessment(actor=owner, assessment=empty, expected_version=empty.version)
    assert not AssessmentRun.objects.exists()
    question = _question(owner)
    assessment = create_assessment(
        actor=owner,
        data={"title": "Quiz", "items": [{"revision_id": question.current_revision_id}]},
    )
    with pytest.raises(ClassroomError, match="changed"):
        publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version + 1)
    assert not AssessmentRun.objects.exists()


@pytest.mark.django_db
def test_run_api_replays_publish_and_hides_manifest_from_entry_metadata():
    users = get_user_model()
    owner = users.objects.create_user(username="run-api-owner")
    other = users.objects.create_user(username="run-api-other")
    question = _question(owner)
    assessment = create_assessment(
        actor=owner,
        data={"title": "API run", "items": [{"revision_id": question.current_revision_id}]},
    )
    client = Client()
    client.force_login(owner)
    url = reverse("liveclassroom:api-v1-assessment-runs", args=[assessment.id])
    data = json.dumps({"expected_version": assessment.version})
    first = client.post(url, data=data, content_type="application/json", HTTP_IDEMPOTENCY_KEY="publish-run")
    assert first.status_code == 201
    replay = client.post(url, data=data, content_type="application/json", HTTP_IDEMPOTENCY_KEY="publish-run")
    assert replay.status_code == 201 and replay["Idempotent-Replay"] == "true"
    assert AssessmentRun.objects.count() == 1
    public_id = first.json()["public_id"]
    intruder = Client()
    intruder.force_login(other)
    assert intruder.get(reverse("liveclassroom:api-v1-assessment-run-detail", args=[public_id])).status_code == 404
    entry = client.get(reverse("liveclassroom:api-v1-available-assessment-run", args=[public_id]))
    assert entry.status_code == 200
    assert "manifest" not in entry.json() and "answer" not in json.dumps(entry.json())
