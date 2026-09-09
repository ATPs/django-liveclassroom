# Task 26 — Idempotent final submission and immutable answers

- Task ID: `26-attempt-submission`
- Status: COMPLETE (implementation and focused checks; coordinator integration pending)
- Baseline commit: `6cf5e8e6a764caae6d9677fb2d47373a0e8575f0`
- Final commit: not committed; the coordinator owns the shared main checkout commit.

## Changed paths and final interfaces

- `src/liveclassroom/services/attempt_submission.py` adds
  `submit_attempt(actor, attempt, request_id, expected_versions=None, now=None,
  reason="student")`, `AttemptSubmissionConflict`, and the post-commit
  `attempt_submitted`/`attempt_finalized` signal aliases.  It locks the attempt
  then items, checks acknowledged answer versions, finalizes once, retains
  immutable revisions, and returns a stable own-result mapping.
- `src/liveclassroom/api_attempts.py` and `src/liveclassroom/urls.py` add
  `POST api/v1/attempts/<uuid>/submit/`.  The public body accepts only
  `request_id` and optional `expected_versions`; client clocks and reasons are
  rejected.
- `src/liveclassroom/services/attempts.py` includes `finalization_reason` in
  own-attempt payloads.
- `tests/test_attempt_submission.py` covers empty answers, stable duplicate
  submission, last-save inclusion, immutable post-submit writes, version
  conflicts, foreign actors, expiry effective time, API input boundaries, and
  one post-commit event.

## Prerequisite and migration evidence

Task 25's `AnswerRevision` and `AttemptAnswerReceipt` implementation and
`0013_attempt_answer_revisions` migration are present in the shared checkout.
Task 26 required no additional migration: existing `AssessmentAttempt.status`,
`submitted_at`, and `finalization_reason` fields are sufficient for the one
terminal transition.  No migration leaf changed.

## Verification

Passed:

- `source /data/p/anaconda3/etc/profile.d/conda.sh && conda activate django && export PATH="/data/p/bin:$PATH" PYTHONPATH=.:src && pytest -q tests/test_attempt_submission.py tests/test_attempt_autosave.py` — **11 passed**.
- Same environment, `ruff check src/liveclassroom/services/attempt_submission.py src/liveclassroom/api_attempts.py src/liveclassroom/services/attempts.py tests/test_attempt_submission.py` — passed.

Not run in this focused worker pass: full suite, compileall, browser, host,
PostgreSQL concurrency, load, and distribution checks.  The service/API tests
do not prove those environments.

## Open follow-ups

Task 28 can call `submit_attempt(..., actor=None, reason="expired", now=...)`
for due attempts; it should preserve the deadline as the effective submitted
time.  Task 31 can subscribe to `attempt_submitted` and trigger bounded
grading recovery after durable submission.
