# Task 27 — Student assessment UI

- Task ID: 27 (`student-assessment-ui`)
- Status: COMPLETE for the package-owned student surface; host login/deployment and production acceptance remain unverified.
- Baseline: `58d8417` (`Add presentation cues and assessment saving`)
- Final commit: `58d8417` plus the uncommitted task changes in the shared main checkout. The coordinator will stage and commit the integrated batch.

## Delivered

- Added `AssessmentAttemptView` and the mount-safe route `assessment-attempt` at `assessments/runs/<public_id>/`. The route requires an existing authenticated account and does not create an attempt while rendering.
- Added `frontend/src/surfaces/assessments/StudentAssessment.tsx` and registered it in `frontend/src/app.ts`.
- The surface fetches safe run instructions, requires an explicit Start / resume action, fetches assigned immutable items and saved own answers, and resumes a saved attempt after refresh or reopening using only a server-issued attempt ID in local storage. Unsent answer text is never persisted there.
- Added type descriptor response controls for single choice, true/false, multiple choice, numeric, rating, ranking, short text, word cloud, and essay items. Prompts use the existing safe `MarkdownView` and optional fragment context.
- Added `SerializedAutosaveController`: 500 ms per-item debounce, one in-flight save per item, stable UUID request IDs for retry, conflict/offline/retry statuses, and final flush before submit.
- Added an inline submit confirmation, expected-version submission, double-click guard, immutable submitted confirmation, and score/feedback withholding before later release tasks.
- Added bilingual English/Simplified Chinese strings and scoped desktop/mobile styles. The available-run metadata now reports that an attempt is available while retaining prompt delivery behind the authenticated attempt API.

## Changed paths

- `src/liveclassroom/views.py`
- `src/liveclassroom/urls.py`
- `src/liveclassroom/templates/liveclassroom/assessment_attempt.html`
- `src/liveclassroom/services/assessment_runs.py`
- `frontend/src/app.ts`
- `frontend/src/locales.ts`
- `frontend/src/surfaces/assessments/StudentAssessment.tsx`
- `src/liveclassroom/static/liveclassroom/liveclassroom.css`
- `src/liveclassroom/static/liveclassroom/app.js` and generated chunks
- `tests/test_student_assessment_browser.py`

## Verification

- `cd frontend && bun run check` — passed.
- `cd frontend && bun run bundle` — passed; 42 modules bundled.
- `pytest -q tests/test_student_assessment_browser.py` — 2 passed, including authenticated page redirect and Chromium start/save/refresh/submit at 390 px.
- `pytest -q tests/test_assessment_runs.py tests/test_assessment_attempts.py tests/test_attempt_autosave.py tests/test_attempt_submission.py tests/test_student_assessment_browser.py` — 20 passed.
- `ruff check src/liveclassroom/views.py src/liveclassroom/services/assessment_runs.py tests/test_student_assessment_browser.py` — passed.
- `python -m compileall -q src/liveclassroom/views.py tests/test_student_assessment_browser.py` — passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py check` — passed.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run` — passed; no migration required.
- `git diff --check` — passed.

Browser evidence covers an authenticated learner, English and Simplified Chinese, 390 px and 1440 px, start/resume, choice save, refresh/reopen, confirmation, final submit, score hiding, screenshots, and no horizontal overflow. PostgreSQL concurrency, host-mounted `/classroom/`, load behavior, and deployment/static collection remain unverified.

## Boundaries and follow-up

No deadline/timer, pool, grading, proctoring, guest durable attempt, or assessment model changes were added. The coordinator should review the shared diff, retain unrelated task 28 changes, stage only task-owned paths, run the final integrated frontend bundle, and commit the batch. Task 28 timing and task 29 pool work remain eligible after their prerequisites are reviewed.
