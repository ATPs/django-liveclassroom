# Final verification — migration isolation and authoring portability repair

The final package suite exposed two independent regressions that were hidden by
focused runs.

- The metadata and assessment-section migration probes restored SQLite only to
  intermediate migrations. Later tests then queried columns introduced by
  migration `0019` or `0021`, including `shuffle_questions` and
  `artifact_type`, against an older schema. Both probes now restore the current
  `0021_authoringjob_artifact_type_authoringdraft` leaf in `finally`.
- AI assessment drafts retain UUID item keys for normal assessment behavior.
  The Task 42 portable-validation adapter requires short local keys, so it now
  derives `item-1`, `item-2`, and so on only for its temporary validation
  document. It does not change the retained draft payload or the created
  assessment item keys.

Focused verification in zsh with conda `django`, `/data/p/bin` on `PATH`, and
`PYTHONPATH=.:src`:

```text
pytest -q tests/test_question_metadata_migration.py \
  tests/test_assessment_sections_migration.py \
  tests/test_authoring_drafts.py::test_validate_and_accept_question_deck_and_assessment_are_independent
3 passed in 12.04s
ruff check src/liveclassroom/services/authoring_drafts.py \
  tests/test_question_metadata_migration.py tests/test_assessment_sections_migration.py
All checks passed
```

The preceding full-suite run reached `557 passed, 14 skipped` and exposed the
schema-leakage failures before these repairs. Its static stage also reported
five unrelated existing Ruff formatting errors in `models/__init__.py` and
`tests/test_content_sharing.py`; these are outside this narrow repair and must
be resolved before calling the repository-wide Ruff check clean.
