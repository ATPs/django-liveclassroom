# Task 46 — reusable host adapters

## Changes

Added a policy-free host integration protocol in `liveclassroom.integrations.host`. Hosts can configure an instance or dotted path through `LIVECLASSROOM['HOST_ADAPTER']` to resolve a minimal host actor and decide authoring, delivery, roster, named-response, grading, and course/roster capabilities. Missing, malformed, non-boolean, or failing adapters deny access.

Standalone behavior remains usable through `DefaultHostAdapter`: existing package permissions continue to authorize package-owned teacher actions, while host-only roster/named-response/grading APIs stay denied unless the package has already explicitly granted the matching action.

Added hooks at activity authoring, assessment publication, attempt delivery, grading, named analytics, session admission, named analytics/export, and system configuration checks. The adapter never imports host models or creates attendance or account links. `examples/host_adapter.py` documents the minimal configuration.

## Verification

Passed:

```text
PYTHONPATH=.:src pytest -q tests/test_host_adapters.py tests/test_api_security.py
13 passed
PYTHONPATH=.:src ruff check [task-46 changed modules and test]
All checks passed
PYTHONPATH=.:src python standalone/manage.py check
System check identified no issues
PYTHONPATH=.:src python standalone/manage.py makemigrations --check --dry-run
No changes detected
git diff --check
```

Tests cover standalone defaults, request-aware delegated fake adapters, per-call policy changes, fail-closed malformed configuration, no-roster default, and authoring denial before persistence. The focused API-security suite also passed after resolving the service import boundary.

## Limits

No xcWebServer adapter, browser test, host database, deployment, or external identity/roster provider was changed or verified. Task 53 remains responsible for an authorized host rollout.
