# Task 31 — automatic attempt grading

- Task ID: `31-automatic-attempt-grading`
- Status: COMPLETE for package implementation and focused verification.
- Baseline commit: `292f545686b324ca697d9f0e41a6df6556ee2b64`
- Final commit: coordinator integration pending; this worker did not commit.
- Preserved unrelated dirty files: `.gitignore`, `AIM.md`, and `pyproject.toml`.

## Prerequisite mapping

Task 26 supplies `AssessmentAttempt`, immutable `AnswerRevision` rows,
`submit_attempt`, and the post-commit `attempt_submitted` signal. Task 30
supplies retained `AssessmentAttemptItem.manifest` rows with stable type keys,
payloads, option IDs, and persisted points. The grading service reads only
those retained rows and never follows the mutable question revision.

## Changed paths and interfaces

- `src/liveclassroom/models/grading.py` adds `AssessmentAttemptGrade` (the
  current aggregate), `AssessmentItemGrade` (one current result per retained
  item), and `AssessmentGradeDecision` (append-only audit snapshots), with
  short aliases `AttemptGrade`, `AttemptItemGrade`, and `GradeDecision`.
- `src/liveclassroom/migrations/0015_assessment_grades.py` adds the three
  durable model tables. Migration leaf changes from `0014_assessment_sections`
  to `0015_assessment_grades`.
- `src/liveclassroom/services/assessment_grading.py` adds
  `score_retained_item(item_payload, answer=None)`,
  `grade_submitted_attempt(*, attempt, now=None)`, and
  `grade_pending_attempts(limit=500, now=None)`. Scores are converted with
  `Decimal(str(score))`, checked for finiteness and the inclusive 0..1 range,
  then scaled and quantized with `ROUND_HALF_UP` to `0.01` points.
- `src/liveclassroom/management/commands/grade_pending_attempts.py` adds the
  bounded `grade_pending_attempts --limit 500` recovery command.
- `src/liveclassroom/apps.py` imports the grading module at startup, wiring the
  task-26 post-commit signal to a best-effort automatic grading callback.
  Callback failures leave the submitted attempt and answer revisions durable;
  the recovery service retries missing results and explicitly retryable errors.
- `tests/test_assessment_grading.py` covers registry scoring, exact and partial
  choice, numeric tolerance boundaries, accepted text, decimal rounding,
  missing keys, unanswered numeric zero, malformed answers, missing graders,
  out-of-range plugin scores, submitted-state permission, immutable duplicate
  grading, aggregate pending state, and recovery idempotency.

No grading API was added, so `tests/test_assessment_grading_api.py` is
intentionally unnecessary. Result rows contain no student-release behavior or
answer-key serializer.

## Verification

Passed in the required zsh/conda-base environment with `PATH=/data/p/bin:$PATH`
and `PYTHONPATH=.:src`:

- `pytest -q tests/test_assessment_grading.py` — **11 passed**.
- `pytest -q tests/test_assessment_grading.py tests/test_attempt_submission.py tests/test_assessment_timing.py` — **22 passed**.
- `pytest -q tests/test_assessment_grading.py tests/test_attempt_submission.py tests/test_attempt_autosave.py tests/test_assessment_attempts.py tests/test_assessment_timing.py tests/test_attempt_randomization.py` — **32 passed**.
- `ruff check src/liveclassroom/models/grading.py src/liveclassroom/services/assessment_grading.py src/liveclassroom/management/commands/grade_pending_attempts.py tests/test_assessment_grading.py` — passed.
- `python -m compileall -q src tests standalone` — passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py check` — passed with no issues.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run` — `No changes detected`.
- `git diff --check` — passed.

The focused recovery test forces the post-commit grading callback to fail,
confirms the durable submitted attempt has no grade, then runs the bounded
recovery service and confirms one grade and one audit decision. A repeated
recovery call reports the existing result and creates no duplicate decision.
The exact scaling test confirms `0.5 * 3` becomes `1.50`; missing keys remain
`ungraded` with a null score; a populated key with no answer is graded zero.

Browser, host/xcWebServer, PostgreSQL concurrency, load, and distribution
evidence are UNVERIFIED. The coordinator must run the full package suite and
review migration SQL before accepting the integrated batch. Task 32 is the
next gate for manual grading.
