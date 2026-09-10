# Task 48 — bilingual help and deterministic demos

- Status: READY FOR REVIEW
- Date/time and timezone: 2026-09-10, Asia/Shanghai
- Worktree: main checkout
- Branch: main
- Baseline commit: `6f04982fcb03029e665cabe2aa5aacccbecae903`
- Final commit(s): `564aee7` (`Add bilingual help and deterministic demos`); this report update is committed separately.
- AIM snapshot SHA-256: `ddfe6b02c2cb211d012fd0eb23b3273c5c7b0031ada2f42184b864b5526da0e0`
- Runtime: zsh, conda `django`, `PATH=/data/p/bin:$PATH`, `PYTHONPATH=.:src`
- Verified package import path: current checkout through `PYTHONPATH=.:src`

## Delivered behavior

- Expanded the server-rendered Help page in English and Simplified Chinese with a
  short teacher path covering optional Course/Class organization, lesson and
  Markdown/YAML authoring, native decks, optional VaultPub rendering, classroom
  launch, assessment start/resume/submit, and review/export boundaries.
- Added mount-safe links to real workspace, builder, deck, assessment, join,
  sharing, and history routes. The page states where an ID or host adapter is
  required and does not claim unavailable workspace sharing or deployment proof.
- Documented simple defaults plus empty/loading/error, keyboard, and mobile
  guidance. Updated the root README to describe the same current behavior.
- Extended the existing opt-in `seed_liveclassroom_bash_demo` command with stable,
  repeatable local artifacts: a disabled demo owner, class-scoped imported Markdown
  activity, two-slide native deck, assessment draft and immutable practice run.
  It uses local fake content only and never runs during startup.
- Added `tests/test_help_and_demos.py` for bilingual link/content coverage and
  repeatable demo artifact assertions.

## Changed files and contracts

- Files changed: `README.md`, `src/liveclassroom/management/commands/seed_liveclassroom_bash_demo.py`,
  `src/liveclassroom/templates/liveclassroom/help.html`, `tests/test_help_and_demos.py`.
- Migration(s): none.
- Dependencies/lockfile changes: none.
- Interfaces affected: the existing opt-in demo command now seeds additional
  teacher-owned authoring examples; existing command arguments and public demo
  classroom behavior are unchanged.
- Any deviation from the plan: the existing public Bash demo registry remains the
  source of the public sample classrooms; additional deck/import/assessment rows
  are ordinary deterministic records rather than new schema fields.

## Verification

| Check | Exact command | Result and counts | Log/evidence path |
| --- | --- | --- | --- |
| Focused tests | `PYTHONPATH=.:src pytest -q tests/test_help_and_demos.py tests/test_help_guidance.py tests/test_public_bash_demo.py` | PASS — 18 passed | terminal run on 2026-09-10 |
| Ruff | `ruff check src/liveclassroom/management/commands/seed_liveclassroom_bash_demo.py tests/test_help_and_demos.py` | PASS | terminal run on 2026-09-10 |
| Compile | `python -m compileall -q src/liveclassroom/management/commands/seed_liveclassroom_bash_demo.py tests/test_help_and_demos.py` | PASS | terminal run on 2026-09-10 |
| Django system check | `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py check` | PASS — no issues | terminal run on 2026-09-10 |
| Migration drift | `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run` | PASS — no changes detected | terminal run on 2026-09-10 |
| Diff check | `git diff --check` | PASS | terminal run on 2026-09-10 |
| Browser acceptance | `PYTHONPATH=.:src pytest -q tests/test_help_and_demos.py` | PASS — Chromium Help smoke at 390px and 1440px; no horizontal overflow | terminal run on 2026-09-10 |

## Remaining work or blockers

- The Help page does not prove host VaultPub configuration, production deployment,
  PostgreSQL concurrency, or load behavior; those remain separate acceptance
  boundaries.
- The seeded assessment is a local immutable practice run. It does not create a
  real credential or student submission.

## Handoff

- Final git status: includes unrelated user/parallel-agent dirty paths; preserved.
- Baseline-to-HEAD diff summary: Task 48 scoped README, Help template, demo seed,
  tests, and this report.
- Task 48 changes will be committed on `main`; no merge, push, deployment, host
  database mutation, service restart, or worktree deletion was performed.
