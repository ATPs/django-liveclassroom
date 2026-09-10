# 33 — audited corrections and regrading completion report

- Status: READY FOR REVIEW
- Date/time and timezone: 2026-09-10, Asia/Shanghai
- Worktree and branch: main checkout, `main`
- Baseline: `ae18bd9`
- Runtime: zsh, conda `django`, `PATH=/data/p/bin:$PATH`, `PYTHONPATH=.:src`
- Migration: `0018_grading_rule_revisions`, additive after release migration `0017`

## Delivered behavior

- Adds explicit item-grade overrides with actor/reason/comment, exact Decimal point
  scaling, retry-safe audit decisions, and aggregate recomputation.
- Adds immutable approved grading-rule revisions for one retained run item, with
  sequential version, rule configuration, creator, reason, and approval time. Only
  grading fields may be changed; prompts, options, assigned order, and points stay
  immutable.
- Regrades selected submitted objective items from retained answers using an approved
  rule revision, preserves manual/override decisions by default, and appends audit
  decisions instead of overwriting history. The numeric-key example verifies 10→11
  changes a saved 11 from zero to full credit while original data remains inspectable.

## Changed files

- `src/liveclassroom/models/grading.py`, `src/liveclassroom/models/__init__.py`
- `src/liveclassroom/migrations/0018_grading_rule_revisions.py`
- `src/liveclassroom/services/grade_corrections.py`
- `tests/test_grade_corrections.py`

## Verification

| Check | Result |
| --- | --- |
| Corrections/manual/automatic/submission/timing tests | PASS — 35 passed |
| `ruff check` for correction files | PASS |
| `python -m compileall -q src tests standalone` | PASS |
| `python standalone/manage.py check` | PASS — no issues |
| `python standalone/manage.py makemigrations --check --dry-run` | PASS — no changes detected |
| `git diff --check` | PASS |

Correction API/editor, PostgreSQL concurrent staff correction, browser workflow, host,
and load evidence remain outside this change and unverified.
