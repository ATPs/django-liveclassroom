# LiveClassroom - Product Aim

## Purpose

Build `django-liveclassroom` as a reusable Django application that helps teachers run interactive live classes. It is a teaching companion, not only a quiz system and not a complete learning management system.

The teacher should be able to prepare or improvise a lesson, control what appears on a classroom display and on student devices, send activities, collect named responses, communicate with the class, and review useful session data afterward.

The same Django models, services, APIs, migrations, WebSocket protocol, templates, and packaged frontend assets must serve both installation modes:

- installation inside an existing Django project, especially `xcWebServer`;
- the thin standalone project used for development, demonstration, and small deployments.

## Primary experience

LiveClassroom has three coordinated but distinct surfaces:

1. **Teacher console** - prepares content, controls the live session, previews both audience channels, admits participants, monitors responses, and changes reveal settings.
2. **Classroom display** - a clean presentation page for a projector or shared screen, opened by an authenticated teacher or co-host.
3. **Student experience** - a mobile-first page that shows only the content and controls currently published to participants.

The classroom display and student experience are independently controllable. For example, the display may remain on a VaultPub slide while students answer a poll, and the teacher may later reveal aggregate results on the display without exposing individual answers.

## Users, roles, and entry

- Reuse the host project's `AUTH_USER_MODEL`; never define a separate account system.
- Teachers and teaching staff authenticate through Django.
- A session has an owner and may have co-hosts, assistants, and read-only observers with explicit capabilities.
- Courses and prepared lesson flows are optional. A teacher may start an instant session, add content during class, and later save it for reuse.
- Student access is selected per session: guest entry, Django login, or both.
- Admission is selected per session: open entry, teacher-approved waiting room, or authenticated roster only.
- Guest entry uses a join code or QR code and requires a display name. Responses are always identifiable to the teacher and in exports.

## Teaching content and interaction

- Provide a visual web builder as the normal authoring experience. Django admin remains a diagnostic and maintenance interface.
- Support reusable flows and reusable activity definitions without requiring a course.
- Support Markdown/YAML and JSON import through the same canonical validation layer used by the visual builder.
- Fully support single choice, multiple choice, true/false, polls, short text, numeric response, ratings, rankings, word clouds, Markdown/media, and timers.
- Allow third-party Django projects to register additional activity types through stable backend and frontend plugin contracts.
- Let students revise responses until an activity is closed.
- Let teachers control, separately for students and the classroom display, whether to reveal prompts, aggregate results, correct answers, explanations, and response status.
- Let teachers choose which earlier activities students may revisit.
- Include a named session-wide chat feed that the teacher can enable or disable. Private messages and file attachments are not part of the first strong release.

## Live editing and trustworthy history

Teachers may edit a flow or the currently published activity during a session. A substantive edit creates a new activity revision rather than rewriting history:

- earlier submissions remain attached to the exact revision that was answered;
- students are notified that the activity changed and may resubmit against the new revision;
- current analytics use the latest revision by default while preserving older revisions for audit and comparison;
- every accepted command and response update is idempotent and auditable.

The database is authoritative. HTTP commands validate permissions and persist changes inside transactions. Realtime messages are notifications that tell clients to fetch newer authoritative state; they are not the source of truth.

## VaultPub integration

VaultPub is a first-class presentation content provider. The primary integration is the existing `vaultpub_portal` Django app in `xcWebServer`.

- A teacher may paste a VaultPub Slide View URL or browse accessible vaults and notes.
- Store a structured vault/note reference instead of depending on one mounted URL string.
- Embed a single Markdown note in Slide View inside the classroom display.
- Add a versioned, same-origin parent/iframe protocol so LiveClassroom can navigate the deck, observe the current slide, and restore presentation state after reconnecting.
- Allow optional activity cue points at slide positions without importing every slide as a database item.
- If a protected deck is sent to students, grant admitted participants temporary access only to that deck and its required assets. Do not expose sibling notes, search, graph, or management routes.
- Continue to support ordinary external URLs and iframes as less capable content items.

## AI authoring assistance

Include a freeform teacher-facing AI chat assistant in the authoring workspace.

- Use a host-provided backend so the reusable package does not own provider credentials or depend on one AI vendor.
- Support host-managed models and explicitly selected custom OpenAI-compatible providers.
- The teacher must explicitly attach each flow item or protected VaultPub note used as context.
- AI output remains a suggestion. It never modifies or publishes classroom content automatically.
- Persist teacher-visible prompts, assistant drafts, model identity, source references, author, and status, but do not persist copied protected source text, provider reasoning, credentials, or raw retry diagnostics.
- Custom credentials may exist only in the active request and worker memory. They must not enter browser storage, logs, files, caches, or the database.
- AI grading is not part of the first strong release.

## Realtime and resilience

- Support up to 100 connected students per session, plus teacher and display clients, with several sessions active at once.
- Use Django Channels for WebSocket connections.
- Use PostgreSQL `LISTEN/NOTIFY` as the cross-worker wake-up mechanism. Notification payloads contain only identifiers and state versions; clients then fetch authoritative state over HTTP.
- Use the in-memory notification path with SQLite for the standalone single-process development server.
- Recover from missed messages, process restarts, and unstable classroom Wi-Fi through state versions, reconnect synchronization, idempotent commands, and bounded HTTP polling.
- Cache the frontend application shell where practical, but do not make fully offline exam delivery a first-release requirement.

## Data and reporting

- Retain named participants, attendance, activity revisions, response revisions, timing, session events, and chat until a teacher deletes the session or the host applies a configured retention policy.
- Provide live response counts and distributions without revealing correct answers early.
- Provide post-session individual and aggregate views, revision comparison, participation timelines, and chat transcripts.
- Export session data in CSV and JSON formats.
- Do not build a longitudinal course gradebook in the first strong release.

## Reference projects

Use the neighboring projects as design references, not runtime dependencies:

- **AirQuiz** - learn from its low-friction room entry, QR workflow, realtime progress, reconnect behavior, classroom-network resilience, and export workflow. Do not copy its exam-first architecture or require per-student randomization.
- **RELATE** - learn from its course/flow/page concepts, reusable typed content, validation, attempts, and durable session history. Do not copy its full LMS scope or promise RELATE YAML compatibility.
- **VaultPub** - reuse its Markdown rendering and Reveal.js Slide View through an explicit integration contract rather than duplicating presentation rendering in LiveClassroom.

## Distribution and integration

- Package the application as an installable Python distribution with namespaced static assets that do not reset host-site CSS.
- Keep Django responsible for authentication, permissions, URLs, initial page rendering, and server-side validation.
- Use packaged React and TypeScript islands for the builder, teacher console, display, student interactions, analytics, and AI chat; do not require a separate frontend deployment.
- Support Django 5.2 and 6.0, SQLite for standalone development, and PostgreSQL for multi-worker production.
- Provide host settings for base templates, content providers, activity plugins, AI backends, retention, and realtime configuration.
- Ship complete English and Simplified Chinese interface strings.

## Explicitly deferred

Formal exams, anti-cheat controls, question randomization, a course gradebook, code execution, file responses, video meetings, whiteboards, private messaging, AI grading, SCORM, LTI, QTI, certificates, marketplaces, and direct RELATE runtime or format compatibility are outside the first strong release.

## Success criteria

The first strong release is complete when:

- a teacher can start an instant or prepared session and operate it without Django admin;
- the teacher can independently control a projector display and student devices;
- guest, authenticated, waiting-room, and roster entry policies work and reconnect safely;
- all built-in activity types support validation, live response collection, revision, reveal controls, analytics, and export;
- a protected VaultPub note can be selected, embedded, controlled, restored, and shared only within the selected classroom scope;
- English and Chinese teacher/student workflows work on desktop and mobile browsers;
- realtime delivery and recovery work across PostgreSQL-backed ASGI workers without an external message broker;
- 100-student load tests, focused security tests, and end-to-end browser workflows pass.

## Current status

The repository currently provides the reusable app and standalone project, legacy course/flow/question compatibility, instant and prepared sessions, guest/authenticated entry, admission controls, pause/end lifecycle controls, revisioned activities and submissions, independent audience channels, named chat, idempotent HTTP commands, reusable activity authoring APIs, built-in activity validation and manifests, Markdown/YAML import, staff-only session analytics, a restricted display route, authenticated Channels routing, archive/CSV export, and host-neutral plus `xcWebServer` VaultPub Slide View adapters. The UI is still primarily server-rendered and the visual builder, richer browser-oriented analytics, AI authoring, host-specific VaultPub participant grants, and production `xcWebServer` installation remain planned work.
