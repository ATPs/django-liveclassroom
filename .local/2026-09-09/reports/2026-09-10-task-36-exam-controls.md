# 36 — exam controls completion report

- Status: READY FOR REVIEW
- Date/time and timezone: 2026-09-10, Asia/Shanghai
- Worktree and branch: main checkout, `main`
- Baseline: `c6831eb`
- Runtime: zsh, conda `django`, `PATH=/data/p/bin:$PATH`, `PYTHONPATH=.:src`
- Migration: `0019_exam_navigation_controls`, additive after `0018`

## Delivered behavior

- Persists forward-only navigation state on each attempt: cursor, accessible high-water
  mark, locked answered item keys, mode, and optimistic navigation version.
- Enforces navigation and deadline limits server-side, including stale-tab conflicts,
  save-before-advance, and read-only prior answers. Autosave cannot write future or
  locked items.
- Persists section question shuffle and fixed/pool option shuffle in the immutable run
  manifest and assigned attempt order. Attempt payloads include server time, remaining
  duration, and navigation state for reconnect-safe countdowns.

## Verification

| Check | Result |
| --- | --- |
| Exam navigation, progress, review, timing, randomization, and release focused tests | PASS — 23 passed in combined coordinator run |
| Worker focused assessment suites | PASS — 50 passed; navigation/randomization/pools 7 passed |
| Ruff, compileall, Django check, migration drift, diff check | PASS |

Browser countdown, bilingual/mobile interaction, PostgreSQL locking, host, and load
acceptance remain unverified.
