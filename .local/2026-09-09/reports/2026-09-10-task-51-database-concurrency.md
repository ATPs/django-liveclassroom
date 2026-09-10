# Task 51 — migration history and PostgreSQL concurrency

## Status: PARTIAL

The focused migration and cross-worker acceptance matrix now passes on a fresh
task-named PostgreSQL database. The gate remains partial because this is a
package acceptance matrix, not production-load, host-deployment, or the full
unbounded migration-history proof under every supported PostgreSQL version.

## Scope and changes

The final task commit contains:

- `tests/test_assessment_postgres_concurrency.py`: six PostgreSQL-only tests
  using independent Django connections and bounded `Barrier` synchronization.
  They cover one active attempt from concurrent starts, duplicate answer saves,
  save versus submit, two expiry finalizers, concurrent automatic grading plus
  regrading, and share revocation against an existing recipient copy.
- `src/liveclassroom/services/assessment_runs.py`: lock only the assessment
  draft row when its optional course is loaded. PostgreSQL rejects a plain
  `FOR UPDATE` on the nullable outer-joined course table.
- `src/liveclassroom/services/grade_corrections.py`: apply the same explicit
  self-row lock to attempt and item queries that load an optional run course.

No host database, deployment, service restart, or production data was touched.

## PostgreSQL evidence

The disposable Docker PostgreSQL service was reached at `127.0.0.1:55432` with
the task settings mapping in `tests/postgres_settings.py`: `NAME=postgres`,
`TEST.NAME=task51_matrix3_20260910`, user `postgres`, and password supplied
through the task-only environment variable. The test setup created the
database and applied the current migration leaf. Each worker closed Django
connections before its operation, so workers opened independent PostgreSQL
connections.

Command:

```zsh
source /data/p/anaconda3/etc/profile.d/conda.sh
conda activate django
export PATH="/data/p/bin:$PATH"
export PYTHONPATH=.:src
export LIVECLASSROOM_POSTGRES_NAME=postgres
export LIVECLASSROOM_POSTGRES_TEST_NAME=task51_matrix3_20260910
export LIVECLASSROOM_POSTGRES_PASSWORD=postgres
DJANGO_SETTINGS_MODULE=tests.postgres_settings pytest --create-db -q \
  tests/test_assessment_postgres_concurrency.py \
  tests/test_postgres_plan_locking.py tests/test_postgres_relay.py \
  tests/test_grade_corrections.py::test_regrade_uses_explicit_corrected_rule_and_preserves_original_manifest_and_answer
```

Observed: **16 passed, 1 warning** in 14.11 seconds. The warning is Django's
expected database override warning in the relay test. The six new tests assert
row identities, revision versions, finalization state, grade totals, immutable
decision counts, approved rule revisions, revocation state, and recipient copy
ownership; they do not treat HTTP status codes as concurrency evidence.

## Migration-history evidence

The populated history test and migration compatibility tests passed on SQLite:

```text
tests/test_full_history_migrations.py tests/test_migration_compatibility.py
2 passed, 7 skipped
```

The seven skips are the PostgreSQL-only cases from the concurrency module when
the command uses normal SQLite settings. On a fresh task-named PostgreSQL
database `task51_history_20260910`, the populated history and compatibility
command passed **3 tests**. It migrated populated legacy rows from `0006` to
the current `0021_authoringjob_artifact_type_authoringdraft` leaf and restored
the current leaf in `finally`.

Durable logs:

- `2026-09-10-task-51-matrix3.log` — final 16-test PostgreSQL matrix.
- `2026-09-10-task-51-history-pg.log` — PostgreSQL migration-history run.
- `2026-09-10-task-51-sqlite-history.log` — SQLite history and skip evidence.

## Remaining acceptance boundaries

The package matrix does not prove PostgreSQL behavior under production load,
all supported database versions, network failures, cross-worker notification
delivery, or the xcWebServer host's live schema. Host migration and service
restart remain an explicitly authorized deployment step. The task therefore
stays **PARTIAL** for coordinator review even though the focused checks pass.
