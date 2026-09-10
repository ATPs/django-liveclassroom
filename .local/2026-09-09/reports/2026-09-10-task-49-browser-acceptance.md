# Task 49 — integrated browser acceptance

## Status: PARTIAL

A real Chromium suite passed for the available teacher authoring and teaching surfaces. The run used the package live server and covered course workspace, question bank workspace, deck editor, assessment builder, lesson/presentation paths, and both desktop/mobile viewports where the existing scenarios define them.

## Evidence

```text
tmux session: lc_task49_browser_20260910
log: .local/2026-09-09/reports/task49-browser-20260910.log
pytest -q tests/test_course_workspace_browser.py tests/test_question_bank_workspace_browser.py tests/test_deck_editor_browser.py tests/test_assessment_builder_browser.py tests/test_lesson_browser.py
7 passed in 21.54s
```

The command exited `0`. This is real Playwright/Chromium evidence, not a static or unit-test substitute.

## Remaining acceptance

The required complete cross-feature scenario remains open: new named content sharing/copy UI, Markdown/YAML importer UI, AI draft review, released result export, reconnect/timed expiry, manual correction/regrade, bilingual end-to-end teacher/student flow, explicit screenshots/network-console capture, and mounted `/classroom/` host proof. No full browser acceptance claim is made from this focused suite.
