# django-liveclassroom

`django-liveclassroom` is a reusable Django app for presenting live classroom
content and collecting real-time student responses.  The package and the
included standalone project share the same models, routes, templates, and ASGI
application.

## Prepare once, teach independently

The teacher workspace organizes **My lessons**, **Shared with me**, **Classes**, and **Recent sessions**. A lesson is reusable content; each classroom receives its own complete snapshot and teaching plan. Editing a lesson never silently changes a classroom already created from it.

Use **Teach again** to create a fresh classroom from retained teaching content. Answers, attendance, chat and presentation progress stay with the original classroom. Use **Save improvements to lesson** to review selected classroom changes before applying them to the original lesson. Shared lessons may be used or copied by a named colleague; editing the source remains with its author.

Classes are optional cohort workspaces with reusable entry/chat defaults and an optional account roster. Guest QR entry remains supported. External presentation URLs and server-file references stay live; uploaded materials have retained asset references. Student review after class is read-only and limited to the activities the teacher enables.

The public help page explains the workspace, builder, console, publication, sharing, and ending workflow in English and Simplified Chinese. Hosts can install the bilingual **Bash for Linux beginners** demo with `seed_liveclassroom_bash_demo`. It is a common read-only lesson: **Use this demo** creates a teacher-owned classroom snapshot. Its terminal is a fixed browser-only simulator with no server subprocess or local-file access.

## What is included now

- Course, flow, typed activity-definition, flow-step, live-session,
  participant, activity, submission, and audit-event models, including
  immutable activity/answer revisions, named chat messages, admission state,
  and independent display/participant channels.
- A teacher workspace for ordinary authoring and teaching, with Django admin
  reserved for diagnostics and maintenance; immutable history is read-only.
- HTTP endpoints for the classroom landing page, teacher console, and student
  join page.
- An authenticated ASGI WebSocket endpoint that broadcasts lightweight,
  versioned session events; PostgreSQL `LISTEN/NOTIFY` is the optional
  cross-worker wake-up path.
- A standalone Django project for local development and deployment experiments.
- A teacher-paced activity loop: create/start a classroom, join as a guest,
  submit and revise answers, close responses, view live totals, then reveal.
- Instant sessions, authenticated or guest entry, waiting-room admission,
  channel-specific reveal settings, hot activity revisions, and a host-neutral
  VaultPub Slide View URL adapter.
- Reusable activity authoring/validation APIs, Markdown/YAML import, activity
  manifests, pause/end lifecycle controls, and staff-only session analytics.
- A staff-only Student view that lets authorized session managers inspect the
  exact participant experience and explicitly act as an admitted participant;
  delegated writes are retained in the session audit history.
- Private teacher AI authoring threads with explicit source attachments,
  durable queued jobs, safe model discovery, and host-configured dispatch.
- Staff-only session archive export plus summary, response, participant, and
  chat CSV datasets.
- Ended-session archive/restore controls, explicit deletion protection, and a
  configurable retention cleanup command.
- Private classroom presentation files: Markdown, PDF, PowerPoint, MP4, and
  WebM can be added from the flow builder or teacher console, delivered only
  within the authorized classroom session, and displayed with teacher page
  control where applicable.
- A strict `liveclassroom.bash_simulator` activity plugin and a complete
  bilingual, 20-minute Bash-for-beginners demo lesson with ready, live, and
  ended sample classrooms.

The first milestone deliberately establishes the durable domain model,
integration boundaries, teacher controls, and a useful reporting surface.
The packaged teaching surfaces are React 19 islands (teacher console, classroom
display, and student session) over a scoped, token-driven stylesheet with
automatic dark mode, a presentation-focused full-viewport display, and complete
EN/zh-Hans coverage including the server-rendered pages. Browser workflows and
local PostgreSQL multi-worker acceptance have executable tests. Provider-specific
AI adapters and production host wiring remain separate integration work.

## Quick start

```bash
git clone https://github.com/ATPs/django-liveclassroom.git
cd django-liveclassroom
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
python standalone/manage.py migrate
python standalone/manage.py createsuperuser
python standalone/manage.py runserver
```

Open <http://127.0.0.1:8000/>. The Django admin is available at
`/admin/`.

To install the optional common examples after migrating, run:

```bash
python standalone/manage.py seed_liveclassroom_bash_demo
```

## Run the first live quiz

1. Sign in and visit `/teacher/`. Choose **Create lesson**, add a single-choice
   activity in the builder, and save the lesson. A Class is optional.
2. Return to the workspace, choose **Start from lesson**, create a classroom,
   and click **Start classroom**.
3. Share `/join/` and the displayed join code. Guests enter only a display
   name, then see the teacher's current activity.
4. Launch the activity to student devices from the classroom plan. The display
   has separate controls. Close responses and reveal the answer when ready.
5. End the classroom and enable review for selected activities. Use **Teach
   again** for a fresh classroom or save selected improvements to the lesson.

## Import Markdown/YAML content

Use `:::quiz` directives inside Markdown, then import into an existing course:

```bash
python standalone/manage.py import_liveclassroom_markdown course-slug examples/courses/rnaseq-intro.md
```

The importer validates everything before writing and normalizes answer text to
stable option IDs. See the bundled example for the supported format.

## Add to an existing Django project

```python
# settings.py
INSTALLED_APPS += ["channels", "liveclassroom"]

# urls.py
(path("classroom/", include("liveclassroom.urls")),)
```

Mount `liveclassroom.routing.websocket_urlpatterns` in the host project's ASGI
application.  The standalone `asgi.py` is the reference integration.

By default every authenticated account can use teacher tools. A host that has
its own teacher group can provide a strict boolean callback; accounts that do
not pass it still retain ordinary student access:

```python
LIVECLASSROOM = {
    "TEACHER_AUTHORIZER": lambda user: user.is_authenticated and user.groups.filter(
        name="liveclassroom-teacher"
    ).exists(),
}
```

To rebuild the packaged teaching client after editing TypeScript, run
`bun run bundle` from `frontend/`. This writes the browser bundle, its lazy
viewer chunks, and the PDF worker to `src/liveclassroom/static/liveclassroom/`;
`bun run check` performs the optional TypeScript typecheck when frontend
dependencies are installed.

## Classroom presentation files

Teachers can upload `.md`, `.pdf`, `.pptx`, `.mp4`, and `.webm` files up to
50 MiB from a flow or an active teacher console. Files remain private: an
admitted participant receives a session-scoped content URL only while the file
is published to their channel. Original-file downloads are limited to session
managers. PDF and PowerPoint files use browser-side viewers; video uses native
browser controls and is deliberately not playback-synchronized.

By default, an uploaded file is stored in package-managed private media. A host
can additionally permit a superuser to reference an existing absolute server
path in place. That option exposes the current bytes at every request, so it is
intended only for a trusted server where that live-reference behavior is wanted:

```python
LIVECLASSROOM = {
    "ASSET_MAX_BYTES": 50 * 1024 * 1024,
    "ALLOW_SERVER_FILE_PATHS": True,
}
```

All public HTTP endpoints are versioned under `/api/v1/`; unversioned API
aliases are not supported.

## Staff Student view

Authorized session managers can open the Student view from a teacher session,
choose any existing participant, and inspect the same participant-facing state
and redaction rules that the selected student receives. The page starts in
inspect-only mode. An explicit action is required before acting as an admitted
participant; actions then affect that participant's real classroom record and
remain auditable with the staff actor. The Student view never creates a
participant or changes attendance or presence simply by being opened.

## Design principles

- Reuse the host project's `AUTH_USER_MODEL`; no custom user model is supplied.
- Treat the database as the source of truth. HTTP commands persist state;
  WebSockets notify connected clients.
- Store an immutable content snapshot on every launched `LiveActivity` so
  historical classroom results remain reproducible.
- Do not add Redis or another external message broker. SQLite uses the local
  in-memory channel layer; PostgreSQL deployments can enable the notification
  relay and clients refetch authoritative state over HTTP.

## Development Database

The current development migration history is a single fresh `0001_initial`.
Recreate disposable development databases when moving from the earlier schema;
this reset is not an upgrade migration for an existing populated installation.

## Optional VaultPub provider

Register the reusable adapter in a host project that mounts the VaultPub portal:

```python
LIVECLASSROOM = {
    "CONTENT_PROVIDERS": {
        "vaultpub": "liveclassroom.integrations.vaultpub.VaultPubProvider",
    },
}
```

The adapter accepts registered-vault and temporary-share `__slides__` URLs,
including percent-encoded Unicode paths, and adds the explicit `embed=1` mode.
Protected participant grants remain host-owned callbacks so portal permissions
are checked on every use.

For the `xcWebServer` installation with `vaultpub_portal`, configure
`vaultpub_portal.liveclassroom_provider.XcWebServerVaultPubProvider` instead of
the generic adapter. It rechecks the portal's registered-vault and share rules
and returns teacher-safe note descriptors; student grants remain disabled until
the host adds scoped grant storage and routes.

## Optional AI authoring backend

Register host-owned model discovery/completion backends and, in production, a
dispatcher that hands queued jobs to the host worker:

```python
LIVECLASSROOM = {
    "AI_BACKENDS": {"host": "myproject.liveclassroom_ai.HostBackend"},
    "AI_JOB_DISPATCHER": "myproject.liveclassroom_ai.dispatch",
}
```

Authoring threads are private to their teacher. Attachments store only typed
references and fingerprints; protected sources are re-authorized at execution.
Without a dispatcher, jobs remain queued for an explicit worker call to
`liveclassroom.services.authoring.run_authoring_job`.

## License

MIT. See [LICENSE](LICENSE). Bundled browser viewer notices are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
