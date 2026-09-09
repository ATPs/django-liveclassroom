import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from liveclassroom.models import AnswerRevision, AssessmentAttempt
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempt_submission import (
    AttemptSubmissionConflict,
    attempt_submitted,
    submit_attempt,
)
from liveclassroom.services.attempts import AttemptAnswerConflict, save_attempt_answer, start_or_resume_attempt
from liveclassroom.services.classroom import ClassroomError, create_activity_definition


def _attempt(owner, learner):
    question = create_activity_definition(
        owner=owner,
        title="Submission question",
        type_key="short_text",
        definition={"prompt": "What is saved?"},
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Submission",
            "settings": {"max_attempts": 1, "audience": "authenticated_link"},
            "items": [{"revision_id": question.current_revision_id}],
        },
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    return start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())[0]


@pytest.mark.django_db
def test_submit_allows_empty_answers_and_repeated_submit_is_stable():
    users = get_user_model()
    owner = users.objects.create_user(username="submit-owner")
    learner = users.objects.create_user(username="submit-learner")
    attempt = _attempt(owner, learner)
    item = attempt.items.get()
    submitted_at = timezone.now() - timedelta(seconds=1)

    first = submit_attempt(
        actor=learner,
        attempt=attempt,
        request_id=uuid4(),
        expected_versions={str(item.key): 0},
        now=submitted_at,
    )
    repeated = submit_attempt(
        actor=learner,
        attempt=attempt,
        request_id=uuid4(),
        expected_versions={str(item.key): 99},
        now=timezone.now(),
    )

    assert dict(first) == dict(repeated)
    assert first["status"] == AssessmentAttempt.Status.SUBMITTED
    assert first["submitted_at"] == submitted_at.isoformat()
    assert first["finalization_reason"] == "student"
    assert first["items"] == [{"item_key": str(item.key), "version": 0, "answer": None}]
    attempt.refresh_from_db()
    assert attempt.status == AssessmentAttempt.Status.SUBMITTED
    assert AnswerRevision.objects.count() == 0


@pytest.mark.django_db
def test_submission_includes_last_saved_revision_and_rejects_later_writes():
    users = get_user_model()
    owner = users.objects.create_user(username="submit-save-owner")
    learner = users.objects.create_user(username="submit-save-learner")
    attempt = _attempt(owner, learner)
    item = attempt.items.get()
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"text": "persisted"},
        expected_version=0,
        request_id=uuid4(),
    )

    result = submit_attempt(
        actor=learner,
        attempt=attempt,
        request_id=uuid4(),
        expected_versions={str(item.key): 1},
    )
    assert result["items"][0]["version"] == 1
    assert result["items"][0]["answer"] == {"text": "persisted"}

    with pytest.raises(AttemptAnswerConflict, match="finalized"):
        save_attempt_answer(
            actor=learner,
            attempt=attempt,
            item_key=item.key,
            answer={"text": "changed"},
            expected_version=1,
            request_id=uuid4(),
        )
    assert list(AnswerRevision.objects.values_list("version", "answer")) == [(1, {"text": "persisted"})]


@pytest.mark.django_db
def test_version_mismatch_keeps_attempt_open_and_returns_current_versions():
    users = get_user_model()
    owner = users.objects.create_user(username="submit-conflict-owner")
    learner = users.objects.create_user(username="submit-conflict-learner")
    attempt = _attempt(owner, learner)
    item = attempt.items.get()
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"text": "saved"},
        expected_version=0,
        request_id=uuid4(),
    )

    with pytest.raises(AttemptSubmissionConflict) as caught:
        submit_attempt(
            actor=learner,
            attempt=attempt,
            request_id=uuid4(),
            expected_versions={str(item.key): 0},
        )
    assert caught.value.code == "stale_revision"
    assert caught.value.current_versions == {str(item.key): 1}
    attempt.refresh_from_db()
    assert attempt.status == AssessmentAttempt.Status.IN_PROGRESS
    assert attempt.submitted_at is None


@pytest.mark.django_db
def test_foreign_actor_cannot_submit_and_expiry_uses_effective_deadline():
    users = get_user_model()
    owner = users.objects.create_user(username="submit-expiry-owner")
    learner = users.objects.create_user(username="submit-expiry-learner")
    foreign = users.objects.create_user(username="submit-expiry-foreign")
    attempt = _attempt(owner, learner)
    with pytest.raises(ClassroomError, match="permission"):
        submit_attempt(actor=foreign, attempt=attempt, request_id=uuid4())

    deadline = timezone.now() - timedelta(seconds=1)
    attempt.deadline_at = deadline
    attempt.save(update_fields=["deadline_at"])
    result = submit_attempt(actor=None, attempt=attempt, request_id=uuid4(), reason="expired", now=timezone.now())
    assert result["finalization_reason"] == "expired"
    assert result["submitted_at"] == deadline.isoformat()


@pytest.mark.django_db
def test_submit_api_rejects_client_reason_and_replays_terminal_result():
    users = get_user_model()
    owner = users.objects.create_user(username="submit-api-owner")
    learner = users.objects.create_user(username="submit-api-learner")
    attempt = _attempt(owner, learner)
    item = attempt.items.get()
    client = Client()
    client.force_login(learner)
    url = reverse("liveclassroom:api-v1-attempt-submit", args=[attempt.public_id])

    invalid = client.post(
        url,
        data=json.dumps({"request_id": str(uuid4()), "reason": "expired"}),
        content_type="application/json",
    )
    assert invalid.status_code == 400
    assert attempt.status == AssessmentAttempt.Status.IN_PROGRESS

    body = {"request_id": str(uuid4()), "expected_versions": {str(item.key): 0}}
    first = client.post(url, data=json.dumps(body), content_type="application/json")
    repeated = client.post(
        url,
        data=json.dumps({**body, "request_id": str(uuid4()), "expected_versions": {str(item.key): 100}}),
        content_type="application/json",
    )
    assert first.status_code == repeated.status_code == 200
    assert first.json() == repeated.json()


@pytest.mark.django_db
def test_submission_event_is_emitted_after_durable_commit_once():
    users = get_user_model()
    owner = users.objects.create_user(username="submit-event-owner")
    learner = users.objects.create_user(username="submit-event-learner")
    attempt = _attempt(owner, learner)
    received = []

    def receiver(sender, **kwargs):
        received.append(kwargs)

    attempt_submitted.connect(receiver, weak=False)
    try:
        with TestCase.captureOnCommitCallbacks(execute=True):
            submit_attempt(actor=learner, attempt=attempt, request_id=uuid4())
            submit_attempt(actor=learner, attempt=attempt, request_id=uuid4())
    finally:
        attempt_submitted.disconnect(receiver)
    assert len(received) == 1
    assert received[0]["attempt_id"] == attempt.pk
    assert received[0]["reason"] == "student"
    assert received[0]["result"]["status"] == AssessmentAttempt.Status.SUBMITTED
