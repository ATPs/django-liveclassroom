# LiveClassroom — Product Aim

## Purpose
Build `django-liveclassroom`: a reusable Django app, plus a thin standalone Django project, for running low-friction live teaching sessions. The same models, services, APIs, WebSocket protocol, templates, migrations, and frontend assets must serve both installation modes.

## Core principles
- Reuse the host `AUTH_USER_MODEL`; never define a separate user model.
- Database state is authoritative. HTTP commands persist changes inside transactions; WebSocket messages notify clients after commit.
- A launched activity stores an immutable definition snapshot, preserving historical results if source content later changes.
- Guests can join with a code and display name; account creation is not required.
- Importers parse and validate into one canonical representation before changing the database.
- Keep the first release focused on live teaching, not a complete LMS.

## MVP acceptance criteria
### Content
- Courses, memberships, flows, Markdown pages, and reusable questions.
- Fully working single-choice, multiple-choice, true/false, poll, and short-text activities.
- Markdown/YAML and JSON import into the canonical model.
- A question can be reused across flows without cloning it.

### Live classroom
- Teacher creates and starts a session, shares a join code and QR code, and controls a teacher-paced flow.
- Teacher can publish the current item, move previous/next, close and reveal questions, and see realtime progress/results.
- Students join anonymously, follow the teacher, submit, reconnect, and recover the exact current state.
- Protocol messages include protocol version, session id, state version, event type, and payload.
- Duplicate commands and duplicate submissions are safe and tested.

### Distribution
- Installable Python package and standalone development server.
- Django integration needs only app installation, URL inclusion, ASGI routing, and migrations.
- SQLite works locally; PostgreSQL + Redis/channel layer are supported in production.
- Static assets are namespaced and do not reset host-site CSS.

## Explicitly deferred
AI question generation and grading, exam randomization, gradebook, code execution, video chat, chat, whiteboard, SCORM/LTI/QTI, marketplaces, certificates, and full LMS features.

## Delivery sequence
1. Complete teacher-paced flow navigation, student following, QR join, and all MVP question interactions.
2. Complete JSON import and authoring UX; retain Markdown/YAML as the canonical content route.
3. Replace temporary server-rendered interaction islands with React + TypeScript/Vite assets.
4. Add standalone init/serve, Docker, PostgreSQL/Redis configuration, and deployment documentation.
5. Add reconnect, duplicate-command, Redis, and multi-client load tests.

## Current status
The reusable app, standalone project, core models, Channels routing, guest join, database-backed state recovery, single-choice live lifecycle, Markdown/YAML importer, management command, and automated tests are implemented. The remaining items above define the path to MVP completion.
