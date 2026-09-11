from datetime import UTC, datetime, timedelta
from datetime import timezone as dt_timezone
from io import StringIO
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core import management
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from liveclassroom.models import AssessmentAttempt
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessment_timing import expire_due_attempts
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import AttemptAnswerConflict, save_attempt_answer, start_or_resume_attempt
from liveclassroom.services.classroom import ClassroomError, create_activity_definition


def _question(owner):
    return create_activity_definition(
        owner=owner,
        title="Timing question",
        type_key="short_text",
        definition={"prompt": "Answer"},
    )


def _run(owner, *, settings):
    question = _question(owner)
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Timed assessment",
            "settings": settings,
            "items": [{"revision_id": question.current_revision_id}],
        },
    )
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


@pytest.mark.django_db
def test_timing_settings_are_validated_and_frozen_as_utc_json():
    owner = get_user_model().objects.create_user(username="timing-settings-owner")
    opens = datetime(2026, 9, 10, 8, 0, tzinfo=dt_timezone(timedelta(hours=8)))
    closes = datetime(2026, 9, 10, 10, 0, tzinfo=dt_timezone(timedelta(hours=8)))
    due = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    run = _run(
        owner,
        settings={
            "opens_at": opens,
            "closes_at": closes,
            "due_at": due,
            "duration_seconds": 3600,
        },
    )
    settings = run.manifest["settings"]
    assert settings["opens_at"] == "2026-09-10T00:00:00+00:00"
    assert settings["closes_at"] == "2026-09-10T02:00:00+00:00"
    assert settings["due_at"] == "2026-09-11T10:00:00+00:00"
    assert settings["duration_seconds"] == 3600

    for invalid in (
        {"opens_at": "2026-09-10T08:00:00"},
        {"duration_seconds": True},
        {"duration_seconds": 0},
        {
            "opens_at": "2026-09-10T02:00:00+00:00",
            "closes_at": "2026-09-10T02:00:00+00:00",
        },
    ):
        with pytest.raises(ClassroomError):
            _run(owner, settings=invalid)

    # A source-draft mutation after publication cannot alter the frozen run.
    run.source_assessment.settings["duration_seconds"] = 5
    run.source_assessment.save(update_fields=["settings"])
    run.refresh_from_db()
    assert run.manifest["settings"]["duration_seconds"] == 3600


@pytest.mark.django_db
def test_start_open_boundary_and_deadline_use_server_time():
    owner = get_user_model().objects.create_user(username="timing-start-owner")
    learner = get_user_model().objects.create_user(username="timing-start-learner")
    opens = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    closes = opens + timedelta(minutes=10)
    run = _run(owner, settings={"opens_at": opens, "closes_at": closes, "duration_seconds": 120})

    with pytest.raises(ClassroomError, match="not open"):
        start_or_resume_attempt(actor=learner, run=run, request_id=uuid4(), now=opens - timedelta(seconds=1))
    attempt, created = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4(), now=opens)
    assert created
    assert attempt.deadline_at == min(attempt.started_at + timedelta(seconds=120), closes)

    closed_run = _run(owner, settings={"closes_at": closes})
    with pytest.raises(ClassroomError, match="closed"):
        start_or_resume_attempt(actor=learner, run=closed_run, request_id=uuid4(), now=closes)


@pytest.mark.django_db
def test_save_at_exact_deadline_is_rejected_and_previous_answer_is_retained(monkeypatch):
    owner = get_user_model().objects.create_user(username="timing-save-owner")
    learner = get_user_model().objects.create_user(username="timing-save-learner")
    run = _run(owner, settings={})
    attempt, _ = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    item = attempt.items.get()
    first = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    deadline = first + timedelta(minutes=5)
    attempt.deadline_at = deadline
    attempt.save(update_fields=["deadline_at"])
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"text": "kept"},
        expected_version=0,
        request_id=uuid4(),
        now=first,
    )
    with pytest.raises(AttemptAnswerConflict, match="deadline"):
        save_attempt_answer(
            actor=learner,
            attempt=attempt,
            item_key=item.key,
            answer={"text": "late"},
            expected_version=1,
            request_id=uuid4(),
            now=deadline,
        )
    # The attempt-detail endpoint finalizes due attempts using the server
    # clock. Freeze that same clock for this whole boundary scenario rather
    # than letting the assertion depend on the date the suite is run.
    monkeypatch.setattr("liveclassroom.services.assessment_timing.timezone.now", lambda: first)
    detail = Client()
    detail.force_login(learner)
    assert detail.get(reverse("liveclassroom:api-v1-attempt-detail", args=[attempt.public_id])).status_code == 200
    attempt.refresh_from_db()
    assert attempt.status == AssessmentAttempt.Status.IN_PROGRESS
    assert list(item.answer_revisions.values_list("answer", flat=True)) == [{"text": "kept"}]

    monkeypatch.setattr("liveclassroom.services.assessment_timing.timezone.now", lambda: deadline)
    assert detail.get(reverse("liveclassroom:api-v1-attempt-detail", args=[attempt.public_id])).status_code == 200
    attempt.refresh_from_db()
    assert attempt.status == AssessmentAttempt.Status.SUBMITTED
    assert attempt.finalization_reason == "expired"


@pytest.mark.django_db
def test_expiry_is_browser_independent_bounded_and_idempotent():
    owner = get_user_model().objects.create_user(username="timing-expiry-owner")
    learner = get_user_model().objects.create_user(username="timing-expiry-learner")
    run = _run(owner, settings={})
    attempt, _ = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    item = attempt.items.get()
    deadline = timezone.now() - timedelta(minutes=1)
    attempt.deadline_at = deadline
    attempt.save(update_fields=["deadline_at"])
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=item.key,
        answer={"text": "before close"},
        expected_version=0,
        request_id=uuid4(),
        now=deadline - timedelta(seconds=1),
    )

    first = expire_due_attempts(now=deadline, limit=500)
    second = expire_due_attempts(now=deadline, limit=500)
    assert first["expired"] == 1
    assert first["failed"] == 0
    assert second == {"scanned": 0, "expired": 0, "already_finalized": 0, "failed": 0}
    attempt.refresh_from_db()
    assert attempt.status == AssessmentAttempt.Status.SUBMITTED
    assert attempt.finalization_reason == "expired"
    assert attempt.submitted_at == deadline
    assert item.answer_revisions.get().answer == {"text": "before close"}


@pytest.mark.django_db
def test_expiry_management_command_reports_counts_and_rejects_bad_limit():
    owner = get_user_model().objects.create_user(username="timing-command-owner")
    learner = get_user_model().objects.create_user(username="timing-command-learner")
    run = _run(owner, settings={})
    attempt, _ = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    attempt.deadline_at = timezone.now() - timedelta(seconds=1)
    attempt.save(update_fields=["deadline_at"])
    output = StringIO()
    management.call_command("expire_assessment_attempts", limit=500, stdout=output)
    assert "expired=1" in output.getvalue()
    with pytest.raises(management.CommandError):
        management.call_command("expire_assessment_attempts", limit=0, stdout=StringIO())
