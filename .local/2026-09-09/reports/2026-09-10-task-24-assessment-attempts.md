# Task 24 authenticated assessment attempts

- Task ID: 24
- Status: COMPLETE for authenticated start/resume and private own-attempt read; autosave, submission, timing and grading remain later tasks.
- Baseline: `cb1caaf`
- Final commit: coordinator commit pending.

## Implementation

- Added additive migration `0012_assessment_attempts` with independent attempt, immutable assigned-item and start-command receipt models. It preserves the live `Submission` tables.
- Start/resume locks the assessment run, repeats audience admission, preserves one active attempt per run/user, enforces frozen limits and copies the exact run-item manifest and order once.
- A request UUID replays its original start result. After a submitted attempt, a new attempt requires explicit `new_attempt: true`; normal inspection never creates attendance or an attempt.
- Student APIs only return the caller's own assigned prompt/options/metadata and saved-answer placeholders. Answer keys, explanations, feedback and other learner identity are absent. Revoked class membership blocks resume while retaining historical rows.

## Verification

Passed:

- `pytest -q tests/test_assessment_attempts.py tests/test_assessment_runs.py tests/test_assessment_definitions.py` — 11 passed
- `python standalone/manage.py check`
- `python standalone/manage.py makemigrations --check --dry-run`
- `python -m compileall -q src tests standalone`
- focused Ruff and `git diff --check`

No browser, host, PostgreSQL concurrency, deployment, migration application or service restart was performed.

## Next eligible work

Task 25 adds append-only answer revisions and retry-safe autosave; task 26 then finalizes a submitted attempt.
