# Task 29 assessment sections and frozen question pools

- Task ID: 29
- Status: COMPLETE for section and publication-time pool backend scope; coordinator review/staging remains pending.
- Baseline commit: `766f52a`
- Final commit: uncommitted shared-main changes (coordinator owns the batch commit).
- Preserved dirty user files: `.gitignore`, `AIM.md`, and `pyproject.toml`.

## Delivered behavior

- Added `AssessmentSection` and `AssessmentSectionEntry` models with ordered stable keys,
  fixed-item entries, and validated bank-pool entries.
- Added `services.assessment_sections` with default-section compatibility, atomic section
  replacement, owner checks, bank-filter validation, positive sample-size validation,
  fixed-item membership checks, and section payload serialization.
- Extended assessment create/update/copy/replace behavior and added the mount-safe
  `api-v1-assessment-sections` GET/PUT endpoint.
- Extended publication to resolve current authorized bank membership once, exclude fixed
  definitions/revisions, reject insufficient or overlapping pools, retain candidate
  revision content and assets, and write section/pool snapshots into the immutable run
  manifest. Legacy flat run items remain readable.
- Pooled runs are explicitly gated from attempt start until task 30 supplies retained
  sampling/assignment; they are never silently delivered as all bank members.
- Added migration `0014_assessment_sections`, which backfills one default section and
  fixed entries in original item order for existing assessments.

## Verification

Passed:

- `pytest -q tests/test_assessment_pools.py tests/test_assessment_sections_migration.py tests/test_assessment_runs.py tests/test_assessment_attempts.py tests/test_assessment_definitions.py tests/test_assessment_migration.py tests/test_answer_revision_migration.py tests/test_attempt_autosave.py tests/test_attempt_submission.py tests/test_assessment_timing.py tests/test_student_assessment_browser.py` — 35 passed.
- Migration compatibility and historical migration suites — 8 passed.
- Focused Ruff checks over changed source, migration, and tests — passed.
- `python -m compileall -q src/liveclassroom` — passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run` — passed.
- `git diff --check` — passed.

Browser screenshot/locale evidence, PostgreSQL concurrency, host migration, load,
distribution, and deployment behavior were not verified. No host database was migrated
and no service was restarted.

## Next eligible task

Task 30 can sample frozen pool candidates and persist selected item/option order in each
new attempt. The coordinator should review the manifest shape and retain migration 0014
as the current leaf before committing the batch.
