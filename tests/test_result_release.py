"""Focused service tests for independent assessment result release."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from liveclassroom.models import (
    AnswerRevision,
    AssessmentAttemptGrade,
    AssessmentItemGrade,
    AssessmentRun,
)
from liveclassroom.release_policy import normalize_release_policy
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import start_or_resume_attempt
from liveclassroom.services.classroom import ClassroomError, create_activity_definition
from liveclassroom.services.result_release import (
    RELEASE_DIMENSIONS,
    ResultReleaseError,
    can_release_result,
    release_result_dimension,
    student_result_payload,
)


def _run(owner, *, release_policy=None, closes_at=None, due_at=None):
    question = create_activity_definition(
        owner=owner,
        title="Release question",
        type_key="single_choice",
        definition={
            "prompt": "Choose the organelle.",
            "options": [{"id": "a", "text": "Nucleus"}, {"id": "b", "text": "Ribosome"}],
            "answer": "a",
            "explanation": "The nucleus stores genetic material.",
        },
    )
    settings = {"audience": AssessmentRun.Audience.AUTHENTICATED_LINK}
    if release_policy is not None:
        settings["release_policy"] = release_policy
    if closes_at is not None:
        settings["closes_at"] = closes_at
    if due_at is not None:
        settings["due_at"] = due_at
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Release quiz",
            "settings": settings,
            "items": [{"revision_id": question.current_revision_id, "points": "2"}],
        },
    )
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


def _attempt(run, learner):
    attempt, created = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    assert created
    return attempt


def _submitted(attempt):
    attempt.status = "submitted"
    attempt.submitted_at = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    attempt.save(update_fields=["status", "submitted_at"])


def _grade(attempt, *, comment="Teacher note"):
    item = attempt.items.get()
    AnswerRevision.objects.create(
        item=item,
        version=1,
        answer={"choice": "b"},
        request_id=uuid4(),
        request_hash="answer-release-test",
        actor=attempt.user,
    )
    AssessmentItemGrade.objects.create(
        item=item,
        status="graded",
        normalized_score=Decimal("0"),
        possible_points=item.points,
        awarded_points=Decimal("0.00"),
        retained_answer={"choice": "b"},
        comment=comment,
    )
    return AssessmentAttemptGrade.objects.create(
        attempt=attempt,
        status="graded",
        possible_points=item.points,
        awarded_points=Decimal("0.00"),
        graded_count=1,
    )


def test_release_policy_defaults_and_rejects_unsafe_configuration():
    assert normalize_release_policy() == {dimension: "manual" for dimension in RELEASE_DIMENSIONS}
    assert normalize_release_policy({"scores": "after_submit"})["scores"] == "after_submit"
    with pytest.raises(ClassroomError, match="after_close"):
        normalize_release_policy({"scores": "after_close"})
    with pytest.raises(ClassroomError, match="Unsupported"):
        normalize_release_policy({"unknown": "manual"})
    with pytest.raises(ClassroomError, match="scores"):
        normalize_release_policy({"scores": "later"})


@pytest.mark.django_db
def test_default_is_manual_and_student_payload_is_an_allowlist():
    users = get_user_model()
    owner = users.objects.create_user(username="release-default-owner")
    learner = users.objects.create_user(username="release-default-learner")
    run = _run(owner)
    attempt = _attempt(run, learner)
    _grade(attempt)
    payload = student_result_payload(attempt=attempt)
    item = payload["items"][0]
    assert payload["released"] == {dimension: False for dimension in RELEASE_DIMENSIONS}
    assert item["prompt"] == "Choose the organelle."
    assert item["options"] == [{"id": "a", "text": "Nucleus"}, {"id": "b", "text": "Ribosome"}]
    assert "score" not in payload and "score" not in item
    assert "answer" not in item and "answer_key" not in item
    assert "explanation" not in item and "comment" not in item


@pytest.mark.django_db
def test_dimensions_release_independently_and_score_never_exposes_key():
    users = get_user_model()
    owner = users.objects.create_user(username="release-independent-owner")
    learner = users.objects.create_user(username="release-independent-learner")
    run = _run(
        owner,
        release_policy={
            "scores": "after_submit",
            "answers": "never",
            "explanations": "manual",
            "comments": "manual",
        },
    )
    attempt = _attempt(run, learner)
    _grade(attempt)
    before = student_result_payload(attempt=attempt)
    assert not before["released"]["scores"]
    assert "answer_key" not in before["items"][0]
    _submitted(attempt)
    after = student_result_payload(attempt=attempt)
    assert after["released"]["scores"]
    assert "score" in after and "answer_key" not in after["items"][0]
    assert "explanation" not in after["items"][0]


@pytest.mark.django_db
def test_after_close_uses_closes_at_and_ignores_informational_due_at():
    users = get_user_model()
    owner = users.objects.create_user(username="release-close-owner")
    learner = users.objects.create_user(username="release-close-learner")
    closes = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    run = _run(
        owner,
        release_policy={"scores": "after_close"},
        closes_at=closes,
        due_at=closes - timedelta(days=1),
    )
    attempt = _attempt(run, learner)
    assert not can_release_result(run=run, attempt=attempt, dimension="scores", now=closes - timedelta(seconds=1))
    assert can_release_result(run=run, attempt=attempt, dimension="scores", now=closes)


@pytest.mark.django_db
def test_manual_release_records_actor_time_and_can_target_one_attempt():
    users = get_user_model()
    owner = users.objects.create_user(username="release-manual-owner", is_staff=True)
    learner = users.objects.create_user(username="release-manual-learner")
    other = users.objects.create_user(username="release-manual-other")
    run = _run(owner, release_policy={"scores": "manual", "answers": "manual"})
    attempt = _attempt(run, learner)
    other_attempt = _attempt(run, other)
    _grade(attempt)
    when = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    row = release_result_dimension(
        run=run, attempt=attempt, dimension="scores", actor=owner, now=when
    )
    assert row.attempt_id == attempt.pk
    assert row.actor_id == owner.pk and row.released_at == when
    assert can_release_result(run=run, attempt=attempt, dimension="scores", actor=learner)
    assert not can_release_result(run=run, attempt=other_attempt, dimension="scores", actor=learner)
    assert not can_release_result(run=run, attempt=other_attempt, dimension="scores", actor=other)
    assert student_result_payload(attempt=attempt)["released"]["scores"]
    assert not student_result_payload(attempt=other_attempt)["released"]["scores"]


@pytest.mark.django_db
def test_run_wide_release_and_manifest_are_separate_and_target_validation_is_strict():
    users = get_user_model()
    owner = users.objects.create_user(username="release-wide-owner", is_staff=True)
    learner = users.objects.create_user(username="release-wide-learner")
    another = users.objects.create_user(username="release-wide-another")
    run = _run(owner, release_policy={"explanations": "manual"})
    attempt = _attempt(run, learner)
    other_run = _run(owner, release_policy={"explanations": "manual"})
    other_attempt = _attempt(other_run, another)
    manifest = run.manifest
    release_result_dimension(run=run, dimension="explanations", actor=owner)
    run.refresh_from_db()
    assert run.manifest == manifest
    assert can_release_result(run=run, attempt=attempt, dimension="explanations", actor=learner)
    with pytest.raises(ResultReleaseError, match="does not belong"):
        release_result_dimension(run=run, attempt=other_attempt, dimension="explanations", actor=owner)
