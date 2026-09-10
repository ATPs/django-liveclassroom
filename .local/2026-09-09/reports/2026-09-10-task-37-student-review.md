# 37 — student review completion report

- Status: READY FOR REVIEW
- Date/time and timezone: 2026-09-10, Asia/Shanghai
- Worktree and branch: main checkout, `main`
- Baseline: `c6831eb`
- Runtime: zsh, conda `django`, `PATH=/data/p/bin:$PATH`, `PYTHONPATH=.:src`
- Migration: none

## Delivered behavior

- Adds read-only, paginated own-attempt history and retained review endpoints.
- Review uses only retained attempt manifests and own saved answer revisions, so source
  edits do not alter history. Result dimensions are recalculated through the release
  policy on each request; answer keys, explanations, comments, and scores remain
  absent until released.
- APIs hide foreign attempts as not found and do not create attempt, attendance, or
  participant records on GET.

## Verification

| Check | Result |
| --- | --- |
| Review/release focused tests | PASS — included in 23 passing combined focused tests |
| Ruff, compileall, Django check, migration drift, diff check | PASS |

Student review UI/browser, protected direct fragment/resource authorization, host, and
PostgreSQL/load evidence remain unverified.
