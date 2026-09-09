# Task 17 — Native deck presentation

- Status: COMPLETE for the package service, API, authorization, and safe
  fallback surface. Optional VaultPub and host browser evidence remain open.
- Baseline: `7255c959cc4883786a8af810b5e0d8a371450574`.
- Final commit: coordinator will commit the shared batch; this worker did not
  stage or commit.

## Interfaces and changed paths

Native deck presentation state is stored under the existing
`LiveSession.creation_settings["native_deck_presentations"]`, with one entry per
`display` or `participants` channel containing `snapshot_id`, stable
`slide_key`, zero based `slide_index`, session `revision`, and `allow_review`.
`present_deck` and `update_deck_presentation` use the existing session version,
event, notification, and polling protocol. Publishing an activity to a channel
clears only that channel's native deck entry.

Added versioned APIs for freezing snapshots and launching decks:

- `POST/GET api/v1/decks/<deck_id>/snapshots/`
- `POST api/v1/sessions/<session_id>/decks/present/`
- Existing `api-v1-session-presentation` accepts native deck launch and
  navigation payloads for compatibility with the console.

Added authorized immutable delivery routes for public payload, Slide View,
slide payload, and retained resources under
`api/v1/sessions/<session_id>/decks/<snapshot_id>/`. Teacher access is limited
to a currently presented channel; admitted participants can access only the
active participant channel. Notes are never serialized. Native deck fallback
rendering uses `MarkdownView`; the optional VaultPub Slide View route remains
isolated in an iframe-compatible response.

Changed source files:

- `src/liveclassroom/services/presentation.py`
- `src/liveclassroom/deck_delivery.py`
- `src/liveclassroom/api_decks.py`
- `src/liveclassroom/api_assets.py`
- `src/liveclassroom/api.py`
- `src/liveclassroom/urls.py`
- `src/liveclassroom/services/classroom.py`
- `src/liveclassroom/templates/liveclassroom/teacher_console.html`
- `frontend/src/activities/NativeDeckView.tsx`
- `frontend/src/protocol.ts`
- `frontend/src/surfaces/display/ClassroomDisplay.tsx`
- `frontend/src/surfaces/student/StudentSession.tsx`
- `frontend/src/surfaces/teacher/TeacherConsole.tsx`
- `tests/test_deck_presentation.py`
- `tests/test_deck_presentation_browser.py`

## Evidence

Passed:

- `pytest -q tests/test_deck_presentation.py tests/test_deck_presentation_browser.py` — 5 passed.
- `cd frontend && bun run check` — passed.
- `ruff check` on all Task 17 Python sources and tests — passed.
- `python -m compileall -q src/liveclassroom tests` — passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py check` — passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run` — no changes detected.
- `git diff --check` — passed.

Skipped or unverified:

- Real Playwright desktop/mobile English/Chinese presentation and reconnect
  evidence was not run in this worker window.
- VaultPub is optional and no host VaultPub renderer/provider was activated or
  changed; rich Slide View rendering, resource hydration, PostgreSQL relay,
  load behavior, distribution, and xcWebServer behavior remain unverified.
- No migration was added; state uses the existing JSON field and session
  revision protocol.

## Follow-up

The coordinator should inspect the shared Task 22 changes, run the combined
frontend bundle and package suite, then exercise the real independent display /
participant workflow. Task 18 may add teacher-only notes and themes on top of
the retained snapshot boundary; Task 19 can add portability after this delivery
contract is accepted.
