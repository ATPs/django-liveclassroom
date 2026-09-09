# 32 — manual grading completion report

- Status: READY FOR REVIEW
- Date/time and timezone: 2026-09-10, Asia/Shanghai
- Worktree and branch: main checkout, `main`
- Baseline: `ef4021f`; portable content was committed independently as `146aa64`
- Runtime: zsh, conda `django`, `PATH=/data/p/bin:$PATH`, `PYTHONPATH=.:src`
- Migration: `0016_manual_grade_comments`, additive and dependent on `0015_assessment_grades`

## Delivered behavior

- Provides a submitted subjective-answer queue for assessment owners and authorized
  course teachers/assistants, using immutable retained prompts and answers.
- Allows explicit manual normalized score or awarded points, with bounded comment and
  required reason. Zero is a valid human decision. Every manual grade appends an audit
  decision with actor, reason, comment, score, and retained answer; the aggregate is
  recomputed from stored item grades.
- Adds mount-safe queue and grade APIs plus a bilingual responsive teacher queue.

## Changed files

- `src/liveclassroom/models/grading.py`
- `src/liveclassroom/migrations/0016_manual_grade_comments.py`
- `src/liveclassroom/services/assessment_grading.py`
- `src/liveclassroom/services/manual_grading.py`
- `src/liveclassroom/api_grading.py`
- `src/liveclassroom/urls.py`
- `frontend/src/surfaces/assessments/AssessmentBuilder.tsx`
- `frontend/src/surfaces/assessments/ManualGradingQueue.tsx`
- `src/liveclassroom/static/liveclassroom/liveclassroom.css`
- `src/liveclassroom/static/liveclassroom/app.js`
- `tests/test_manual_grading.py`, `tests/test_manual_grading_api.py`

## Verification

| Check | Result |
| --- | --- |
| `pytest -q tests/test_manual_grading.py tests/test_assessment_grading.py tests/test_attempt_submission.py tests/test_assessment_timing.py` | PASS — 29 passed |
| `ruff check` for task files | PASS |
| `python -m compileall -q src tests standalone` | PASS |
| `python standalone/manage.py check` | PASS — no issues |
| `cd frontend && bun run check && bun run bundle` | PASS |
| `git diff --check` | PASS |

The release-control worker was concurrently preparing model changes, so final
migration-drift evidence is deferred until that worker writes the next migration leaf.
Browser, host, PostgreSQL concurrency, load, and deployment evidence are unverified.
