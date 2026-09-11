"""HTTP contracts for audited grade overrides and regrade confirmation."""

import json
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import path

from liveclassroom.api_grade_corrections import grade_override, regrade_apply, regrade_preview
from liveclassroom.models import AssessmentGradeDecision, GradingRuleRevision
from liveclassroom.services.assessment_grading import grade_submitted_attempt
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempt_submission import submit_attempt
from liveclassroom.services.attempts import save_attempt_answer, start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.grade_corrections import item_grade_fingerprint
from tests.test_assessment_grading import _attempt

app_name = "grade-correction-test"
urlpatterns = [
    path("override/<uuid:attempt_id>/<uuid:item_key>/", grade_override),
    path("preview/<uuid:run_id>/", regrade_preview),
    path("apply/<uuid:run_id>/", regrade_apply),
]


def _submit(attempt, learner, answer):
    item = attempt.items.get()
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer=answer[str(item.key)],
        expected_version=0,
        request_id=uuid4(),
    )
    submit_attempt(actor=learner, attempt=attempt, request_id=uuid4(), expected_versions={str(item.key): 1})


def _numeric_attempt():
    users = get_user_model()
    owner = users.objects.create_user(username=f"correction-owner-{uuid4().hex[:8]}")
    learner = users.objects.create_user(username=f"correction-learner-{uuid4().hex[:8]}")
    question = create_activity_definition(
        owner=owner,
        title="Correction question",
        type_key="numeric",
        definition={"prompt": "Value", "answer": 10},
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Correction assessment",
            "settings": {"max_attempts": 1, "audience": "authenticated_link"},
            "items": [{"revision_id": question.current_revision_id, "points": "2"}],
        },
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    attempt = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())[0]
    return owner, learner, run, attempt


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="tests.test_grade_correction_api")
def test_regrade_preview_apply_is_fingerprinted_atomic_and_idempotent():
    owner, learner, run, attempt = _numeric_attempt()
    item = attempt.items.get()
    _submit(attempt, learner, {str(item.key): {"value": "10"}})
    grade_submitted_attempt(attempt=attempt)
    client = Client()
    client.force_login(owner)
    body = {
        "item_keys": [str(item.key)],
        "rule_version": "activity-registry-v2",
        "rule_config": {"answer": 11},
        "reason": "Approved correction.",
    }
    before_decisions = AssessmentGradeDecision.objects.count()
    preview = client.post(f"/preview/{run.public_id}/", data=json.dumps(body), content_type="application/json")
    assert preview.status_code == 200, preview.content
    assert preview.json()["items"][0]["old"]["normalized_score"] == "1.0000000000"
    assert preview.json()["items"][0]["new"]["normalized_score"] == "0.0000000000"
    assert AssessmentGradeDecision.objects.count() == before_decisions
    assert GradingRuleRevision.objects.count() == 0

    apply_body = {**body, "preview_fingerprint": preview.json()["preview_fingerprint"], "idempotency_key": uuid4().hex}
    applied = client.post(f"/apply/{run.public_id}/", data=json.dumps(apply_body), content_type="application/json")
    assert applied.status_code == 200, applied.content
    assert applied.json()["counts"]["changed"] == 1
    assert GradingRuleRevision.objects.count() == 1
    decisions = AssessmentGradeDecision.objects.count()
    replay = client.post(f"/apply/{run.public_id}/", data=json.dumps(apply_body), content_type="application/json")
    assert replay.status_code == 200
    assert replay.get("Idempotent-Replay") == "true"
    assert AssessmentGradeDecision.objects.count() == decisions
    conflict = client.post(
        f"/apply/{run.public_id}/",
        data=json.dumps({**apply_body, "reason": "Different request."}),
        content_type="application/json",
    )
    assert conflict.status_code == 409


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="tests.test_grade_correction_api")
def test_grade_override_requires_current_fingerprint_and_replays_receipt():
    owner = get_user_model().objects.create_user(username=f"override-owner-{uuid4().hex[:8]}")
    learner = get_user_model().objects.create_user(username=f"override-learner-{uuid4().hex[:8]}")
    attempt = _attempt(owner, learner)
    item = attempt.items.get()
    _submit(attempt, learner, {str(item.key): {"choice": "A"}})
    grade_submitted_attempt(attempt=attempt)
    client = Client()
    client.force_login(owner)
    body = {
        "normalized_score": "0.5",
        "comment": "Half credit.",
        "reason": "Reviewed.",
        "expected_grade_fingerprint": item_grade_fingerprint(attempt_item=item),
        "idempotency_key": uuid4().hex,
    }
    response = client.post(
        f"/override/{attempt.public_id}/{item.key}/", data=json.dumps(body), content_type="application/json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["audit_decision_id"]
    replay = client.post(
        f"/override/{attempt.public_id}/{item.key}/", data=json.dumps(body), content_type="application/json"
    )
    assert replay.status_code == 200
    assert replay.get("Idempotent-Replay") == "true"
    stale = client.post(
        f"/override/{attempt.public_id}/{item.key}/",
        data=json.dumps({**body, "idempotency_key": uuid4().hex}),
        content_type="application/json",
    )
    assert stale.status_code == 409
