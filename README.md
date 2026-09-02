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
