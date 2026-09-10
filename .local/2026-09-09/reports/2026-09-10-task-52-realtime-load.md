# Task 52 — realtime and load acceptance

## Status: PARTIAL

The existing package-owned PostgreSQL harnesses provide real, task-owned baseline
coverage. They do not meet the full two-classroom, restart/reconnect, assessment, or
measured-duration contract, so Task 52 remains partial.

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

## Required remaining work

The full Task 52 contract has not been demonstrated: two simultaneous classrooms with
100 participants each; measured warm-up and ten-minute interval with p50/p95; an
intentional socket-loss reconnect and one worker restart; assessment autosave,
submission and deadline expiry while sockets are unavailable; an acknowledged-write
ledger; and a reproducible command-line harness with the requested `--help` arguments.
This evidence is not browser usability, host deployment, or production-load proof.
