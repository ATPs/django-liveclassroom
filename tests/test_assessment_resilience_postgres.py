"""Assessment recovery acceptance across task-owned ASGI workers.

The test deliberately keeps WebSockets unavailable while assessment writes are
accepted. HTTP and the database remain authoritative for saved answers,
submission, expiry, and grading after a worker restart.
"""

import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from liveclassroom.models import (
    AnswerRevision,
    AssessmentAttempt,
    AssessmentAttemptGrade,
    AssessmentGradeDecision,
    AssessmentItemGrade,
)
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.classroom import create_activity_definition

from .test_multiworker_classroom import (
    _free_port,
    _restart_worker,
    _spawn_worker,
    _timed_request,
    _wait_for_health,
)


def _require_postgres():
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL for assessment resilience acceptance")
    pytest.importorskip("uvicorn")


def _assessment(owner, *, title):
    question = create_activity_definition(
        owner=owner,
        title=f"{title} question",
        type_key="numeric",
        definition={"prompt": "Enter the value", "answer": 10, "tolerance": "0"},
    )
    draft = create_assessment(
        actor=owner,
        data={
            "title": title,
            "settings": {"max_attempts": 1, "audience": "authenticated_link"},
            "items": [{"revision_id": question.current_revision_id, "points": "2"}],
        },
    )
    return publish_assessment(actor=owner, assessment=draft, expected_version=draft.version)


def _cookie(user):
    from django.test import Client

    client = Client()
    client.force_login(user)
    return f"{settings.SESSION_COOKIE_NAME}={client.cookies[settings.SESSION_COOKIE_NAME].value}"


def _json_request(base_url, path, *, cookie, payload=None, key=None):
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    return _timed_request(f"{base_url}{path}", cookie=cookie, body=body, key=key)


def _scheduler(env, command, *, limit=10):
    result = subprocess.run(
        [sys.executable, "standalone/manage.py", command, "--limit", str(limit)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


@pytest.mark.django_db(transaction=True)
def test_two_assessments_recover_saves_restart_expiry_and_grades_without_sockets(tmp_path: Path):
    _require_postgres()
    users = get_user_model()
    owner = users.objects.create_user(username=f"task52-assessment-owner-{uuid4().hex[:8]}")
    learner_one = users.objects.create_user(username=f"task52-assessment-learner1-{uuid4().hex[:8]}")
    learner_two = users.objects.create_user(username=f"task52-assessment-learner2-{uuid4().hex[:8]}")
    runs = [
        _assessment(owner, title="Resilience assessment one"),
        _assessment(owner, title="Resilience assessment two"),
    ]
    cookies = [_cookie(learner_one), _cookie(learner_two)]
    db_name = str(connection.settings_dict["NAME"])
    repo_root = Path(__file__).resolve().parents[1]
    ports = [_free_port(), _free_port()]
    while ports[1] == ports[0]:
        ports[1] = _free_port()
    base_urls = [f"http://127.0.0.1:{port}" for port in ports]
    logs = [tmp_path / f"task52-assessment-worker-{index}.log" for index in range(2)]
    worker_env = os.environ.copy()
    worker_env.update(
        {
            "DJANGO_SETTINGS_MODULE": "tests.postgres_settings",
            "LIVECLASSROOM_POSTGRES_NAME": db_name,
            "LIVECLASSROOM_POSTGRES_TEST_NAME": db_name,
            "PYTHONPATH": ".:src",
        }
    )
    workers = []
    timings = []
    attempts = []
    try:
        for port, log_path in zip(ports, logs):
            workers.append(_spawn_worker(repo_root=repo_root, env=worker_env, port=port, log_path=log_path))
        deadline = time.monotonic() + 45
        for base_url, worker in zip(base_urls, workers):
            _wait_for_health(base_url, worker, deadline)

        # Start and autosave each run through a different worker. No assessment
        # socket is opened; this models a browser with notification transport
        # unavailable while HTTP writes continue to be acknowledged.
        for index, (run, cookie) in enumerate(zip(runs, cookies)):
            started = time.monotonic()
            status, raw, replay, _elapsed = _json_request(
                base_urls[index],
                reverse("liveclassroom:api-v1-assessment-attempts", args=[run.public_id]),
                cookie=cookie,
                payload={"request_id": str(uuid4())},
                key=f"task52-start-{index}",
            )
            assert status == 201, (status, raw, replay)
            payload = json.loads(raw)
            attempts.append(payload)
            item = payload["items"][0]
            status, raw, _replay, _elapsed = _json_request(
                base_urls[index],
                reverse("liveclassroom:api-v1-attempt-answers", args=[payload["id"]]),
                cookie=cookie,
                payload={
                    "item_key": item["key"],
                    "expected_version": 0,
                    "request_id": str(uuid4()),
                    "answer": {"value": "11"},
                },
                key=f"task52-save-{index}",
            )
            assert status == 200, (status, raw)
            saved = json.loads(raw)
            assert saved["version"] == 1
            timings.append((time.monotonic() - started) * 1000)

        # Restart worker zero after both writes. The replacement must recover
        # the first accepted answer via the database-backed detail endpoint.
        workers[0] = _restart_worker(
            worker=workers[0],
            port=ports[0],
            repo_root=repo_root,
            env=worker_env,
            log_path=logs[0],
            base_url=base_urls[0],
        )
        status, raw, _replay, _elapsed = _json_request(
            base_urls[0],
            reverse("liveclassroom:api-v1-attempt-detail", args=[attempts[0]["id"]]),
            cookie=cookies[0],
        )
        assert status == 200, (status, raw)
        recovered = json.loads(raw)
        assert recovered["items"][0]["answer_version"] == 1
        assert recovered["items"][0]["answer"] == {"value": 11.0}

        # Submit one attempt after restart. The second remains open until the
        # scheduler finalizes it, exercising both legal terminal paths.
        status, raw, _replay, _elapsed = _json_request(
            base_urls[0],
            reverse("liveclassroom:api-v1-attempt-submit", args=[attempts[0]["id"]]),
            cookie=cookies[0],
            payload={
                "request_id": str(uuid4()),
                "expected_versions": {attempts[0]["items"][0]["key"]: 1},
            },
            key="task52-submit-one",
        )
        assert status == 200, (status, raw)

        second_attempt = AssessmentAttempt.objects.get(public_id=attempts[1]["id"])
        second_attempt.deadline_at = timezone.now() - timedelta(seconds=1)
        second_attempt.save(update_fields=["deadline_at"])

        scheduler_env = worker_env.copy()
        scheduler_env["LIVECLASSROOM_POSTGRES_NAME"] = db_name
        scheduler_env["LIVECLASSROOM_POSTGRES_TEST_NAME"] = db_name
        code, output, error = _scheduler(scheduler_env, "expire_assessment_attempts")
        assert code == 0, (output, error)
        assert "scanned=1" in output and "expired=1" in output
        code, output, error = _scheduler(scheduler_env, "expire_assessment_attempts")
        assert code == 0, (output, error)
        assert output == "scanned=0 expired=0 already_finalized=0 failed=0"

        code, output, error = _scheduler(scheduler_env, "grade_pending_attempts")
        assert code == 0, (output, error)
        assert "graded=2" in output

        first_attempt = AssessmentAttempt.objects.get(public_id=attempts[0]["id"])
        second_attempt.refresh_from_db()
        assert first_attempt.status == AssessmentAttempt.Status.SUBMITTED
        assert second_attempt.status == AssessmentAttempt.Status.SUBMITTED
        assert second_attempt.finalization_reason == "expired"
        for attempt_payload in attempts:
            attempt = AssessmentAttempt.objects.get(public_id=attempt_payload["id"])
            item = attempt.items.get()
            assert AnswerRevision.objects.filter(item=item).count() == 1
            assert AssessmentItemGrade.objects.filter(item=item).count() == 1
            assert AssessmentAttemptGrade.objects.filter(attempt=attempt).count() == 1
            assert AssessmentGradeDecision.objects.filter(attempt=attempt).count() == 1
        print(
            f"2 assessment runs, 2 acknowledged saves, 1 worker restart, sockets=0, "
            f"save p50={sorted(timings)[0]:.1f}ms p95={sorted(timings)[-1]:.1f}ms"
        )
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=10)
