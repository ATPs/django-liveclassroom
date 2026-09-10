# Task 52 — two-classroom multi-worker reconnect harness

## Status: PARTIAL

The package test harness now exercises two independent classrooms, two local
uvicorn/Channels workers, reconnects clients after a task-owned worker restart,
and reconciles every acknowledged live answer write through PostgreSQL and HTTP
state. The smaller end-to-end diagnostic passed. The first correctly configured
full 2 x 100 run reached the sampled relay phase but exposed a task-owned
uvicorn keepalive timeout; the harness now gives its synthetic workers a
120-second ping interval/timeout. The assessment autosave/expiry part of the
Task 52 contract remains open for a later coordinator run.

## Scope and implementation

Changed only `tests/test_multiworker_classroom.py`. The existing PostgreSQL
multi-worker test now:

- seeds two disposable live classrooms and 100 guest participants per classroom
  by default;
- starts exactly two local uvicorn processes on task-selected loopback ports;
- sends teacher publish/settings commands, 200 initial submissions, 200
  idempotent cross-worker retries, and 200 edits after reconnect;
- closes a deterministic subset of sockets, terminates and restarts worker zero,
  reconnects every client affected by that process plus the explicit subset, and
  checks HTTP authoritative state on both classrooms;
- checks 400 accepted writes against 400 ledger entries and 400 persisted
  `SubmissionRevision` rows (two per participant per classroom);
- publishes final PostgreSQL relay notifications and checks a deterministic
  reconnecting-client sample per classroom, keeping a missed event bounded by
  the configured relay timeout; and
- reports p50, p95, and maximum HTTP command latency with the workload duration.

`LIVECLASSROOM_LOAD_PARTICIPANTS` and `LIVECLASSROOM_LOAD_RELAY_TIMEOUT` are
diagnostic environment overrides. Defaults remain 100 and 45 seconds. They are
not command-line credentials and do not change production configuration.

## Baseline and environment

- Baseline at implementation start: `71c4c2f78611d946a0ff0fd26971c9c815d07bb2`.
- User-owned dirty files preserved: `.gitignore`, `AIM.md`, `pyproject.toml`,
  `.local/2026-09-09/reports/2026-09-10-task-31-automatic-attempt-grading.md`,
  and `tests/test_assessment_grading.py`.
- No migration, dependency, host database, service, xcWebServer, or deployment
  files changed.
- PostgreSQL runs used disposable task-named databases on `127.0.0.1:55432`.
- Web workers bound only to task-selected `127.0.0.1` ports.

## Verification

Passed focused checks:

```text
python -m py_compile tests/test_multiworker_classroom.py
ruff check tests/test_multiworker_classroom.py
git diff --check
```

The two-classroom end-to-end diagnostic passed with five participants per
classroom in a disposable PostgreSQL database. It exercised the same restart,
reconnect, write-ledger, HTTP state, and sampled relay paths as the default
matrix:

```text
DJANGO_SETTINGS_MODULE=tests.postgres_settings
LIVECLASSROOM_POSTGRES_TEST_NAME=task52_debug2_20260910
LIVECLASSROOM_LOAD_PARTICIPANTS=5
LIVECLASSROOM_LOAD_RELAY_TIMEOUT=5
pytest --create-db -q -s tests/test_multiworker_classroom.py
1 passed in 10.60s
10 students, 20 accepted writes and 20 HTTP retries across 2 classrooms/2 workers;
p50=71.0ms p95=209.2ms max=227.2ms duration=2.08s
```

The required `django` environment has PostgreSQL and uvicorn but does not have
the optional `websockets.sync.client` package. Its durable check therefore
correctly recorded one skip rather than a false pass:

```text
.local/2026-09-09/reports/checks/task52-two-classrooms-django-20260910-123106/checks.log
1 skipped in 7.36s
```

The first full run with the temporary task-local WebSocket client used the
required PostgreSQL settings and exited 1 after 141.05 seconds. Its sampled
relay phase reported:

```text
websockets.exceptions.ConnectionClosedError:
received 1011 (internal error) keepalive ping timeout; then sent 1011 (internal error) keepalive ping timeout
```

The failure is why the task-owned worker command now sets `--ws-ping-interval`
and `--ws-ping-timeout` to 120 seconds. The final rerun passed:

```text
.local/2026-09-09/reports/checks/task52-final3-20260910-125348/checks.log
.local/2026-09-09/reports/checks/task52-final3-20260910-125348/exit.code = 0
1 passed in 70.17s
200 students, 400 accepted writes and 400 HTTP retries across 2 classrooms/2 workers;
websocket convergence sample=20 p50=394.2ms p95=1014.2ms max=1209.8ms duration=37.51s
```

The run used a temporary task-local WebSocket client outside package
dependencies; no shared Python environment was modified.

## Remaining acceptance

The following remain unverified or separate:

- assessment autosave, submission, scheduler-driven expiry, and final grade
  reconciliation while sockets are unavailable;
- sustained warm-up/workload duration and hardware/load profile budgets;
- all supported PostgreSQL versions, host deployment, xcWebServer behavior,
  browser usability, and production load.

The 5-participant result is local package evidence only and is not a substitute
for the required 2 x 100 acceptance or Task 53 host activation.
