import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from liveclassroom.models import AnswerRevision, AssessmentAttempt
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import AttemptAnswerConflict, save_attempt_answer, start_or_resume_attempt
from liveclassroom.services.classroom import ClassroomError, create_activity_definition


def _attempt(owner, learner, *, type_key="short_text", definition=None):
    question = create_activity_definition(
        owner=owner,
        title="Question",
        type_key=type_key,
        definition=definition or {"prompt": "Answer"},
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Autosave",
            "settings": {"max_attempts": 1, "audience": "authenticated_link"},
            "items": [{"revision_id": question.current_revision_id}],
        },
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    return start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())[0]


@pytest.mark.django_db
def test_save_replays_lost_response_after_newer_revision_without_reverting_current_answer():
    users = get_user_model()
    owner = users.objects.create_user(username="autosave-owner")
    learner = users.objects.create_user(username="autosave-learner")
    attempt = _attempt(owner, learner)
    item = attempt.items.get()
    first_request = uuid4()

    first = save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"text": "RNA"},
        expected_version=0,
        request_id=first_request,
    )
    second = save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"text": "DNA"},
        expected_version=1,
        request_id=uuid4(),
    )
    replay = save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"text": "RNA"},
        expected_version=0,
        request_id=first_request,
    )

    assert replay.pk == first.pk
    assert second.version == 2
    assert list(AnswerRevision.objects.filter(item=item).values_list("version", "answer")) == [
        (1, {"text": "RNA"}),
        (2, {"text": "DNA"}),
    ]


@pytest.mark.django_db
def test_changed_request_body_and_stale_tab_are_conflicts_with_current_own_answer():
    users = get_user_model()
    owner = users.objects.create_user(username="autosave-conflict-owner")
    learner = users.objects.create_user(username="autosave-conflict-learner")
    attempt = _attempt(owner, learner)
    item = attempt.items.get()
    request_id = uuid4()
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"text": "first"},
        expected_version=0,
        request_id=request_id,
    )
    with pytest.raises(AttemptAnswerConflict, match="different input"):
        save_attempt_answer(
            actor=learner,
            attempt=attempt,
            item_key=item.key,
            answer={"text": "changed"},
            expected_version=0,
            request_id=request_id,
        )
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"text": "latest"},
        expected_version=1,
        request_id=uuid4(),
    )
    with pytest.raises(AttemptAnswerConflict) as caught:
        save_attempt_answer(
            actor=learner,
            attempt=attempt,
            item_key=item.key,
            answer={"text": "old tab"},
            expected_version=1,
            request_id=uuid4(),
        )
    assert caught.value.current == {"item_key": str(item.key), "version": 2, "answer": {"text": "latest"}}
    assert AnswerRevision.objects.filter(item=item).count() == 2


@pytest.mark.django_db
def test_storage_failure_rolls_back_new_revision_and_keeps_previous_history(monkeypatch):
    users = get_user_model()
    owner = users.objects.create_user(username="autosave-rollback-owner")
    learner = users.objects.create_user(username="autosave-rollback-learner")
    attempt = _attempt(owner, learner)
    item = attempt.items.get()
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"text": "kept"},
        expected_version=0,
        request_id=uuid4(),
    )

    def fail_create(*args, **kwargs):
        raise RuntimeError("simulated answer storage failure")

    monkeypatch.setattr(AnswerRevision.objects, "create", fail_create)
    with pytest.raises(RuntimeError, match="storage failure"):
        save_attempt_answer(
            actor=learner,
            attempt=attempt,
            item_key=item.key,
            answer={"text": "not persisted"},
            expected_version=1,
            request_id=uuid4(),
        )
    assert list(AnswerRevision.objects.filter(item=item).values_list("version", "answer")) == [
        (1, {"text": "kept"})
    ]


@pytest.mark.django_db
def test_invalid_wrong_item_finalized_and_expired_saves_create_no_revision():
    users = get_user_model()
    owner = users.objects.create_user(username="autosave-boundary-owner")
    learner = users.objects.create_user(username="autosave-boundary-learner")
    other = users.objects.create_user(username="autosave-boundary-other")
    attempt = _attempt(owner, learner)
    item = attempt.items.get()

    with pytest.raises(ClassroomError, match="not found"):
        save_attempt_answer(
            actor=learner,
            attempt=attempt,
            item_key=uuid4(),
            answer={"text": "wrong"},
            expected_version=0,
            request_id=uuid4(),
        )
    with pytest.raises(ClassroomError, match="permission"):
        save_attempt_answer(
            actor=other,
            attempt=attempt,
            item_key=item.key,
            answer={"text": "intruder"},
            expected_version=0,
            request_id=uuid4(),
        )
    attempt.status = AssessmentAttempt.Status.SUBMITTED
    attempt.save(update_fields=["status"])
    with pytest.raises(AttemptAnswerConflict, match="finalized"):
        save_attempt_answer(
            actor=learner,
            attempt=attempt,
            item_key=item.key,
            answer={"text": "after"},
            expected_version=0,
            request_id=uuid4(),
        )
    assert AnswerRevision.objects.filter(item=item).count() == 0

    fresh = _attempt(owner, learner)
    fresh.deadline_at = timezone.now() - timedelta(seconds=1)
    fresh.save(update_fields=["deadline_at"])
    with pytest.raises(AttemptAnswerConflict, match="deadline"):
        save_attempt_answer(
            actor=learner,
            attempt=fresh,
            item_key=fresh.items.get().key,
            answer={"text": "late"},
            expected_version=0,
            request_id=uuid4(),
        )
    assert AnswerRevision.objects.filter(item=fresh.items.get()).count() == 0


@pytest.mark.django_db
def test_answer_api_returns_only_own_answer_and_rejects_stale_version():
    users = get_user_model()
    owner = users.objects.create_user(username="autosave-api-owner")
    learner = users.objects.create_user(username="autosave-api-learner")
    attempt = _attempt(owner, learner)
    item = attempt.items.get()
    client = Client()
    client.force_login(learner)
    url = reverse("liveclassroom:api-v1-attempt-answers", args=[attempt.public_id])
    body = {
        "item_key": str(item.key),
        "expected_version": 0,
        "request_id": str(uuid4()),
        "answer": {"text": "RNA"},
    }
    response = client.post(url, data=json.dumps(body), content_type="application/json")
    assert response.status_code == 200
    assert set(response.json()) == {"item_key", "version", "answer", "saved_at", "server_now"}
    assert "score" not in response.json() and "correctness" not in response.json()
    stale = {**body, "request_id": str(uuid4()), "answer": {"text": "old"}}
    stale_response = client.post(url, data=json.dumps(stale), content_type="application/json")
    assert stale_response.status_code == 409
    assert stale_response.json()["current"]["answer"] == {"text": "RNA"}
    detail = client.get(reverse("liveclassroom:api-v1-attempt-detail", args=[attempt.public_id])).json()
    assert detail["items"][0]["answer_version"] == 1
    assert detail["items"][0]["answer"] == {"text": "RNA"}
