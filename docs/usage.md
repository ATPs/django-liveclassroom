# Using django-liveclassroom

`django-liveclassroom` is a reusable Django package for preparing teaching
content, running live classrooms, delivering assessments, and reviewing
results. It can run with the bundled standalone project or under a Django host
application.

## Choose an installation path

Use an attached release wheel for an existing Django project:

```bash
python -m pip install django_liveclassroom-1.0.0-py3-none-any.whl
```

The attached Python source distribution also contains the generated browser
bundle. GitHub's automatic source zip and tarball, and a Git checkout, do not
track that generated entry file. Build it before installing from source:

```bash
git clone https://github.com/ATPs/django-liveclassroom.git
cd django-liveclassroom
python -m venv .venv
. .venv/bin/activate
cd frontend
bun install --frozen-lockfile
bun run bundle
cd ..
python -m pip install -e '.[dev]'
```

The package requires Python 3.12 or newer, Django 5.2 or 6.0, Django Channels,
`qrcode`, and PyYAML. Install `.[postgres]` for PostgreSQL support and
`.[vaultpub]` only when a host will configure the optional VaultPub integration.

## Run the standalone reference project

The standalone project is for local development, demonstrations, and small
single-process deployments. It uses SQLite and the in-memory channel layer.

```bash
python standalone/manage.py migrate
python standalone/manage.py createsuperuser
python standalone/manage.py runserver
```

Open `http://127.0.0.1:8000/`, sign in, and use `/teacher/` to open the teacher
workspace. `/admin/` remains available for maintenance and diagnosis.

The included settings deliberately use `DEBUG=True`, a development key, and
`ALLOWED_HOSTS=["*"]` to make a local or classroom-LAN demonstration easy. They
are not production settings. Do not expose this `runserver` configuration to an
untrusted network. The standalone URL configuration does not serve `MEDIA_ROOT`
directly; LiveClassroom files are delivered through authorized package URLs.

Optionally seed the repeatable bilingual Bash example after migration:

```bash
python standalone/manage.py seed_liveclassroom_bash_demo --language all
```

This command creates only its own disabled demo owner and sample records. It
does not create credentials, run automatically, or access local files.

## Teach with the workspace

1. Sign in, open `/teacher/`, and optionally create a Course and Class. They
   organize teaching work but are not required for an instant classroom.
2. Create a reusable lesson in the lesson builder. Add typed activities, import
   Markdown/YAML or JSON, attach approved files, and create native slide decks.
   Saved content belongs to its author; sharing with a named colleague grants
   access only to that content, and copying creates an independent copy.
3. Start a classroom from a lesson or create an instant classroom. Choose guest,
   authenticated, or mixed entry; then select open, waiting-room, or roster
   admission as appropriate.
4. In the teacher console, start the classroom and publish content separately
   to the projector display and participant channels. Closing responses,
   revealing totals, revealing answers, and showing explanations are separate
   actions. Share the join page and displayed join code with students.
5. End the classroom when teaching is complete. Enable review only for material
   students may revisit. Use Teach again for a new snapshot, or save selected
   classroom improvements back to the reusable lesson.

The Student view starts as inspection only. A manager must explicitly act as an
admitted participant before writes occur; those delegated writes are recorded
in the audit history.

### Files and presentations

Teachers can use Markdown, PDF, PowerPoint, MP4, and WebM files up to the
configured 50 MiB default. Uploaded files are private and can be published to
the display or participant channel. Original-file downloads remain manager
only. Video playback is deliberately not synchronized between browsers.

`ALLOW_SERVER_FILE_PATHS` is disabled by default. Enabling it permits a
superuser to reference an absolute server path and serves the current bytes at
each request. Use it only on a trusted server with a deliberate filesystem
access policy:

```python
LIVECLASSROOM = {
    "ALLOW_SERVER_FILE_PATHS": True,
}
```

Never enable this option for untrusted administrators, shared hosting, or a
deployment where server paths may contain unrelated private material.

### Assessments, grading, and review

Build reusable assessments from question definitions and publish an immutable
run. Runs can use time windows, duration limits, attempt limits, controlled
navigation, question pools, and randomized question or option ordering. A
student's assigned questions and answer revisions remain tied to the run.

Students start or resume through the run link. Answers autosave, final
submission is explicit, and the server remains authoritative when a deadline
passes. Objective items are graded deterministically; essays and other
subjective work can enter the manual grading queue. Teachers may release
scores, answers, explanations, and feedback independently, then use Results
and grading for attempts, corrections, analytics, and CSV/JSON exports.

An ordinary browser is not a lockdown browser or remote-proctoring system.
Use host policy and external systems where stronger exam controls are required.

## Install into an existing Django project

Add the package and Channels, then mount the namespaced URLs under the host's
chosen prefix:

```python
# settings.py
INSTALLED_APPS += ["channels", "liveclassroom"]
ASGI_APPLICATION = "myproject.asgi.application"

# urls.py
urlpatterns += [path("classroom/", include("liveclassroom.urls"))]
```

The ASGI application must route WebSockets through the package patterns and
wrap the application lifespan:

```python
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

from liveclassroom.realtime.lifespan import with_liveclassroom_lifespan
from liveclassroom.routing import websocket_urlpatterns

django_asgi_app = get_asgi_application()
application = with_liveclassroom_lifespan(ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
}))
```

The default WebSocket path is `/ws/liveclassroom/sessions/{session_id}/`. Hosts
may change it with `LIVECLASSROOM["WEBSOCKET_PATH"]`, but reverse URLs and the
frontend bootstrap data must remain mount-prefix safe. Do not hard-code a
root-relative API or WebSocket URL in host code.

Apply migrations normally:

```bash
python manage.py migrate liveclassroom
python manage.py check
python manage.py makemigrations --check --dry-run
```

The package has migrations `0001` through `0021`. Never reset a populated
database or its migration history to upgrade LiveClassroom.

By default, every authenticated user can use teacher tools. A host with a
teacher role should configure a strict boolean authorization callback:

```python
LIVECLASSROOM = {
    "TEACHER_AUTHORIZER": lambda user: user.is_authenticated and user.groups.filter(
        name="liveclassroom-teacher"
    ).exists(),
}
```

Use `HOST_ADAPTER` when the host owns courses, rosters, authoring policy,
delivery policy, or assessment-result access. Configured adapters must
implement their relevant authorization hooks; absent result hooks never grant a
configured host access. See [extension contracts](extensions.md) for activity,
grading, export, content-provider, and frontend extension requirements.

## Optional integrations

VaultPub, AI backends, background queues, and provider credentials are host
owned. The generic VaultPub provider accepts Slide View URLs and uses the
conventional `/database/vaultpub` prefix. A host with a different route or a
protected-content policy should provide a subclass or adapter that reauthorizes
discovery and participant grants for every request.

```python
LIVECLASSROOM = {
    "CONTENT_PROVIDERS": {
        "vaultpub": "myproject.liveclassroom.VaultPubProvider",
    },
    "AI_BACKENDS": {"host": "myproject.liveclassroom_ai.HostBackend"},
    "AI_JOB_DISPATCHER": "myproject.liveclassroom_ai.dispatch",
}
```

AI jobs remain queued until a configured dispatcher or worker processes them.
Run a bounded worker manually when needed:

```bash
python manage.py process_liveclassroom_ai_jobs --once --limit 100
```

Protected source material is reauthorized at execution. Credentials, provider
reasoning, and protected text do not belong in ordinary logs or package data.

## Production and maintenance

For production, use host-owned settings and a real ASGI service. Set a unique
secret key; turn off debug; restrict allowed hosts; configure HTTPS, HSTS and
secure session/CSRF cookies where appropriate; provide private media storage;
and serve collected static files through the deployment's static layer. Do not
serve the package media directory as a public URL tree.

Run `bun run bundle` before `collectstatic` after frontend source changes. For
SQLite, use a single process. For multi-worker deployments, use PostgreSQL and
its `LISTEN/NOTIFY` relay; HTTP/database state remains authoritative when a
WebSocket reconnects or a worker restarts.

Operational commands include:

```bash
python manage.py expire_assessment_attempts --limit 500
python manage.py grade_pending_attempts --limit 500
python manage.py audit_liveclassroom_media
python manage.py purge_liveclassroom_sessions --no-input
```

Schedule expiry and pending-grade work according to the host's delivery policy.
`audit_liveclassroom_media` is report-only unless `--repair` is supplied.
Retention is disabled when `LIVECLASSROOM["RETENTION_DAYS"]` is `None`; review
backups and exports before permanently deleting archived sessions.

If a page has stale JavaScript, rebuild the bundle and collect static assets.
If a host cannot connect a WebSocket, check its proxy route, ASGI process, and
configured mount prefix. If an account cannot access teacher pages, verify the
teacher authorizer or host adapter. If an uploaded file is unavailable, verify
the classroom publication channel and current authorization rather than exposing
the backing media directory.
