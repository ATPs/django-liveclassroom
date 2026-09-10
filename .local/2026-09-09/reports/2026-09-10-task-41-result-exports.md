# Task 41 — authorized assessment result exports

- Status: COMPLETE (backend/API scope)
- Date/time and timezone: 2026-09-10, Asia/Shanghai
- Baseline: `873ffaf` (retained question analytics)
- Final commit: recorded by the coordinator after scoped commit
- Migration leaf: unchanged; no migration added

## Delivered behavior

- Added `services/assessment_exports.py`, a transaction-consistent projection over
  retained attempts, answer revisions, current item/attempt grades, and grade decisions.
- Teacher CSV exports select the latest submitted attempt per learner and run; JSON
  retains all authorized attempts and audit rows. Optional `details=true` adds retained
  item keys/types, answers, current grade, and feedback to CSV.
- Teacher exports require the existing explicit `can_grade_attempt()` staff scope for
  every requested run/class. Test participants are excluded by course session scope.
- Student exports use the existing result-release dimensions and are limited to the
  authenticated attempt owner. Keys, explanations, comments, and scores are emitted
  independently according to release state.
- Added mount-safe streaming endpoints:
  `assessment-runs/<public_id>/results/export/`,
  `classes/<class_id>/results/export/`, and
  `attempts/<public_id>/result/export/`.
- Added UTC ISO timestamps, decimal strings, private no-store download headers, safe
  filenames, and spreadsheet formula neutralization for user text. Existing release
  serialization now handles absent grade rows without raising a one-to-one lookup error.

## Verification

Passed:

```text
PYTHONPATH=.:src pytest -q tests/test_assessment_exports.py
3 passed
PYTHONPATH=.:src pytest -q tests/test_result_release.py tests/test_result_release_api.py tests/test_assessment_review.py tests/test_grade_summaries.py tests/test_question_analytics.py
17 passed
PYTHONPATH=.:src ruff check src/liveclassroom/services/assessment_exports.py src/liveclassroom/api_assessment_exports.py tests/test_assessment_exports.py src/liveclassroom/urls.py src/liveclassroom/services/result_release.py
All checks passed
PYTHONPATH=.:src python standalone/manage.py check
System check identified no issues
```

Browser screenshots, host authorization, PostgreSQL concurrency, load, and frontend
bundle evidence were not run. The export implementation is backend-only.
