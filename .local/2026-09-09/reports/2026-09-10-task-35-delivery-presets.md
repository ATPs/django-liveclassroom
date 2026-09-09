# 35 — delivery presets completion report

- Status: READY FOR REVIEW
- Date/time and timezone: 2026-09-10, Asia/Shanghai
- Worktree and branch: main checkout, `main`
- Baseline: `ae18bd9`
- Runtime: zsh, conda `django`, `PATH=/data/p/bin:$PATH`, `PYTHONPATH=.:src`
- Migration: none

## Delivered behavior

- Adds draft-only named practice, assignment, quiz, and exam presets over the existing
  assessment model. Presets validate positive-or-null attempt limits, navigation, and
  scoring settings; application uses optimistic version checks and cannot alter an
  already published run.
- Practice is unlimited and unscored, assignment has one attempt and releases only
  after a configured hard close, quiz remains manual-release by default, and exam
  requires authenticated access plus timing readiness.
- Adds a mount-safe preset endpoint and optional mode on copies, creating independent
  drafts. The assessment builder provides a bilingual mode selector, collapsed timing
  and attempt controls, publish control, and mode-preserving copy.

## Changed files

- `src/liveclassroom/services/assessment_presets.py`
- `src/liveclassroom/services/assessments.py`
- `src/liveclassroom/api_assessments.py`
- `src/liveclassroom/urls.py`
- `frontend/src/surfaces/assessments/AssessmentBuilder.tsx`
- `src/liveclassroom/static/liveclassroom/app.js`
- `tests/test_assessment_presets.py`, `tests/test_assessment_definitions.py`

## Verification

| Check | Result |
| --- | --- |
| `pytest -q tests/test_assessment_presets.py tests/test_assessment_definitions.py tests/test_assessment_timing.py tests/test_result_release.py tests/test_assessment_attempts.py` | PASS — 23 passed |
| `ruff check` for preset files | PASS |
| `python -m compileall -q src tests standalone` | PASS |
| `python standalone/manage.py check` | PASS — no issues |
| `python standalone/manage.py makemigrations --check --dry-run` | PASS — no changes detected |
| `cd frontend && bun run check && bun run bundle` | PASS |
| `git diff --check` | PASS |

Browser interaction, host, PostgreSQL, and load behavior were not tested. The client
uses the server preset endpoint for persisted drafts; server validation remains the
authoritative constraint.
