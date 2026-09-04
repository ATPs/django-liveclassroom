# django-liveclassroom

`django-liveclassroom` is a reusable Django app for presenting live classroom
content and collecting real-time student responses.  The package and the
included standalone project share the same models, routes, templates, and ASGI
application.

## What is included now

- Course, flow, typed activity-definition, flow-step, live-session,
  participant, activity, submission, and audit-event models, including
  immutable activity/answer revisions, named chat messages, admission state,
  and independent display/participant channels.
- Django admin for authoring and inspecting the core data.
- HTTP endpoints for the classroom landing page, teacher console, and student
  join page.
- An authenticated ASGI WebSocket endpoint that broadcasts lightweight,
  versioned session events; PostgreSQL `LISTEN/NOTIFY` is the optional
  cross-worker wake-up path.
- A standalone Django project for local development and deployment experiments.
- A working teacher-paced single-choice quiz loop: create/start a session, join
  as a guest, submit once, close answers, view live totals, then reveal.
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

The first milestone deliberately establishes the durable domain model,
integration boundaries, teacher controls, and a useful reporting surface.
The packaged TypeScript teaching surface now mounts on the teacher, display,
and student pages; a visual builder, browser acceptance, provider-specific AI
adapters, and production host wiring remain planned work.

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

## Run the first live quiz

1. In `/admin/`, create a Course, Flow, and a ready single-choice
   ActivityDefinition. Its `definition` uses `{"prompt": "…", "options":
   [{"id": "A", "text": "…"}], "answer": ["A"]}`. Add the definition to
   the flow as a FlowStep.
2. Visit `/teacher/`, create a session, and click **Start classroom**.
3. Share `/join/` and the displayed join code. Guests enter only a display
   name, then see the teacher's current activity.
4. Publish the FlowStep, close responses, and reveal the answer from
   the teacher console.

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

To rebuild the packaged teaching client after editing TypeScript, run
`bun run bundle` from `frontend/`. This writes the dependency-free browser
bundle to `src/liveclassroom/static/liveclassroom/app.js`; `bun run check`
performs the optional TypeScript typecheck when frontend dependencies are
installed.

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

MIT. See [LICENSE](LICENSE).
