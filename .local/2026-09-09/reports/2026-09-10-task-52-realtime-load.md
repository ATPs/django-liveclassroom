# Task 52 — realtime and load acceptance

## Status: PARTIAL

The package-owned PostgreSQL harnesses provide real, task-owned two-worker,
restart/reconnect, and assessment-resilience evidence. They do not meet the full
two-classroom sustained-duration contract, so Task 52 remains partial.

## Passed task-owned evidence

A disposable PostgreSQL test database was created with
`tests.postgres_settings` and task-specific `LIVECLASSROOM_POSTGRES_TEST_NAME` values.
No xcWebServer process, database, user, or traffic was used.

```text
DJANGO_SETTINGS_MODULE=tests.postgres_settings pytest --create-db -q \
  tests/test_classroom_load.py tests/test_multiworker_classroom.py
1 passed, 1 skipped in 31.55s
```

`test_one_hundred_concurrent_students_keep_every_accepted_answer` uses 100 guest
participants and 16 concurrent worker threads. Each makes an accepted submission and
an idempotent replay (200 HTTP writes total). The test reconciles all 100 persisted
submission revisions, answer texts, participant aggregate count, and an authoritative
state refresh.

The multi-worker skip was reproducibly due to the missing optional `websockets` client
in the shared conda `django` environment, not a pass. To keep that environment
unchanged, a disposable `/tmp/liveclassroom-task52-websockets` venv with
`websockets==16.1.1` was created with system site packages. It ran the real existing
harness:

```text
DJANGO_SETTINGS_MODULE=tests.postgres_settings \
  /tmp/liveclassroom-task52-websockets/bin/python -m pytest --create-db -q \
  tests/test_multiworker_classroom.py
1 passed in 30.89s
```

That harness starts two task-owned Uvicorn/ASGI workers on random loopback ports,
connects 100 real WebSocket clients (50 per worker), sends and replays 100 accepted
HTTP submissions across different workers, verifies the authoritative HTTP state, and
observes a PostgreSQL relay notification on every client. It terminates the task-owned
workers in `finally`.

Durable logs:

- `2026-09-10-task-52-baseline.log` and `.exit`
- `2026-09-10-task-52-multiworker.log` and `.exit`

## Assessment resilience evidence

The focused assessment acceptance test uses two task-owned Uvicorn workers and
two independent authenticated assessment runs on disposable PostgreSQL. It
starts each attempt and acknowledges one autosave through HTTP, with no
assessment WebSocket connected. Worker zero is then restarted; its replacement
reads the first saved revision through the authoritative attempt-detail API.
One attempt is submitted after restart. The other is made due and finalized by
the separate `expire_assessment_attempts` scheduler process, then both are
reconciled by the separate `grade_pending_attempts` process.

Command and environment:

```text
source /data/p/anaconda3/etc/profile.d/conda.sh
conda activate django
export PATH="/data/p/bin:$PATH"
export PYTHONPATH=.:src
export LIVECLASSROOM_POSTGRES_NAME=postgres
export LIVECLASSROOM_POSTGRES_TEST_NAME=task52_assessment2_20260910
export LIVECLASSROOM_POSTGRES_PASSWORD=postgres
DJANGO_SETTINGS_MODULE=tests.postgres_settings pytest --create-db -s -q \
  tests/test_assessment_resilience_postgres.py
```

Observed: **1 passed** in 8.80 seconds. The task-owned run reported two
acknowledged saves, one worker restart, zero assessment sockets, and save
latencies of p50 64.0 ms, p95 222.3 ms, max 222.3 ms. The scheduler reported
one expiry and a zero-row idempotent second invocation; grading reported two
graded attempts. Database reconciliation found exactly one retained answer
revision, one item grade, one aggregate grade, and one immutable grade decision
for each attempt. No acknowledged answer was lost and no duplicate finalization
or grade row was created.

The new test is `tests/test_assessment_resilience_postgres.py`; its worker and
scheduler processes use the disposable database named above and terminate in
`finally`. SQLite collection skips it because SQLite cannot prove this
cross-worker contract. The previous multi-worker test supplies the separate
100-participant WebSocket relay and reconnect evidence described above; this
focused run intentionally measures the assessment HTTP fallback while sockets
are unavailable.

## Required remaining work

The full Task 52 contract has not been demonstrated: a combined two-classroom run
with 100 participants in each classroom; a measured warm-up and ten-minute interval
with sustained p50/p95 results; and a reusable command-line harness with the requested
`--help` arguments. This evidence is not browser usability, host deployment, or
production-load proof.
