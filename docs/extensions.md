# Extension contracts

LiveClassroom keeps optional document, slide, AI, host, grading, export, and
frontend integrations behind small Python contracts.  The package does not
import VaultPub, an AI SDK, host models, or frontend code while
`liveclassroom.extensions` is imported.  A provider is loaded only after its
host explicitly names it in settings.

## Registration

The supported protocol version is `1`.  Extension keys are stable namespaced
package names such as `example.liveclassroom.reviewed_grading`; a key must not
be reused for a different contract.  Each implementation declares
`protocol_version` and a finite `capabilities` set.  Capability names are
validated against the package allowlist.  Duplicate keys, missing methods,
unsupported versions, malformed manifests, and unsafe capabilities raise
`ExtensionConfigurationError` with a short message.

The generic loader accepts instances, classes, registration records, or
explicit dotted paths.  Mapping entries are processed by their sorted setting
key, while the implementation's own key is authoritative:

```python
from liveclassroom.extensions import load_extensions

extensions = load_extensions({
    "reviewed_grading": "examples.extension.ExampleGradingExtension",
}, kind="grading", required_methods=("validate", "score"))
grader = extensions.get("example.liveclassroom.reviewed_grading")
```

For a Django installation, the same declaration can be placed in
`LIVECLASSROOM["EXTENSIONS"]`.  The bundled standalone project and an existing
host mounted at `/classroom/` use the same package setting; the mount prefix
does not change extension keys or payloads.  A host may instead use the typed
adapters `adapt_activity_type`, `adapt_frontend_manifest`,
`adapt_ai_backend`, `adapt_ai_job_worker`, `adapt_host_adapter`, and
`adapt_slide_provider`.  They wrap the existing activity, content-provider,
AI, host-adapter, and grading APIs without replacing their registries or
changing their response shapes.

## Contracts

`DocumentExtension` implements
`render(request, reference: ContentReference, *, mode) -> HttpResponseBase`.
`GradingExtension` implements `validate(definition) -> dict` and
`score(answer, definition) -> dict`.  `ExportExtension` implements
`export(*, actor, object_kind, object_id) -> dict`.

The typed records also cover the existing `ActivityType`, frontend manifest,
AI backend and job worker, host adapter, and slide provider contracts.  A
frontend manifest has these four non-empty surfaces:

```python
{
    "editor": "vendor.package/editor.v1.js",
    "student_renderer": "vendor.package/student.v1.js",
    "display_renderer": "vendor.package/display.v1.js",
    "analytics": "vendor.package/analytics.v1.js",
}
```

## Authorization and errors

Loading an extension grants no data access.  Use `invoke_document`,
`invoke_grading_validate`, `invoke_grading_score`, or `invoke_export` with an
explicit `actor`, request, resource, and an authorization callback.  The
callback must return the literal `True`; a missing, false, non-boolean, or
failing authorization denies the operation.  Authorization remains owned by
the host or the package service that knows the resource.  An extension cannot
silently grant itself permission.

Invocation catches provider failures and raises `ExtensionInvocationError`
without exposing a traceback.  Returned grading and export payloads must be
JSON-like dictionaries and are rejected if they contain credential, secret,
token, reasoning, or traceback fields.  Document extensions must return a
Django `HttpResponseBase`.  Credentials, protected source text, and provider
diagnostics are not persisted by these contracts.

If an optional provider is absent, its registration is simply absent.  Core
activities and standalone teaching continue to use the existing registries;
the host can report the provider as unavailable and offer a safe fallback.

## Version upgrades

Protocol versions are independent of package releases.  A compatible change
keeps version `1` and the documented payload shape.  A breaking contract
requires a new protocol version and a new migration or adapter path; hosts
should register the new key during rollout and remove the old key only after
stored references have been upgraded.  There is no marketplace or arbitrary
code execution path: importing a configured dotted path is the same explicit
deployment choice as the existing host provider and AI settings.

The dependency-free example is [examples/extension.py](../examples/extension.py).
