# 38 — teacher progress completion report

- Status: READY FOR REVIEW
- Date/time and timezone: 2026-09-10, Asia/Shanghai
- Worktree and branch: main checkout, `main`
- Baseline: `c6831eb`
- Runtime: zsh, conda `django`, `PATH=/data/p/bin:$PATH`, `PYTHONPATH=.:src`
- Migration: none

## Delivered behavior

- Adds permission-scoped run progress and account-linked learner overview services and
  mount-safe APIs. Counts distinguish not-started, in-progress, submitted, graded,
  pending-manual, and ungraded states from persisted records.
- Uses roster denominators only for class runs; authenticated-link runs report eligible
  total unknown. Test participants are excluded from rows and denominator by default.
- Named overview uses account identity and retained attempts/participation without
  creating attendance or attempts.

## Verification

| Check | Result |
| --- | --- |
| Progress service/API focused tests | PASS — 4 coordinator tests; worker reports 8 combined focused tests |
| Ruff, compileall, Django check, migration drift, diff check | PASS |

Teacher progress frontend/browser, host, PostgreSQL, and load evidence remain unverified.
