# Task 19 deck Markdown portability

Status: PARTIAL / READY FOR COORDINATOR REVIEW

- Task ID: 19
- Baseline and current checkout commit: `cb1caaf` (the task was implemented as uncommitted work in the shared main checkout)
- Prerequisites: task 15 native deck editor and task 16 immutable deck snapshots are present; task 18 is concurrently editing deck theme/rendering helpers.

## Delivered

- `liveclassroom.importers.decks.preview_deck_import(actor, text, assets)` delegates frontmatter and slide segmentation to VaultPub's public `parse_frontmatter` and `segment_slides` APIs. It returns a JSON-ready `draft`, one-based slide errors, and `valid`, without database writes.
- `liveclassroom.importers.decks.import_deck(actor, validated_draft)` validates the complete draft and delegates the atomic row creation to the existing deck service. Preview keys, order, Markdown, notes, and approved local asset IDs are retained.
- `liveclassroom.services.deck_export.export_deck_markdown(actor=..., deck=..., include_notes=False)` is owner-only, excludes private notes by default, and emits deterministic UTF-8 Markdown frontmatter and horizontal-rule slide separators. `deck_export_markdown` and `export_markdown` aliases are provided.
- `liveclassroom.api_deck_portability` contains owner-scoped preview, import, and text export views. The coordinator must register them in `urls.py` because that shared file is concurrently edited.
- The deck workspace has bilingual import preview/create controls and owner export with an explicit private-notes checkbox. It derives the pending endpoints from the existing deck API root.
- The importer recognizes `<!-- liveclassroom:notes --> ... <!-- /liveclassroom:notes -->` and `<!-- speaker-notes --> ... <!-- /speaker-notes -->` only outside fenced code blocks. External/data/javascript image URLs and unresolved image references are reported before any import.
- No migration or dependency change was made.

## Verification

Passed:

```text
pytest -q tests/test_deck_import_export.py   # 5 passed
ruff check src/liveclassroom/importers/decks.py src/liveclassroom/services/deck_export.py src/liveclassroom/api_deck_portability.py tests/test_deck_import_export.py
python -m compileall -q src/liveclassroom/importers/decks.py src/liveclassroom/services/deck_export.py src/liveclassroom/api_deck_portability.py tests/test_deck_import_export.py
git diff --check
```

The focused tests cover fenced `---` content, Unicode and equations, private-note round trips, asset authorization/error reporting, owner checks, and no-write invalid imports.

Not run in this task: browser/Playwright evidence, full package checks, mounted API checks (the coordinator has not yet registered the new views), PostgreSQL, host integration, load, and distribution packaging. These must remain separate acceptance claims.

## Coordinator integration

Register these views from `liveclassroom.api_deck_portability` in the package URL list:

- `POST api/v1/decks/import/preview/` -> `deck_import_preview`, name `api-v1-deck-import-preview`
- `POST api/v1/decks/import/` -> `deck_import`, name `api-v1-deck-import`
- `GET api/v1/decks/<int:deck_id>/export/` -> `deck_export`, name `api-v1-deck-export`

Stage this report and the six task files with the integrated task batch. Do not stage `.gitignore`, `AIM.md`, `pyproject.toml`, or concurrent task 18/24 changes accidentally.
