# Task 23 assessment runs

- Task ID: 23
- Status: COMPLETE for immutable publication and safe pre-attempt metadata; task 24 owns authenticated attempt creation and question delivery.
- Baseline: `7255c95`
- Final commit: coordinator batch commit pending.

## Implementation

- Added `AssessmentRun` and protected `AssessmentRunAsset` rows in additive migration `0011_assessment_runs`.
- `publish_assessment()` locks the draft, validates its version and audience, copies exact pinned revision payloads, metadata, type/schema provenance, points, instructions and settings into an immutable manifest, and retains referenced assets.
- Teacher APIs list/publish source-assessment runs and retrieve a private run manifest. Publication uses the existing authoring idempotency receipt.
- The authenticated available-run endpoint returns title, instructions and access metadata only. It does not expose items, answers, feedback or resources before task 24 creates an authorized attempt.

## Verification

Passed:

- `pytest -q tests/test_assessment_runs.py tests/test_assessment_definitions.py tests/test_assessment_migration.py` — 8 passed
- `python standalone/manage.py makemigrations --check --dry-run`
- `python standalone/manage.py check`
- `python -m compileall -q src tests standalone`
- focused Ruff and `git diff --check`

No browser, PostgreSQL-concurrency, xcWebServer, host migration, deployment, or load evidence was collected. No host database was migrated and no service was restarted.

## Next eligible work

Task 24 can create authenticated attempts from the frozen manifest. It must keep course membership separate from permissions to named submissions and grading records.
