# Task 49 — integrated browser acceptance

## Status: PARTIAL

A broader real Chromium suite passed for the currently integrated teacher and student
surfaces. It exercises authenticated browser sessions through the package live server;
it is browser evidence only for the scenarios below, not a substitute for host,
PostgreSQL-concurrency, or load acceptance.

## Passed browser evidence

```text
tmux session: lc_task49_broader
log: .local/2026-09-09/reports/task49-browser-expanded-20260910.log
exit: .local/2026-09-09/reports/task49-browser-expanded-20260910.exit (0)
pytest -q tests/test_course_workspace_browser.py tests/test_question_bank_workspace_browser.py tests/test_deck_editor_browser.py tests/test_deck_presentation_browser.py tests/test_lesson_browser.py tests/test_lesson_sharing_browser.py tests/test_lesson_reuse_browser.py tests/test_student_assessment_browser.py tests/test_grading_editor_browser.py tests/test_presenter_notes_browser.py tests/test_vaultpub_browser.py
15 passed, 1 warning in 30.85s
```

The suite covers Course/Class workspace and question banks; deck edit and presentation;
lesson launch, live guest/student channels and reuse; named teacher sharing, preview and
an independently owned copy; assessment start, autosave, refresh/resume, submit and
English/Simplified-Chinese mobile views; objective grading controls; presenter-note
secrecy; and VaultPub Markdown/image rendering with its raw fallback. The existing
scenarios assert mount-aware reversed routes where relevant, authenticated sessions,
actual HTTP requests, mobile overflow and selected English/Chinese labels.

Durable screenshot artifacts from these runs include:

- `.local/screenshots/2026-09-09-course-workspace-desktop.png`
- `.local/screenshots/2026-09-09-course-workspace-mobile.png`
- `.local/screenshots/2026-09-09-question-bank-workspace-desktop.png`
- `.local/screenshots/2026-09-10-assessment-builder-desktop.png`
- `.local/screenshots/2026-09-10-assessment-builder-zh-mobile.png`
- `.local/screenshots/2026-09-10-student-assessment-mobile.png`
- `.local/screenshots/2026-09-10-student-assessment-zh-mobile.png`
- `.local/screenshots/2026-09-10-student-assessment-desktop.png`

The warning is Bleach's `NoCssSanitizerWarning` for an allowed style attribute in the
VaultPub browser fixture; the test passed and it is not treated as deployment evidence.

## Remaining acceptance

The full cross-feature matrix remains open: browser-visible Markdown/YAML import and
import-error recovery, `ContentShare` API/UI beyond the lesson-sharing surface, AI draft
review/acceptance, released-result CSV/JSON download controls, a timed exam expiring
while the browser is closed, manual correction/regrade and release-policy dimensions in
one browser journey, explicit browser network/console capture for every flow, and an
actual mounted `/classroom/` host run. The supplied suite does not establish all flows
in both languages and both widths. Task 49 therefore remains **PARTIAL**.

Host, optional-provider, PostgreSQL-concurrency, multi-worker reconnect and load
acceptance remain separate tasks.
