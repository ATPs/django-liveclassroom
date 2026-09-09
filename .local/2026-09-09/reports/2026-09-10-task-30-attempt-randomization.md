# Task 30 attempt randomization

- Task ID: 30
- Status: COMPLETE
- Baseline: `bec7284`
- Final commit: coordinator commit pending.

## Implementation

- Added `assigned_item_manifests()` and `assign_attempt_items()` to select only frozen pool candidates into durable `AssessmentAttemptItem` rows before an attempt is exposed.
- Fixed items retain section order. Pools sample without replacement using server `SystemRandom`; test callers can inject deterministic RNGs.
- Pool option shuffling applies only to unordered choice types, persists the visible option ID order, and leaves ranking/matching/order-sensitive types intact.
- Attempt start now uses the assignment service atomically. Reconnect/read reuses stored rows and never re-samples a bank.

## Verification

Passed:

- `pytest -q tests/test_attempt_randomization.py tests/test_assessment_attempts.py tests/test_assessment_pools.py` — 8 passed
- Django checks and migration drift check
- compileall, focused Ruff, and `git diff --check`

No browser, PostgreSQL concurrency, host, deployment, or load evidence was collected.

## Next eligible work

Task 31 can grade submitted, retained assignments. Task 32 follows with manual grading.
