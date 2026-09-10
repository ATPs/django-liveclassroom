# 39 — grade summaries completion report

- Status: READY FOR REVIEW
- Date/time and timezone: 2026-09-10, Asia/Shanghai
- Worktree and branch: main checkout, `main`
- Baseline: `8405cef`
- Migration: none

## Delivered behavior

- Adds permission-scoped Class and TeachingCourse grade summaries derived from retained
  attempts and current grade rows. Latest submitted attempts populate each cell while
  active attempts and complete history remain separate.
- Keeps not-started, pending, ungraded, and explicit zero distinct; states roster
  denominator and excludes test participants by default. Course grouping includes only
  classes the teacher can read.
- Adds mount-safe Class, Course, and TeachingCourse summary APIs.

## Verification

- Focused summaries/progress/manual grading: PASS — 14 passed.
- Broader focused grading/release/progress/organization: PASS — 39 passed.
- Coordinator focused suite including summary and portability tests: PASS — 43 passed.
- Ruff, compileall, Django check, migration drift, and diff check: PASS.

Browser/host/PostgreSQL/load evidence remains unverified.
