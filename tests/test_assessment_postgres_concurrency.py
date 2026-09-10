"""Real PostgreSQL races for attempts, grading and named content shares.

These tests intentionally use independent Django connections in each worker.
SQLite runs skip them because its locking behavior cannot prove the package's
cross-worker PostgreSQL contract.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.utils import timezone

from liveclassroom.models import (
    AnswerRevision,
    AssessmentAttempt,
    AssessmentAttemptGrade,
    AssessmentGradeDecision,
    AssessmentItemGrade,
    ContentShare,
    GradingRuleRevision,
)
from liveclassroom.services.assessment_grading import grade_submitted_attempt
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessment_timing import expire_due_attempts, finalize_due_attempt
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempt_submission import AttemptSubmissionConflict, submit_attempt
from liveclassroom.services.attempts import AttemptAnswerConflict, save_attempt_answer, start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.grade_corrections import regrade_attempts
from liveclassroom.services.sharing import (
    ContentShareError,
    copy_shared_content,
    create_share,
    revoke_share,
    shared_resource,
)


def _require_postgres():
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL for cross-worker row-lock coverage")


def _close_worker_connections():
    """Ensure each thread gets a connection independent of the test thread."""
    connections.close_all()


def _run(owner, *, type_key="short_text", definition=None, points="2"):
    definition = definition or {"prompt": "Answer"}
    question = create_activity_definition(
        owner=owner,
        title=f"Concurrent question {uuid4().hex[:8]}",
        type_key=type_key,
        definition=definition,
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": f"Concurrent assessment {uuid4().hex[:8]}",
            "settings": {"max_attempts": 1, "audience": "authenticated_link"},
            "items": [{"revision_id": question.current_revision_id, "points": points}],
        },
    )
    return publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)


def _submitted_attempt(*, owner, learner, type_key="short_text", definition=None, points="2", answer=None):
    run = _run(owner, type_key=type_key, definition=definition, points=points)
    attempt, created = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    assert created
    item = attempt.items.get()
    if answer is not None:
        save_attempt_answer(
            actor=learner,
            attempt=attempt,
            item_key=item.key,
            answer=answer,
            expected_version=0,
            request_id=uuid4(),
        )
        expected_versions = {str(item.key): 1}
    else:
        expected_versions = None
    submit_attempt(
        actor=learner,
        attempt=attempt,
        request_id=uuid4(),
        expected_versions=expected_versions,
    )
    attempt.refresh_from_db()
    assert attempt.status == AssessmentAttempt.Status.SUBMITTED
    return run, attempt, item


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_starts_allocate_one_active_attempt_and_two_receipts():
    _require_postgres()
    users = get_user_model()
    owner = users.objects.create_user(username=f"pg-start-owner-{uuid4().hex[:8]}")
    learner = users.objects.create_user(username=f"pg-start-learner-{uuid4().hex[:8]}")
    run = _run(owner)
    barrier = Barrier(2, timeout=15)

    def start(request_id):
        _close_worker_connections()
        try:
            barrier.wait()
            attempt, created = start_or_resume_attempt(
                actor=users.objects.get(pk=learner.pk), run=run, request_id=request_id
            )
            return attempt.pk, created
        finally:
            _close_worker_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, (uuid4(), uuid4())))

    assert len({result[0] for result in results}) == 1
    assert sorted(result[1] for result in results) == [False, True]
    assert AssessmentAttempt.objects.filter(run=run, user=learner, status="in_progress").count() == 1
    assert run.start_receipts.filter(user=learner).count() == 2


@pytest.mark.django_db(transaction=True)
def test_postgres_duplicate_answer_saves_preserve_one_winner_and_stale_conflict():
    _require_postgres()
    users = get_user_model()
    owner = users.objects.create_user(username=f"pg-save-owner-{uuid4().hex[:8]}")
    learner = users.objects.create_user(username=f"pg-save-learner-{uuid4().hex[:8]}")
    run = _run(owner)
    attempt, _ = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    item = attempt.items.get()
    barrier = Barrier(2, timeout=15)

    def save(answer):
        _close_worker_connections()
        try:
            barrier.wait()
            try:
                revision = save_attempt_answer(
                    actor=users.objects.get(pk=learner.pk),
                    attempt=AssessmentAttempt(pk=attempt.pk),
                    item_key=item.key,
                    answer={"text": answer},
                    expected_version=0,
                    request_id=uuid4(),
                )
            except AttemptAnswerConflict as exc:
                return ("conflict", exc.code)
            return ("saved", revision.pk)
        finally:
            _close_worker_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ("first", "second")))

    assert sorted(result[0] for result in results) == ["conflict", "saved"]
    assert results[0][1] == "stale_revision" or results[1][1] == "stale_revision"
    revisions = list(item.answer_revisions.order_by("version").values("version", "answer"))
    assert revisions and len(revisions) == 1
    assert revisions[0]["version"] == 1
    assert revisions[0]["answer"]["text"] in {"first", "second"}
    assert AnswerRevision.objects.filter(item=item).count() == 1


@pytest.mark.django_db(transaction=True)
def test_postgres_save_submit_race_has_one_legal_order_and_finalizes_once():
    _require_postgres()
    users = get_user_model()
    owner = users.objects.create_user(username=f"pg-submit-owner-{uuid4().hex[:8]}")
    learner = users.objects.create_user(username=f"pg-submit-learner-{uuid4().hex[:8]}")
    run = _run(owner)
    attempt, _ = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    item = attempt.items.get()
    barrier = Barrier(2, timeout=15)

    def save():
        _close_worker_connections()
        try:
            barrier.wait()
            try:
                revision = save_attempt_answer(
                    actor=users.objects.get(pk=learner.pk),
                    attempt=AssessmentAttempt(pk=attempt.pk),
                    item_key=item.key,
                    answer={"text": "accepted before submit"},
                    expected_version=0,
                    request_id=uuid4(),
                )
                return ("saved", revision.pk)
            except AttemptAnswerConflict as exc:
                return ("save_conflict", exc.code)
        finally:
            _close_worker_connections()

    def submit():
        _close_worker_connections()
        try:
            barrier.wait()
            try:
                result = submit_attempt(
                    actor=users.objects.get(pk=learner.pk),
                    attempt=AssessmentAttempt(pk=attempt.pk),
                    request_id=uuid4(),
                    expected_versions={str(item.key): 0},
                )
                return ("submitted", result.finalized_now)
            except AttemptSubmissionConflict as exc:
                return ("submit_conflict", exc.code)
        finally:
            _close_worker_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        save_result = pool.submit(save)
        submit_result = pool.submit(submit)
        results = [save_result.result(timeout=30), submit_result.result(timeout=30)]

    assert {result[0] for result in results} in (
        {"saved", "submit_conflict"},
        {"save_conflict", "submitted"},
    )
    if results[0][0] == "saved":
        assert results[1] == ("submit_conflict", "stale_revision")
        submit_attempt(
            actor=learner,
            attempt=attempt,
            request_id=uuid4(),
            expected_versions={str(item.key): 1},
        )
    else:
        assert results[0] == ("save_conflict", "attempt_closed")
    attempt.refresh_from_db()
    assert attempt.status == AssessmentAttempt.Status.SUBMITTED
    assert AnswerRevision.objects.filter(item=item).count() in {0, 1}
    assert AssessmentAttempt.objects.filter(pk=attempt.pk, status="submitted").count() == 1


@pytest.mark.django_db(transaction=True)
def test_postgres_expiry_workers_finalize_one_attempt_once():
    _require_postgres()
    users = get_user_model()
    owner = users.objects.create_user(username=f"pg-expiry-owner-{uuid4().hex[:8]}")
    learner = users.objects.create_user(username=f"pg-expiry-learner-{uuid4().hex[:8]}")
    run = _run(owner)
    attempt, _ = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    deadline = timezone.now() - timedelta(minutes=1)
    attempt.deadline_at = deadline
    attempt.save(update_fields=["deadline_at"])
    barrier = Barrier(2, timeout=15)

    def expire():
        _close_worker_connections()
        try:
            barrier.wait()
            loaded = AssessmentAttempt.objects.get(pk=attempt.pk)
            return finalize_due_attempt(attempt=loaded, now=deadline)
        finally:
            _close_worker_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _value: expire(), (1, 2)))

    assert sum(getattr(result, "finalized_now", False) for result in results) == 1
    assert sum(getattr(result, "finalized_now", False) is False for result in results) == 1
    attempt.refresh_from_db()
    assert attempt.status == AssessmentAttempt.Status.SUBMITTED
    assert attempt.finalization_reason == "expired"
    assert attempt.submitted_at == deadline
    assert expire_due_attempts(now=deadline, limit=500) == {
        "scanned": 0,
        "expired": 0,
        "already_finalized": 0,
        "failed": 0,
    }


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_grading_is_idempotent_and_regrading_keeps_audit_history():
    _require_postgres()
    users = get_user_model()
    owner = users.objects.create_user(username=f"pg-grade-owner-{uuid4().hex[:8]}")
    learner = users.objects.create_user(username=f"pg-grade-learner-{uuid4().hex[:8]}")
    run, attempt, item = _submitted_attempt(
        owner=owner,
        learner=learner,
        type_key="numeric",
        definition={"prompt": "Value", "answer": 10, "tolerance": "0"},
        answer={"value": "11"},
    )
    # The submission callback may have graded already. Reset only this task's
    # rows so both workers race the same ungraded submitted attempt.
    AssessmentGradeDecision.objects.filter(attempt=attempt).delete()
    AssessmentItemGrade.objects.filter(item=item).delete()
    AssessmentAttemptGrade.objects.filter(attempt=attempt).delete()
    barrier = Barrier(2, timeout=15)

    def grade():
        _close_worker_connections()
        try:
            barrier.wait()
            aggregate = grade_submitted_attempt(attempt=AssessmentAttempt(pk=attempt.pk))
            return aggregate.awarded_points
        finally:
            _close_worker_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        grade_results = list(pool.map(lambda _value: grade(), (1, 2)))

    assert grade_results == [grade_results[0], grade_results[0]]
    assert grade_results[0] == 0
    assert AssessmentGradeDecision.objects.filter(attempt=attempt).count() == 1

    barrier = Barrier(2, timeout=15)

    def regrade():
        _close_worker_connections()
        try:
            barrier.wait()
            return regrade_attempts(
                run=run,
                item_keys=[str(item.key)],
                rule_version="activity-registry-v2",
                rule_config={"answer": 11},
                actor=users.objects.get(pk=owner.pk),
                reason="Concurrent answer-key review.",
            )
        finally:
            _close_worker_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        regrade_results = list(pool.map(lambda _value: regrade(), (1, 2)))

    assert sum(result["changed"] for result in regrade_results) == 1, regrade_results
    assert sum(result["unchanged"] for result in regrade_results) == 1, regrade_results
    assert GradingRuleRevision.objects.filter(run=run, item_key=item.key).count() == 2
    assert AssessmentGradeDecision.objects.filter(attempt=attempt).count() == 2
    item.refresh_from_db()
    assert item.grade.normalized_score == 1
    assert item.grade.awarded_points == 2
    assert AssessmentAttemptGrade.objects.get(attempt=attempt).awarded_points == 2


@pytest.mark.django_db(transaction=True)
def test_postgres_share_revocation_race_blocks_future_reads_and_preserves_existing_copy():
    _require_postgres()
    users = get_user_model()
    owner = users.objects.create_user(username=f"pg-share-owner-{uuid4().hex[:8]}")
    recipient = users.objects.create_user(username=f"pg-share-recipient-{uuid4().hex[:8]}")
    source = create_activity_definition(
        owner=owner,
        title="Shared source",
        type_key="short_text",
        definition={"prompt": "Private prompt"},
    )
    share = create_share(actor=owner, kind="question", object_id=source.pk, recipient=recipient)
    copied = copy_shared_content(actor=recipient, share=share).activities[0]
    barrier = Barrier(2, timeout=15)

    def read_share():
        _close_worker_connections()
        try:
            barrier.wait()
            try:
                resource = shared_resource(
                    actor=users.objects.get(pk=recipient.pk), share=ContentShare(pk=share.pk)
                )
                return ("read", resource.pk)
            except ContentShareError:
                return ("blocked", None)
        finally:
            _close_worker_connections()

    def revoke():
        _close_worker_connections()
        try:
            barrier.wait()
            revoke_share(actor=users.objects.get(pk=owner.pk), share=ContentShare(pk=share.pk))
            return "revoked"
        finally:
            _close_worker_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        read_result = pool.submit(read_share)
        revoke_result = pool.submit(revoke)
        result = read_result.result(timeout=30)
        assert revoke_result.result(timeout=30) == "revoked"

    share.refresh_from_db()
    copied.refresh_from_db()
    assert share.revoked_at is not None
    assert result[0] in {"read", "blocked"}
    assert copied.owner_id == recipient.pk
    assert copied.current_revision.payload == source.current_revision.payload
    with pytest.raises(ContentShareError):
        shared_resource(actor=recipient, share=share)
