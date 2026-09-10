# Task 49 — browser acceptance follow-up

## Status: PARTIAL

This follow-up adds four real Chromium scenarios for integrated package paths
that were not covered by the earlier Task 49 run. The tests use the package
live server, authenticated Django accounts, actual page interactions, and
same-origin browser requests. They do not claim mounted xcWebServer or
production evidence.

## Passed browser evidence

```text
pytest -q tests/test_task49_browser_acceptance.py
4 passed in 14.19s
```

The suite covers:

* a deterministic in-process AI backend and synchronous worker dispatch. The
  teacher selects a model and question draft type, submits a prompt in the
  real Flow Builder, reviews the generated proposal, explicitly accepts it,
  and the browser-visible accepted state is checked against the created
  ActivityDefinition. English desktop and Simplified Chinese 390px mobile
  pages were checked for overflow and screenshots were captured;
* a submitted essay shown in the real Manual grading queue. The teacher
  enters awarded points, comment, and required audit reason, saves the grade,
  and the queue becomes empty. English desktop and Simplified Chinese mobile
  states were checked;
* a two-second exam started by a real student page, followed by closing the
  student tab. A later authenticated attempt read finalizes the due attempt
  through the server path, displays the submitted state, and confirms the
  persisted finalization reason is `expired`;
* teacher CSV download and JSON result export through Chromium, including
  spreadsheet-formula neutralization and omission of private manifest text;
  teacher releases the answer dimension through the browser and the student
  Simplified Chinese mobile page then sees the released answer in its own JSON
  and CSV exports.

Screenshots were written under
`.local/2026-09-09/screenshots/task49/`:

* `2026-09-10-task49-ai-review-en-desktop.png`
* `2026-09-10-task49-ai-review-zh-mobile.png`
* `2026-09-10-task49-manual-grade-en-desktop.png`
* `2026-09-10-task49-manual-grade-zh-mobile.png`
* `2026-09-10-task49-export-en-desktop.png`
* `2026-09-10-task49-export-zh-mobile.png`

The tests also collect browser console errors and API responses with status
400 or above for the exercised pages; none were observed. The focused run was
executed with zsh, conda `django`, `/data/p/bin` on `PATH`, and
`PYTHONPATH=.:src`.

## Remaining acceptance

Task 49 remains partial. The package has no general teacher results landing
page or browser controls for audited regrade, so regrade and the complete
manual-correction/release journey remain API/service evidence rather than
browser evidence. This follow-up exercises the manual grade form and the
release API from Chromium, but does not claim a regrade UI.

The full matrix still needs all mandatory preparation, presentation, assessment,
review, privacy, loading/error, keyboard, language, and viewport scenarios in
one repeatable journey. Mounted `/classroom/` browser evidence, AI provider
deployment behavior, browser network traces for every previous scenario,
PostgreSQL concurrency, sustained load, and host restart/deployment behavior
remain outside this run.
