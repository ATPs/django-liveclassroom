# 34 — controlled result release completion report

- Status: READY FOR REVIEW
- Date/time and timezone: 2026-09-10, Asia/Shanghai
- Worktree and branch: main checkout, `main`
- Baseline: `98f8261`
- Runtime: zsh, conda `django`, `PATH=/data/p/bin:$PATH`, `PYTHONPATH=.:src`
- Migration: `0017_assessmentresultrelease`, additive after task 32's `0016`

## Delivered behavior

- Adds four independently controlled result dimensions: scores, answer keys and
  saved answers, explanations, and teacher comments. Each defaults to hidden/manual,
  supports `never`, `after_submit`, `after_close`, and staff-triggered manual release.
- Stores release decisions separately from immutable run manifests, with the staff
  actor, timestamp, run-wide or explicit-attempt target, and unique constraints.
- Produces student-facing payloads from a server-side allowlist. A score release
  does not expose answer keys. Submitted attempt detail and a dedicated result endpoint
  use this filtered payload.
- Adds mount-safe release/result APIs. Run owners and authorized course staff can manage
  release; students can retrieve only their own filtered attempt.

## Changed files

- `src/liveclassroom/release_policy.py`
- `src/liveclassroom/models/result_release.py`
- `src/liveclassroom/models/__init__.py`
- `src/liveclassroom/migrations/0017_assessmentresultrelease.py`
- `src/liveclassroom/services/result_release.py`
- `src/liveclassroom/services/assessments.py`
- `src/liveclassroom/api_release.py`
- `src/liveclassroom/api_attempts.py`
- `src/liveclassroom/urls.py`
- `tests/test_result_release.py`, `tests/test_result_release_api.py`

## Verification

| Check | Result |
| --- | --- |
| `pytest -q tests/test_result_release.py tests/test_result_release_api.py` | PASS — 9 passed |
| Combined release/grading/attempt focused suite | PASS — 35 passed |
| `ruff check` for release files | PASS |
| `python -m compileall -q src tests standalone` | PASS |
| `python standalone/manage.py check` | PASS — no issues |
| `python standalone/manage.py makemigrations --check --dry-run` | PASS — no changes detected |
| `git diff --check` | PASS |

No browser, host, PostgreSQL concurrency, live asset/fragment authorization, load, or
production deployment evidence was obtained. Those boundaries remain for later review
and acceptance tasks.
