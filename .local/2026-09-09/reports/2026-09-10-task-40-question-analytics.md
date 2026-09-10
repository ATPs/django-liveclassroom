# Task 40 — retained question analytics

## Changes

Added staff-scoped analytics derived from immutable assigned attempt-item manifests. Each result keeps its run/revision/fingerprint context, so later source edits and pooled question assignments cannot change historical denominators.

`question_analytics()` reports assigned, answered, graded, pending/ungraded counts, mean normalized score, full-credit rate, option selection counts, common wrong choices, and participation trends. It never treats a pending manual grade as incorrect. Raw answers are absent by default and require the existing explicit grading capability through `include_named=true`.

Added mount-safe read-only APIs for one assessment run and one class:

- `GET api/v1/assessment-runs/<public_id>/question-analytics/`
- `GET api/v1/classes/<class_id>/question-analytics/`

## Verification

Passed:

```text
PYTHONPATH=.:src pytest -q tests/test_question_analytics.py
2 passed
PYTHONPATH=.:src ruff check src/liveclassroom/services/question_analytics.py src/liveclassroom/api_question_analytics.py src/liveclassroom/urls.py
All checks passed
PYTHONPATH=.:src python standalone/manage.py check
System check identified no issues
PYTHONPATH=.:src python standalone/manage.py makemigrations --check --dry-run
No changes detected
```

The focused tests cover retained assigned-item denominators, choice distribution, fully graded mean, raw-answer redaction, explicit named response access, mounted API routes, and unrelated-user denial.

## Limits

No analytics dashboard UI, browser screenshots, host capability adapter, PostgreSQL concurrency, or load evidence was run. Task 46 will introduce host capability extension points; its configured named-response policy must be applied as a follow-up to this package-default permission boundary.
