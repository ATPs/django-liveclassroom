# Task 20 — Presentation cues and provider selection

- Task ID: 20
- Status: PARTIAL: package services, APIs, and teacher source picker are implemented; browser and host/provider discovery evidence remain open.
- Baseline observed: `e31a698` before the coordinator's concurrent task 25 work; shared checkout advanced to `6cf5e8e` while this task was in progress.
- Final commit: uncommitted shared checkout; coordinator owns staging and the integrated commit.

## Interfaces and changed paths

- `liveclassroom.services.presentation_cues` retains bounded cues in
  `LiveSession.creation_settings["presentation_cues"]`. A cue stores an
  immutable native `DeckSnapshot` slide key/index or an external provider's
  canonical reference, source fingerprint, title, and `offer_activity` action.
- `create_presentation_cue`, `list_presentation_cues`,
  `replace_presentation_cue`, `delete_presentation_cue`, and
  `launch_presentation_cue` validate the session plan step, actor permission,
  slide bounds, source authorization, and changed fingerprints. Launch delegates
  to the existing idempotent `launch_plan_step` path and does not auto-publish
  from slide events.
- Added mount-safe routes for provider catalog, provider search, URL/reference
  resolution, cue CRUD, and teacher-confirmed cue launch under
  `api/v1/sessions/<session_id>/presentation/`.
- `VaultPubProvider` now explicitly advertises that package-level browse is
  unavailable while URL resolution remains supported; descriptions advertise
  Slide View capability.
- `PresentationSourcePicker.tsx` is wired into the teacher native-deck panel.
  It supports native snapshot selection, provider selection, provider search
  when advertised, paste-and-resolve URLs, cue attachment, explicit Launch, and
  visible unavailable/reattach states in English and Simplified Chinese.

Changed paths owned by this task:

- `src/liveclassroom/services/presentation_cues.py`
- `src/liveclassroom/api_presentation.py`
- `src/liveclassroom/integrations/vaultpub.py`
- `src/liveclassroom/urls.py`
- `frontend/src/surfaces/teacher/PresentationSourcePicker.tsx`
- `frontend/src/surfaces/teacher/TeacherConsole.tsx`
- `tests/test_presentation_cues.py`

`urls.py` and `TeacherConsole.tsx` also contain concurrent coordinator/task
changes; preserve those when staging.

## Verification

Passed in zsh with conda `base`, `/data/p/bin` on `PATH`, and `PYTHONPATH=.:src`:

- `pytest -q tests/test_presentation_cues.py tests/test_vaultpub_provider.py` — 7 passed.
- `ruff check src/liveclassroom/services/presentation_cues.py src/liveclassroom/api_presentation.py src/liveclassroom/integrations/vaultpub.py tests/test_presentation_cues.py` — passed.
- `python -m compileall -q` on the task Python files — passed.
- `bun run check` from `frontend` — passed (`tsc --noEmit`).
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py check` — passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run` — no changes detected.
- `git diff --check` — passed.

No migration or dependency change was required. Existing migration history was
left untouched.

Browser Playwright screenshots/localized 390px and desktop interactions were
not run. Real xcWebServer provider discovery, VaultPub authorization/share
lifecycle, PostgreSQL concurrency, multi-worker notifications, load,
distribution, and production behavior remain unverified. Existing ordinary
URL/PDF/image file viewer behavior was not altered and still requires its
separate browser acceptance.

Next eligible work is integrated review of task 20 with task 17/18/19 and then
the later lesson/deck cue integration tasks. The coordinator should stage only
the explicit task paths, run the final bundle, and preserve concurrent task 25
files and migration `0013`.
