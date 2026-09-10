# Task 44 — named content sharing and independent copies

## Changes

Added the explicit, revocable `ContentShare` model and migration `0020_content_shares` for exact questions, question banks, native decks, and assessment definitions. The owner can create, list, and idempotently revoke one grant per recipient/resource.

Recipient copies are made through a new graph-scoped portable export path. The source owner is never impersonated. The active grant is locked and rechecked; every traversed dependency and asset must belong to that source owner, while provider-backed activity references are validated for the recipient. The canonical portable importer then creates an independent, recipient-owned graph atomically.

Added mount-safe APIs:

- `GET` / `POST` `api/v1/content-shares/`
- `DELETE` `api/v1/content-shares/<id>/`
- `POST` `api/v1/content-shares/<id>/copy/`

API replies provide grant metadata and created-object summaries, never a protected source definition. There is no anonymous/public sharing or runtime/session sharing.

## Verification

Passed:

```text
PYTHONPATH=.:src pytest -q tests/test_content_sharing.py tests/test_portable_content.py
13 passed
ruff check src/liveclassroom/services/portable_content.py src/liveclassroom/services/sharing.py src/liveclassroom/api_sharing.py src/liveclassroom/urls.py
All checks passed
git diff --check
```

The focused scenarios cover exact/idempotent grant creation, recipient and stranger authorization, independent copy behavior after source mutation, revocation, foreign dependency rejection, owner/recipient API boundaries, and source-text non-disclosure.

## Limits

No teacher workspace control or browser flow was added because the current authoring workspace has no shared common entry point for all four resource types. Host-specific provider policy, authenticated host-browser coverage, PostgreSQL concurrency, and load behavior remain unverified.
