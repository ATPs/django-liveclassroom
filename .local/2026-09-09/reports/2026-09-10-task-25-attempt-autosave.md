# Task 25 — Durable answer revisions and retry safe autosave

- Task ID: 25
- Status: COMPLETE (implementation and focused checks)
- Baseline: `6cf5e8e` (the coordinator may integrate this working tree with the
  concurrent task batch)
- Final commit: not committed; coordinator owns the shared main checkout commit

## Changed paths and interfaces

- `src/liveclassroom/models/attempts.py` adds immutable `AnswerRevision` rows
  and attempt scoped `AttemptAnswerReceipt` rows.  Revisions are unique by
  `(item, version)` and receipts by `(attempt, request_id)`.
- `src/liveclassroom/services/attempts.py` adds
  `save_attempt_answer(actor, attempt, item_key, answer, expected_version,
  request_id, now=None)`.  It validates against the frozen registry manifest,
  appends a revision, and stores the replay receipt in one transaction.
  Saves lock the attempt before the item, matching the documented finalization
  lock order; latest answer is derived from the highest revision.
- `src/liveclassroom/api_attempts.py` and `src/liveclassroom/urls.py` add
  `POST api/v1/attempts/<uuid>/answers/`.  Success returns only
  `item_key`, `version`, `answer`, `saved_at`, and `server_now`; the own attempt
  serializer now includes the latest answer and version.
- `src/liveclassroom/models/__init__.py` exports the two new models.
- `src/liveclassroom/migrations/0013_attempt_answer_revisions.py` is the
  additive migration after `0012_assessment_attempts`.
- `tests/test_attempt_autosave.py` covers replay after a newer save, changed
  request bodies, stale tabs, invalid/unauthorized/finalized/deadline saves,
  API serialization, and own-answer reads.
- `tests/test_answer_revision_migration.py` verifies the additive migration
  preserves old attempt rows and restores migration leaf `0013` in `finally`.

## Prerequisite and migration evidence

Task 24 is present in the baseline (`AssessmentAttempt`, `AssessmentAttemptItem`,
`AttemptStartReceipt`, authenticated attempt API).  The current migration leaf
was `0012_assessment_attempts`; task 25 owns `0013_attempt_answer_revisions`.
No task 20 migration was present while this migration was generated.

## Verification

Passed:

- `pytest -q tests/test_attempt_autosave.py tests/test_answer_revision_migration.py tests/test_assessment_attempts.py` — **10 passed**.
- `ruff check` on all task 25 Python files — passed.
- `python -m compileall -q src tests standalone` — passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py check` — passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run` — passed.
- `git diff --check` — passed.

Browser, PostgreSQL concurrency, host, load, and distribution checks were not
run.  The service/API tests do not prove those environments.

## Open follow ups

Task 26 finalization must flush/lock using attempt then item, preserve these
revisions, and reject post-finalization writes. Task 27 may add the client
autosave UI while retaining request IDs and expected versions. Task 28 supplies
the server deadline/expiry command.
