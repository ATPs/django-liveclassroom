# django-liveclassroom

`django-liveclassroom` is a reusable Django app for presenting live classroom
content and collecting real-time student responses.  The package and the
included standalone project share the same models, routes, templates, and ASGI
application.

## What is included now

- Course, flow, question, live-session, participant, activity, submission, and
  audit-event models.
- Django admin for authoring and inspecting the core data.
- HTTP endpoints for the classroom landing page, teacher console, and student
  join page.
- An ASGI WebSocket endpoint that validates a session id and broadcasts
  lightweight session events.
- A standalone Django project for local development and deployment experiments.
- A working teacher-paced single-choice quiz loop: create/start a session, join
  as a guest, submit once, close answers, view live totals, then reveal.

The first milestone deliberately establishes the durable domain model and
integration boundaries.  Authoring UI, Markdown/YAML import, React islands,
and live teacher controls come next.

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

1. In `/admin/`, create a Course, Flow, single-choice Question, and Question
   FlowItem. The question `data` uses `{"options": [{"id": "A", "text":
   "…"}]}`; its `answer` is a JSON list such as `["A"]`.
2. Visit `/teacher/`, create a session, and click **Start classroom**.
3. Share `/join/` and the displayed join code. Guests enter only a display
   name, then see the teacher's current activity.
4. Publish the Question FlowItem, close responses, and reveal the answer from
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

## Design principles

- Reuse the host project's `AUTH_USER_MODEL`; no custom user model is supplied.
- Treat the database as the source of truth. HTTP commands persist state;
  WebSockets notify connected clients.
- Store an immutable content snapshot on every launched `LiveActivity` so
  historical classroom results remain reproducible.
- Support signed guest identity later without making a student account mandatory.

## License

MIT. See [LICENSE](LICENSE).
