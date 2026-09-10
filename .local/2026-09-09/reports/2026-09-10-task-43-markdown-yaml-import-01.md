# Task 43 — Markdown/YAML portable import

Status: COMPLETE (service/parser scope; HTTP/UI integration remains coordinator-owned).

Baseline was `8405cef` (`Add assessment exam controls review and progress`); task 39
was committed while this work was in progress, leaving the review head at
`01da6e8` (`Add class and course grade summaries`). Existing dirty user paths and
unrelated task 44 sharing files were preserved.

## Implemented

- `src/liveclassroom/importers/markdown_portable.py`
  - Calls VaultPub public `parse_frontmatter`, `segment_slides`, and `slide_options`
    when parsing Markdown.
  - Supports explicit `question`, `deck`, `lesson`, and `assessment` documents,
    plus UTF-8 `.yaml`/`.yml` mappings through a duplicate-key rejecting safe
    PyYAML loader.
  - Produces the task 42 portable envelope and delegates canonical validation to
    `validate_portable`.
  - Preserves Markdown slide order, fenced code, math/Mermaid source, lesson quiz
    syntax, metadata, private answer keys, and approved direct sibling asset
    references.
  - Reports path/code/message errors with line numbers where YAML supplies them;
    rejects unsafe URLs and paths, unknown fields, malformed YAML, invalid fences,
    unreferenced resources, sensitive runtime/submission fields, and size limits.
- `src/liveclassroom/services/markdown_import.py`
  - Adds non-writing `preview_markdown_import` and atomic
    `commit_markdown_import` wrappers.
  - Re-parses and fingerprint-checks the exact source before calling task 42
    `import_portable`.
  - Uses existing `AuthoringCommandReceipt` for idempotent replay without a new
    migration.
- `src/liveclassroom/importers/__init__.py` exports the parser draft types.
- `tests/test_markdown_portable_import.py` covers deck segmentation, fenced source,
  question YAML, lesson quiz delegation, assessment commit/idempotency, stale
  drafts, malformed/duplicate YAML, unsafe URLs/paths, unknown fields, no-write
  previews, and invalid code fences.

VaultPub was imported from `/data/p/xiaolong/vaultpub/src/vaultpub`; the public
frontmatter and slide APIs were available. The single-file input note
`dev/2026090901-single-markdown-input.md` was reviewed. No private VaultPub helper,
VaultPub route, migration, or file-system path read was added.

## Verification

- `pytest -q tests/test_markdown_portable_import.py` — PASS, 7 tests.
- Ruff on the four task files — PASS.
- Targeted compileall — PASS.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py check` — PASS.
- `env -u DJANGO_SETTINGS_MODULE python standalone/manage.py makemigrations --check --dry-run` — PASS.
- `git diff --check` — PASS.

Frontend/Playwright, mounted HTTP routes, host integration, PostgreSQL, load, and
production behavior were not run. The two task 43 HTTP routes and preview UI remain
for the coordinator's follow-up integration because they share URL/editor ownership.
