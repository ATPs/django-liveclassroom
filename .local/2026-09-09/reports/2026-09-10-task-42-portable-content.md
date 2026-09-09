# 42 — portable content completion report

- Status: READY FOR REVIEW
- Date/time and timezone: 2026-09-10, Asia/Shanghai
- Worktree: main checkout `/data/p/xiaolong/django-liveclassroom/django-liveclassroom`
- Branch: `main`
- Baseline commit: `ef4021f` (task 31 complete; task 42 implementation began from the shared main checkout)
- Runtime: zsh, conda `django`, `PATH=/data/p/bin:$PATH`, `PYTHONPATH=.:src`
- Migration: none

## Delivered behavior

- Adds a versioned `liveclassroom.portable` v1 service with pure validation,
  deterministic owner-authorized export, and atomic import of activities, question
  banks, decks, assessments (including sections and pools), flows, and uploaded
  assets.
- Rejects unsupported and sensitive runtime fields, bad schema/content, duplicate
  local keys, dangling links, unsafe filenames, untrusted paths, invalid hashes,
  and size-limit violations. Inline assets are capped at 10 MiB each and 50 MiB
  per bundle.
- Copies imported definitions to the current owner, preserves author answer keys,
  slide order and private notes, Markdown fences, points, metadata, and flow order.
  It does not expose student/runtime records or create a source link.
- HTTP route registration is intentionally deferred to its coordinator integration
  window, as specified by the task prompt. The reusable service is available to the
  Markdown/YAML importer and a later narrow API adapter.

## Changed files

- `src/liveclassroom/services/portable_content.py`
- `tests/test_portable_content.py`

## Verification

| Check | Result |
| --- | --- |
| `pytest -q tests/test_portable_content.py` | PASS — 9 passed |
| `ruff check src/liveclassroom/services/portable_content.py tests/test_portable_content.py` | PASS |
| `python -m compileall -q src tests standalone` | PASS |
| `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py check` | PASS — no issues |
| `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run` | PASS — no changes detected |
| `git diff --check` | PASS |

Browser, mounted HTTP adapter, external provider, PostgreSQL concurrency, and host
acceptance were not run. No host database, deployment, service, or worktree was changed.
