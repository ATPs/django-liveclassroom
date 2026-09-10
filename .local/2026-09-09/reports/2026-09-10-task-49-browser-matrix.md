# Task 49 — focused browser matrix follow-up

Date: 2026-09-10  
Baseline: `eba112d` (`Refresh xcWebServer activation readiness`)  
Execution: main checkout, package standalone `LiveServer`, conda `django`
environment, Playwright Chromium, `PYTHONPATH=.:src`.

This follow-up adds three focused real-browser scenarios for acceptance gaps
that were previously represented only by service/API tests. The browser made
the same-origin requests with authenticated cookies; database reads only
verified the durable result after the visible interaction.

## Changes found and fixed

* The visual lesson builder posts Markdown steps as `kind: "markdown"` with a
  `content` object. `add_step_api` did not translate that shape into the normal
  `liveclassroom.markdown` activity definition and returned a 500. The API now
  creates the owned activity definition and uses the existing flow-step
  authorization path.
* `PresentationSourcePicker` stripped the trailing slash returned by
  `apiEndpoint`, so its collection request to `presentation/cues` missed the
  Django route on a no-redirect host. The picker now retains collection
  slashes and concatenates cue item paths correctly. The frontend bundle was
  rebuilt.

## Browser evidence

Command (run in detached tmux session `lc_task49_matrix5`):

```text
pytest -q tests/test_task49_browser_matrix.py
3 passed, 1 warning in 9.99s
```

Scenarios passed:

1. A teacher creates a lesson through the builder dialog, adds Markdown via
   the actual form, opens its visible preview, receives a deliberate temporary
   detail API 503, sees the recoverable error, reloads successfully, then
   switches to Simplified Chinese at 390px with no horizontal overflow. The
   expected 503 is recorded in the browser console and response capture.
2. A teacher presents a two-slide native deck to both channels. Chromium
   verifies teacher-only notes on the teacher surface, no notes on display or
   guest student surfaces, moves only the display channel with the keyboard
   ArrowRight action, reloads display and teacher at slide 2, and confirms the
   guest participant remains at slide 1 after reconnect. Display is English
   desktop; the guest is Simplified Chinese at 390px.
3. A learner uses Chromium to read their assessment history, retained review,
   and release-filtered result. A teacher uses a Chinese 390px page to read
   run progress and the class grade summary, which contain no answer material.
   A different authenticated user receives 404 for the learner review/result
   and teacher progress/summary URLs. The learner page is English desktop and
   the teacher page is Simplified Chinese mobile.

Screenshots:

* `.local/2026-09-09/screenshots/task49/2026-09-10-task49-builder-en-desktop.png`
* `.local/2026-09-09/screenshots/task49/2026-09-10-task49-builder-zh-mobile.png`
* `.local/2026-09-09/screenshots/task49/2026-09-10-task49-deck-zh-mobile.png`
* `.local/2026-09-09/screenshots/task49/2026-09-10-task49-review-en-desktop.png`
* `.local/2026-09-09/screenshots/task49/2026-09-10-task49-progress-zh-mobile.png`

The VaultPub test fixture emitted the existing Bleach
`NoCssSanitizerWarning`; it did not fail the browser checks.

## Other verification

* `ruff check src/liveclassroom/api_flows.py tests/test_task49_browser_matrix.py` — passed.
* `bun run check` — passed (`tsc --noEmit`).
* `bun run bundle` — passed and updated the package browser bundle.
* `git diff --check` — passed.
* `python -m compileall -q tests/test_task49_browser_matrix.py` — passed.

The focused test output is retained at
`.local/2026-09-09/reports/task49-matrix-20260910-final.log`; its exit marker
is `task49-matrix-20260910-final.exit`.

## Boundaries that remain

The synchronous Django `LiveServer` does not provide the ASGI websocket route,
so Chromium records the expected `WebSocket connection ... Unexpected response
code: 404` during the deck pages. The guest also makes the expected initial
pre-join participant-state request and receives 403 before the join form is
submitted. The test keeps these harness/lifecycle responses explicit while
requiring the presentation cue and other HTTP API requests to succeed.

This package run does not prove a mounted `/classroom/` xcWebServer browser
journey, provider-backed AI behavior, sustained production load, or deployment
restart behavior. Those remain the host/load acceptance boundaries in the
Task 49 and Task 53 records.
