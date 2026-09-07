# LiveClassroom - Product Aim

## Purpose

Build `django-liveclassroom` as a reusable Django application that helps teachers run interactive live classes. It is a teaching companion, not only a quiz system and not a complete learning management system.

The teacher should be able to prepare or improvise a lesson, control what appears on a classroom display and on student devices, send activities, collect named responses, communicate with the class, and review useful session data afterward.

The same Django models, services, APIs, migrations, WebSocket protocol, templates, and packaged frontend assets must serve both installation modes:

- installation inside an existing Django project, especially `xcWebServer`;
- the thin standalone project used for development, demonstration, and small deployments.

## Lessons, classes, and classroom occurrences

The teacher workflow is **prepare and save a lesson → create a classroom → teach → review → save selected improvements or teach again**.

- A **lesson** is the editable reusable Flow in a teacher's library. It contains ordered activities and presentation materials. Teachers do not manage image tags, release labels, or deployment concepts.
- Creating a classroom automatically captures a complete immutable **lesson snapshot**, including unused steps, typed definitions and asset references. A classroom owns its independently editable plan and all runtime/student data.
- An optional **Class** represents one cohort or term, using the existing Course model. It organizes lessons, staff, an optional authenticated roster, entry/chat defaults and session history. Lessons can be used across classes without moving or changing their ownership.
- Class defaults are resolved when a classroom is created. Explicit classroom settings take precedence, subject to host policy. New classrooms start with empty audience channels and fresh admission, answers, chat, presentation progress and temporary grants.
- Editing a reusable lesson never changes existing classrooms automatically. Teachers may explicitly compare and import changes to steps that have not been launched. A running activity is edited separately through its revisioned classroom record.
- **Teach again** creates a new classroom from the prior classroom's complete final plan, including unused steps and live changes. It retains provenance and never resets or clears the historical session.
- **Save improvements to lesson** presents a simple selectable change list. Changes to the source after comparison require a fresh comparison; conflicting content needs explicit selection. Instant classrooms can be saved as personal lessons.
- A lesson owner may share with named existing Django accounts. Recipients can inspect, use or save independent copies, but cannot edit the original or see its author's classroom records or AI conversations. Revoking sharing prevents further source access; existing copies and classrooms remain independent.
- The library contains personal lessons, activities and materials plus lessons shared with the teacher. Sharing grants access only to materials actually referenced by the shared lesson, never to an entire private library.
- Uploaded files retain stable asset references. VaultPub, external URLs and authorized server-path materials remain live external references: history records their references, not a reproducible copy of external bytes. Access is checked at use; a lesson share does not grant unrelated external permissions.
- Ending a classroom closes responses and chat. Existing admitted participants may return to teacher-approved, read-only review content and their own answers. Reviewing does not create new attendance. Teachers may change review access, archive, export or delete retained sessions without rewriting teaching content.

The architectural analogy is **reusable lesson snapshot → independent classroom instance → retained history**. It describes content isolation, not a requirement to use Docker or to add a container-management interface.

## Primary experience

LiveClassroom has three coordinated but distinct surfaces:

1. **Teacher console** - prepares content, controls the live session, admits participants, monitors responses, changes reveal settings, and opens the staff-only Student view.
2. **Classroom display** - a clean presentation page for a projector or shared screen, opened by an authenticated teacher or co-host.
3. **Student experience** - a mobile-first page that shows only the content and controls currently published to participants.

The classroom display and student experience are independently controllable. For example, the display may remain on a VaultPub slide while students answer a poll, and the teacher may later reveal aggregate results on the display without exposing individual answers.

An authorized session manager may use the staff-only Student view to select an
existing participant and inspect exactly that participant's experience. It is
inspect-only until the manager explicitly begins acting as an admitted
participant. Delegated responses and chat affect the selected participant's
real session record and retain the staff actor for audit; opening or inspecting
the view must not create attendance, presence, connections, or participants.

## Users, roles, and entry

- Reuse the host project's `AUTH_USER_MODEL`; never define a separate account system.
- Teachers and teaching staff authenticate through Django.
- A host may supply a teacher-authorization callback. The reusable default permits authenticated users; a host can require a group or its own staff policy without preventing ineligible accounts from joining as students.
- A session has an owner and may have co-hosts, assistants, and read-only observers with explicit capabilities.
- Classes and prepared lessons are optional. A teacher may start an instant session, add content during class, and later save it for reuse.
- Student access is selected per session: guest entry, Django login, or both.
- Admission is selected per session: open entry, teacher-approved waiting room, or authenticated roster only.
- Guest entry uses a join code or QR code and requires a display name. Responses are always identifiable to the teacher and in exports.

## Teaching content and interaction

- Provide a visual web builder as the normal authoring experience. Django admin remains a diagnostic and maintenance interface.
- Support reusable flows and reusable activity definitions without requiring a course.
- Hosts may seed public, read-only demonstration lessons. A qualified teacher can inspect a demo or use it to create a private independent classroom, but cannot edit the common source or its sample records.
- Support Markdown/YAML and JSON import through the same canonical validation layer used by the visual builder.
- Fully support single choice, multiple choice, true/false, polls, short text, numeric response, ratings, rankings, word clouds, Markdown/media, timers, and a fixed browser-only Bash simulation.
- Allow third-party Django projects to register additional activity types through stable backend and frontend plugin contracts.
- Let students revise responses until an activity is closed.
- Let teachers control, separately for students and the classroom display, whether to reveal prompts, aggregate results, correct answers, explanations, and response status.
- Let teachers choose which earlier activities students may revisit.
- Include a named session-wide chat feed that the teacher can enable or disable. Private messages and file attachments are not part of the first strong release.

## Live editing and trustworthy history

Teachers may edit their reusable lesson or the classroom-local plan during a session. These are separate operations; reusable edits require explicit import into unused classroom steps. They may also edit the currently published activity. A substantive edit creates a new activity revision rather than rewriting history:

- earlier submissions remain attached to the exact revision that was answered;
- students are notified that the activity changed and may resubmit against the new revision;
- submissions carry the exact activity revision the student saw; stale screens cannot submit against a replacement prompt;
- the server accepts student responses only to permitted participant-published activities;
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
- The teacher must explicitly attach each activity definition, flow step, or
  protected VaultPub note used as context.
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
- Expose public HTTP endpoints only through the versioned `/api/v1/` contract;
  do not retain unversioned compatibility aliases.
- Use packaged React and TypeScript islands for the builder, teacher console, display, student interactions, analytics, and AI chat; do not require a separate frontend deployment.
- Support Django 5.2 and 6.0, SQLite for standalone development, and PostgreSQL for multi-worker production.
- Provide host settings for base templates, teacher authorization, content providers, activity plugins, AI backends, retention, and realtime configuration.
- Ship complete English and Simplified Chinese interface strings.

## Explicitly deferred

Formal exams, anti-cheat controls, question randomization, a course gradebook, server or local shell-code execution, file responses, video meetings, whiteboards, private messaging, AI grading, SCORM, LTI, QTI, certificates, marketplaces, and direct RELATE runtime or format compatibility are outside the first strong release. The Bash activity is a bounded, fixed browser simulation only.

## Success criteria

The first strong release is complete when:

- a teacher can start an instant or prepared session and operate it without Django admin;
- the teacher can independently control a projector display and student devices,
  and an authorized session manager can inspect or explicitly act as an
  admitted participant through the audited Student view;
- guest, authenticated, waiting-room, and roster entry policies work and reconnect safely;
- all built-in activity types support validation, live response collection, revision, reveal controls, analytics, and export;
- a protected VaultPub note can be selected, embedded, controlled, restored, and shared only within the selected classroom scope;
- English and Chinese teacher/student workflows work on desktop and mobile browsers;
- realtime delivery and recovery work across PostgreSQL-backed ASGI workers without an external message broker;
- 100-student load tests, focused security tests, and end-to-end browser workflows pass.

## Implementation and verification status

The package includes reusable authoring, automatic lesson snapshots, independent classroom plans, optional cohort workspaces, named-account lesson sharing, selective improvement review, prepared/instant/reused classrooms, revisioned responses, independent audience channels, teacher-controlled student review, private teaching files, queued AI authoring, exports, packaged bilingual React surfaces, task-focused help, host-configurable teacher authorization, and common read-only Bash-for-beginners demos.

Implemented capabilities must be accompanied by executable workflow evidence in the implementation record. A passing unit suite alone does not establish browser, 100-student or multi-worker acceptance. Host-specific VaultPub participant grants, production xcWebServer installation and provider-specific AI adapters remain separate integration work. External references remain live rather than historically frozen.
