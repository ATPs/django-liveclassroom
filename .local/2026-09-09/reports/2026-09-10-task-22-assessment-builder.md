# Task 22 assessment builder

- Task ID: 22
- Status: COMPLETE for the fixed-question teacher workspace; coordinator integration pending.
- Baseline: `7255c95` (`Add question workspace deck editor and assessments`)
- Final commit: uncommitted in the shared main checkout; the coordinator owns the batch commit.

## Changed paths and interfaces

- Added `frontend/src/surfaces/assessments/AssessmentBuilder.tsx` and its
  `[data-assessment-builder]` mount. It lists and opens private assessment
  drafts, creates a fixed-question draft, edits title/instructions/optional
  class, adds current question-bank revisions, reorders items, edits positive
  decimal points, calculates totals, saves through the Task 21 APIs, previews
  pinned Markdown with teacher-only answers, copies a draft, and offers an
  explicit current-revision replacement action.
- Extended `QuestionBankWorkspace` picker callbacks to pass the selected private
  question detail and revision ID, while preserving its existing one-argument
  callback behavior and lesson label.
- Added teacher-only route/template `teacher/assessments/` and the dashboard
  navigation link. No migration or assessment run/attempt behavior was added.
- Added scoped assessment workspace CSS and generated frontend bundle output.
- Added `tests/test_assessment_builder_browser.py` covering creation from a
  question bank, 3+4 point total, private preview, save, reopen, copy, English
  desktop, and Chinese mobile rendering.

## Prerequisite evidence

Task 21 assessment APIs and Task 13 question-bank workspace were present at
baseline. Task 11 fragment endpoint was reused for private pinned Markdown;
when the optional VaultPub renderer is unavailable it returns 503 and the
existing safe Markdown fallback remains visible.

## Verification

Passed:

- `cd frontend && bun run check`
- `cd frontend && bun run bundle`
- `pytest -q tests/test_assessment_builder_browser.py tests/test_assessment_definitions.py` — 5 passed
- `ruff check src/liveclassroom/views.py src/liveclassroom/urls.py tests/test_assessment_builder_browser.py`
- `python -m compileall -q src tests standalone`
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py check`
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run`
- `git diff --check`

Browser evidence is saved by the test under `.local/screenshots/` for English
desktop and Chinese 390px mobile. The test observed optional fragment 503
responses and verified fallback content. PostgreSQL concurrency, xcWebServer,
production static collection, load, and deployment behavior remain unverified.

## Shared checkout note

The checkout also contains concurrent Task 17 deck/presentation edits. A
minimal unmatched JSX brace in `StudentSession.tsx` was corrected so the shared
frontend type check could run; the coordinator should include that fix with the
Task 17 review. No files were staged or committed by this task.

## Next eligible work

Review the combined Task 17 and Task 22 frontend bundle, then continue with
assessment run/attempt work after the Task 23 backend schema is accepted.
