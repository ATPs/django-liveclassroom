# Task 18 — Presenter notes and simple appearance

- Task ID: 18
- Status: COMPLETE for package/API and focused frontend source checks; real browser and host evidence remain unverified.
- Baseline: `cb1caafd286c1c60808e968326520e7a857f4a74` (task 17 integrated in main).
- Final commit: coordinator will commit the shared batch; this worker did not stage or commit.

## What changed

- Added `api-v1-session-deck-notes`, which requires `can_manage_session`, checks the currently presented immutable snapshot, returns retained notes only, and uses `private, no-store` caching.
- Added teacher-only `notes_url` to the session deck state. Public deck payloads, Slide View staging Markdown, and resources continue to omit notes.
- Added `DECK_THEME_KEYS` (`default`, `light`, `dark`) and safe mapping to VaultPub's `light`/`dark` themes. Draft and snapshot preview documents now carry validated upstream Slide View frontmatter and horizontal-rule separators.
- Added the draft theme selector and presenter notes panel. Native deck view includes scoped fullscreen/exit controls and left/right keyboard navigation for teachers; Escape exits fullscreen.

Changed paths owned by this task:

- `src/liveclassroom/services/decks.py`
- `src/liveclassroom/services/presentation.py`
- `src/liveclassroom/deck_delivery.py`
- `src/liveclassroom/services/deck_snapshots.py`
- `src/liveclassroom/deck_views.py`
- `src/liveclassroom/urls.py`
- `src/liveclassroom/static/liveclassroom/liveclassroom.css`
- `frontend/src/activities/NativeDeckView.tsx`
- `frontend/src/protocol.ts`
- `frontend/src/locales.ts`
- `frontend/src/surfaces/decks/DeckWorkspace.tsx`
- `tests/test_presenter_notes.py`
- `tests/test_presenter_notes_browser.py`

Task 19 portability files already present in the shared checkout were preserved.
User-owned `.gitignore`, `AIM.md`, and `pyproject.toml` were not staged or edited.

## Verification

Passed in zsh with conda `base`, `/data/p/bin` on `PATH`, and `PYTHONPATH=.:src`:

- `pytest -q tests/test_presenter_notes.py tests/test_presenter_notes_browser.py tests/test_deck_presentation.py tests/test_deck_snapshots.py tests/test_deck_preview.py tests/test_decks.py tests/test_deck_import_export.py` — 19 passed (the two added task 18 tests also pass independently).
- `ruff check` on changed Python files and focused tests — passed.
- `python -m compileall -q src/liveclassroom tests` — passed.
- `(cd frontend && bun run check)` — passed (`tsc --noEmit`).
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py check` — passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run` — no changes detected.
- `git diff --check` — passed.

No migration or dependency change was needed. Full `bun run bundle` and browser automation were left for the coordinator's final integrated frontend build. Browser screenshots, English/Chinese viewport interaction, optional VaultPub runtime hydration, PostgreSQL concurrency, host integration, load behavior, and distribution behavior are unverified.

## Next eligible task

Task 19 (portable deck import/export) can proceed with the notes separation and theme allowlist. Task 20 should add cue/provider behavior only after this presenter UI and delivery boundary is reviewed.
