# Task 45 — reviewed AI authoring drafts

## Changes

Added durable private `AuthoringDraft` proposals for questions, decks, and assessment definitions. An authoring request can state its artifact type; the backend must return a strict structured envelope. The package validates the draft before storing it, records only a safe typed payload and source fingerprints, and fails invalid output with the stable `invalid_draft` job error.

Teachers can retrieve, accept, or reject a draft through mount-safe endpoints. Acceptance is transactionally idempotent and creates an independent owned object or updates an explicitly selected owned target after version checking. It never publishes, shares, launches, grades, or overwrites content without explicit review. The authoring panel now lets a teacher select the draft type and review/accept/reject generated drafts in English and Simplified Chinese.

## Verification

Passed:

```text
PYTHONPATH=.:src pytest -q tests/test_authoring_drafts.py tests/test_authoring.py
13 passed
PYTHONPATH=.:src ruff check src/liveclassroom/models/authoring.py src/liveclassroom/services/authoring.py src/liveclassroom/services/authoring_drafts.py src/liveclassroom/api_authoring.py tests/test_authoring_drafts.py
All checks passed
PYTHONPATH=.:src python standalone/manage.py check
System check identified no issues
PYTHONPATH=.:src python standalone/manage.py makemigrations --check --dry-run
No changes detected
cd frontend && bun run check
$ tsc --noEmit
git diff --check
```

Tests cover typed question/deck/assessment validation and independent acceptance, private draft persistence, invalid AI envelopes, owner-only transitions, idempotent rejection, and exact attachment reauthorization.

## Limits

No live external AI backend, browser screenshot, host integration, or browser test was run. The package keeps model/backend identifiers generic and does not persist credentials or provider diagnostics.
