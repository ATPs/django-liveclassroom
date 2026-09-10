# Task 51 — migration history and PostgreSQL concurrency

## Status: PARTIAL

Updated the historical migration assertions through the current additive leaf (`0021_authoringjob_artifact_type_authoringdraft`) and added a full-history migration test. The existing PostgreSQL session-snapshot race expectation omitted the immutable activity metadata that the runtime correctly retains; the expected before/after snapshots now include it.

## PostgreSQL evidence

A dedicated disposable PostgreSQL database named `task51_liveclassroom` was used. The initial combined PostgreSQL run produced 10 passes and one snapshot-race assertion failure. After correcting that stale expected snapshot, the focused PostgreSQL locking suite passed:

```text
DJANGO_SETTINGS_MODULE=tests.postgres_settings pytest -q tests/test_postgres_plan_locking.py
3 passed
```

The original combined log is retained as `2026-09-10-task-51-postgres.log`; its nonzero exit documents the pre-fix failure rather than a successful acceptance run.

## Remaining gate

The complete task-51 matrix remains open: concurrent attempt starts/saves/submits/expiry, grading/regrading and share-revocation races need their own real PostgreSQL tests and a fresh complete final run. No host database was accessed or changed.
