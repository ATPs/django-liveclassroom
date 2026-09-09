# Task 28 - Server assessment deadlines and expiry

- Task ID: `28-assessment-deadlines`
- Status: COMPLETE for package timing validation, server enforcement, and bounded expiry.
- Baseline: `58d8417` (`Add presentation cues and assessment saving`)
- Final commit: coordinator integration pending; this worker did not commit.
- The unrelated dirty `.gitignore`, `AIM.md`, `pyproject.toml` and concurrent task 27 frontend/template files remain untouched.

## Delivered behavior

- `src/liveclassroom/services/assessment_timing.py` validates `due_at`, `opens_at`,
  `closes_at`, and positive integer `duration_seconds`; rejects naive datetimes,
  booleans and invalid opening/closing order; and canonicalizes aware datetimes
  to UTC ISO-8601 strings for frozen assessment-run JSON.
- `services/assessments.py` accepts the timing settings while preserving the
  existing max-attempt, audience and pass-percent validation. Assessment-run
  publication already deep-copies settings, so later draft edits cannot change
  delivered timing.
- `services/attempts.py` checks the server clock at start/resume, permits the
  exact opening instant, rejects the exact closing instant, and derives
  `AssessmentAttempt.deadline_at` as the earlier of duration or hard close.
  An optional `now` exists only for internal deterministic tests; no API field
  can set the start/deadline/server clock.
- Existing answer-save and submission services enforce `deadline_at` with their
  server-side clocks. An exact-deadline save is rejected without creating a
  revision. Own attempt reads opportunistically finalize due attempts through
  the task-26 submission service, while expiry does not depend on a browser.
- `services/assessment_timing.py:expire_due_attempts(now=None, limit=500)` scans
  a bounded ordered batch and calls idempotent `submit_attempt(...,
  actor=None, reason="expired")`. It reports `scanned`, `expired`,
  `already_finalized`, and `failed`; lock ordering and task-26 terminal state
  prevent duplicate finalization/events when workers race.
- `management/commands/expire_assessment_attempts.py` exposes
  `python manage.py expire_assessment_attempts --limit 500`, prints counts and
  returns a management-command failure when any candidate failed. Hosts can
  schedule this once per minute with their existing cron/systemd/job mechanism;
  task 53 owns actual host activation.

## Migration and dependencies

No migration was necessary. `AssessmentDefinition.settings` already stores the
frozen draft settings and `AssessmentAttempt.deadline_at` was added by task 24's
`0012_assessment_attempts` migration. `makemigrations --check --dry-run`
reports no changes, preserving the current leaf `0013_attempt_answer_revisions`
and all populated migration history.

## Verification

Passed in zsh with conda `base`, `/data/p/bin` on `PATH`, and `PYTHONPATH=.:src`:

- `pytest -q tests/test_assessment_timing.py` - 5 passed.
- `pytest -q tests/test_assessment_timing.py tests/test_assessment_definitions.py tests/test_assessment_attempts.py tests/test_attempt_autosave.py tests/test_attempt_submission.py` - 24 passed.
- `ruff check` on all changed package/service/API/command/test paths - passed.
- `python -m compileall -q src/liveclassroom tests/test_assessment_timing.py` - passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py check` - passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run` - no changes detected.
- `git diff --check` - passed.

Browser screenshots and browser timing interaction were not run in this backend
worker. PostgreSQL concurrency, multi-worker load, host migration, scheduler
activation, deployment, restart, and production behavior remain unverified.

## Next eligible work

Task 29 may freeze section/pool candidate revisions. Task 31 may subscribe to
the durable `attempt_submitted` event and grade expired/manual submissions.
Task 53 may prepare and, only with explicit activation authority, apply the host
migration/static/restart/scheduler rollout.
