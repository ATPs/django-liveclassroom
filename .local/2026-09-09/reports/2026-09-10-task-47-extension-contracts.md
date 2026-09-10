# Task 47 — versioned extension contracts

## Changes

Added `liveclassroom.extensions`, a dependency-free set of versioned protocols and deterministic registries for document rendering, grading, exports, activity/frontend manifests, AI backends/job workers, host adapters, and slide providers. Registrations require a namespaced key, protocol version, declared safe capabilities, and required callable methods; duplicate, malformed, unsupported, and absent extensions fail with safe deterministic errors.

Added a standalone example extension, focused contract tests, and `docs/extensions.md` covering settings registration, mounted `/classroom/` use, explicit actor/request authorization, graceful optional absence, and compatibility adapters for existing registries. The Django configuration checks validate declared extension settings without importing optional extensions at package import time.

## Verification

```text
PYTHONPATH=.:src pytest -q tests/test_extension_examples.py
6 passed
PYTHONPATH=.:src ruff check src/liveclassroom/extensions.py examples/extension.py tests/test_extension_examples.py src/liveclassroom/conf.py src/liveclassroom/checks.py
All checks passed
PYTHONPATH=.:src python standalone/manage.py check
System check identified no issues
git diff --check
```

## Limits

No plugin marketplace, arbitrary extension execution surface, external host package, or host deployment was added. Existing provider/activity/AI behavior remains behind their current adapters; optional extensions are only loaded by explicit host configuration.
