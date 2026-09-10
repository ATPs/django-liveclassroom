# Task 41 — authorized assessment exports

## Changes

Added a retained-result projection shared by CSV and JSON downloads. Teacher exports require the existing explicit grading/named-result capability, select the latest submitted attempt per student for the CSV summary, and preserve authorized attempt/item/audit data in JSON without question manifests, answer keys, private notes, or unauthorised comments.

Student downloads use the task-34 release policy and expose only the requester’s own released dimensions. CSV neutralizes spreadsheet formulas in user text, uses UTF-8 quoting, controlled decimal values, UTC timestamps, and private/no-store responses.

Added mount-safe endpoints for one attempt, assessment run, and class result download.

## Verification

Passed:

```text
PYTHONPATH=.:src pytest -q tests/test_assessment_exports.py tests/test_authoring_drafts.py
7 passed
```

Focused export scenarios consume streaming content and cover CSV formula neutralization, Unicode/newline handling, latest result selection, foreign scope denial, student release redaction, and private cache headers.

## Limits

No export-button UI, browser screenshots, host policy adapter, PostgreSQL consistency/concurrency, or load evidence was run. The result projection uses one atomic query/serialization scope; a later task will provide combined deployment acceptance.
