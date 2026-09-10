# Task 50 — VaultPub artifact follow-up

## Status: PARTIAL — current optional artifact cannot be built

This follow-up tested the current VaultPub source revision independently of its editable
installation. It confirms that LiveClassroom's optional integration needs a compatible,
installable VaultPub wheel; it does not obtain that evidence by importing the sibling
checkout.

## Baseline and method

- LiveClassroom: `979f071` (`Exercise two-classroom realtime reconnect load`).
- VaultPub: `fec041f1e36f7f290da24b47e62da03ef03528b5` (`include single markdown input`).
- Runtime: zsh, conda `django`, Python 3.12, Hatchling 1.27.0.
- Both repositories were copied with `git archive HEAD` to one disposable directory.
  No upstream source, shared environment, host service, host database, or host static
  files were changed.

The run built a LiveClassroom wheel successfully. It then ran
`python -m hatchling build -t wheel` in the archived VaultPub source, which invokes
VaultPub's frontend build hook before packaging.

## Result

The VaultPub frontend build completed, but Hatchling rejected the wheel creation:

```text
ValueError: A second file is being added to the wheel archive at the same path:
`vaultpub/django_app/static/vaultpub/assets/KaTeX_AMS-Regular-BQhdFMY1.woff2`.
```

The current `pyproject.toml` includes the complete generated `assets` directory in
`tool.hatch.build.targets.wheel.force-include`, while the normal package discovery
also supplies it after the frontend build. The build therefore cannot produce the
current source wheel. The previously found `dist/vaultpub-1.0.0-py3-none-any.whl`
predates this VaultPub source revision, so it cannot prove the current exact-Markdown
renderer required by LiveClassroom.

## Required follow-up outside this package task

VaultPub needs a narrow packaging repair and a newly built, versioned wheel published
to the configured package source or supplied as a controlled deployment artifact.
After that, rerun Task 50 by installing `django-liveclassroom[vaultpub]` against only
that artifact in a fresh environment and exercise the isolated slide renderer. Until
then, the base package acceptance remains valid and optional VaultPub distribution
acceptance remains partial.
