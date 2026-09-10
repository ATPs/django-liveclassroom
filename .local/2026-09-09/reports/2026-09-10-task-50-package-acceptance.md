# Task 50 — package acceptance

## Status: PARTIAL

The committed package base profile passed artifact, isolated-wheel, mounted-host, and
static-resource acceptance. The optional VaultPub profile remains **PARTIAL** because
the only resolver-visible VaultPub installation is an editable checkout, not an
independently installed artifact; it must not substitute for optional-distribution
proof.

## Baseline and environment

- Source commit: `289d614` (`Record Task 48 final verification`)
- Build source: `git archive HEAD` in a disposable `/tmp/liveclassroom-task50-final.*`
  directory, so the user-owned dirty `pyproject.toml` and unrelated work were excluded.
- Runtime: zsh, conda `django`, Python 3.12, Django 5.2, Hatchling 1.27.0.
- Build tool: `python -m hatchling build -d dist`; the shared environment has no
  `build` module, so no shared-environment installation was made.

## Artifacts

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `django_liveclassroom-0.1.0-py3-none-any.whl` | 1,057,481 | `5b8997a28f4614347f4046ec9ff3aff76aad1b71342733321b6b195000341b44` |
| `django_liveclassroom-0.1.0.tar.gz` | 1,209,047 | `8c6e75c4120c9bc614a27d6cb8d18f6e29876b71119af6a7086729193ee2b5dc` |

Both archives contain all LiveClassroom migrations, templates, bundled `app.js`,
scoped CSS, the PDF worker, and the emitted application/core/PDF/viewer chunks.

## Passed base-profile acceptance

1. Built wheel and sdist from the recorded archive.
2. Created a disposable `venv --system-site-packages`, installed the newly built wheel
   with `pip install --no-deps`, then used `env -u PYTHONPATH -u DJANGO_SETTINGS_MODULE`.
   `liveclassroom.__file__` resolved to the venv's `site-packages`, rather than this
   checkout or the editable shared package.
3. A tiny foreign Django host with disposable SQLite database and static root passed
   `check`, `migrate --noinput`, and `collectstatic --noinput`.
4. The same wheel reversed Help routes correctly at both `/classroom/help/` and
   `/teaching/classroom/help/`.
5. Task-owned local Django servers returned HTTP 200 for the mounted Help page,
   `app.js`, `liveclassroom.css`, `pdf.worker.min.mjs`, and all five bundled chunks.
   The main bundle's emitted application-chunk import was fetched successfully.

No host CSS was modified and no actual xcWebServer process, database, static tree, or
package installation was changed.

## Optional VaultPub profile

`pip install --dry-run '<wheel>[vaultpub]'` recognized `vaultpub==1.0.0`, but its
metadata has `direct_url.json` with `editable: true` and
`file:///data/p/xiaolong/vaultpub`. This is useful resolver information, but it is not
an isolated optional-package acceptance. No sibling VaultPub installation was changed.
Full VaultPub host rendering remains host-adapter and host-configuration acceptance.

## Remaining boundaries

This task does not establish real browser styling in a production static server,
optional VaultPub wheel installation, xcWebServer deployment, PostgreSQL concurrency,
or multi-worker/load behavior. Those remain separate acceptance tasks.
