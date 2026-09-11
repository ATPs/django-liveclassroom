# django-liveclassroom — Product Aim

## Purpose

Build `django-liveclassroom` as a reusable Django **teaching package** for creating, presenting, delivering, assessing, and reviewing teaching activities.

The package should support the complete lightweight teaching loop:

**prepare → present → interact → assess → grade → review → reuse**

It is broader than a live quiz system and broader than a presentation tool. It should support four primary teaching modes:

1. **Presentation** — show and control slides or other teaching materials.
2. **Live teaching** — combine presentation, questions, polls, discussion, demonstrations, and teacher-paced activities.
3. **Practice and assignments** — let students complete reusable learning activities at their own pace.
4. **Examination** — deliver timed, scored, auditable quizzes and formal browser-based exams.

The goal is not to replace a full LMS such as Moodle or Canvas. Instead, `django-liveclassroom` should provide a compact, modern teaching layer that can be embedded into an existing Django site or run independently.

The same core models, services, permissions, APIs, migrations, realtime protocol, templates, and packaged frontend assets must support both:

* installation inside an existing Django project, especially `xcWebServer`;
* the thin standalone project for development, demonstration, teaching, and small deployments.

---

## Product principles

### Teaching first

Every major feature should answer a real teaching need.

The package should make common workflows easy:

* prepare a lecture;
* present slides;
* ask questions during a lecture;
* collect and display responses;
* run practice exercises;
* create a quiz or exam;
* grade student work;
* review individual and class performance;
* reuse and improve teaching material.

Technical concepts such as snapshots, revisions, providers, queues, and realtime state are implementation mechanisms. They should not dominate the teacher-facing experience.

### One content system, multiple delivery modes

A question, slide deck, activity, or lesson should not need to be recreated for every use.

The same reusable content may be used:

* inside a live lecture;
* as independent student practice;
* inside homework;
* inside a quiz;
* inside a formal exam;
* in another lesson or course.

### Reusable package, not a closed application

`django-liveclassroom` must remain installable as a normal Django application.

Host projects should be able to provide or replace:

* authentication and authorization;
* student rosters;
* course models;
* slide/content providers;
* activity types;
* grading strategies;
* AI providers;
* storage;
* background-job infrastructure;
* realtime configuration.

The standalone project is a complete reference application, not a separate implementation.

---

## Core teaching concepts

The product should expose clear teaching concepts even when the existing implementation uses different internal model names.

### Course

An optional organizational container for a subject or teaching program.

Examples:

* Introduction to Bioinformatics
* RNA-seq Data Analysis
* Medical Statistics 2026

A host application may map this concept to its own course model.

### Class or cohort

An optional group of students participating in a course or teaching period.

A class may define:

* students and teaching staff;
* default admission rules;
* assigned lessons;
* assessments;
* teaching history;
* grade summaries.

The package must still work without a course or class.

### Lesson

A reusable teaching unit.

A lesson may contain an ordered mixture of:

* slides;
* Markdown or rich teaching content;
* images and media;
* questions;
* polls;
* activities;
* demonstrations;
* timers;
* discussion prompts;
* external resources.

A lesson is the main reusable unit for teacher-paced teaching.

### Slide deck

A reusable presentation that can be displayed independently or embedded inside a lesson.

Slides are a **first-class teaching object**, not merely an iframe attached to a classroom.

### Question

A reusable assessment item with structured metadata.

A question may contain:

* prompt;
* question type;
* options or answer definition;
* points;
* explanation;
* feedback;
* tags;
* difficulty;
* learning objectives;
* media;
* grading configuration.

### Question bank

A searchable reusable collection of questions.

Teachers should be able to:

* organize questions;
* filter by tags or topic;
* reuse questions across assessments;
* copy and modify questions;
* import and export questions;
* generate assessment sections from question pools.

### Assessment

A reusable definition for a quiz, practice exercise, homework, or exam.

An assessment defines content and rules but is separate from a student's actual attempt.

### Classroom session

A live teaching occurrence.

It combines reusable content with fresh runtime state such as:

* participants;
* current slide;
* current activity;
* answers;
* chat;
* reveal state;
* timing;
* attendance;
* teacher commands.

### Assessment run and attempt

Publishing an assessment creates a concrete assessment run with an immutable content snapshot.

Each student's work is stored as an independent attempt with its own:

* assigned questions;
* answer revisions;
* timing;
* submission state;
* score;
* grading state;
* audit history.

Existing Django model names do not need to match these conceptual names exactly. The concepts define product behavior rather than forcing unnecessary migrations.

---

# Presentation and slides

## Slides are a core capability

A teacher must be able to use `django-liveclassroom` simply as a teaching presentation system, even when no quiz is involved.

The teacher should be able to:

* create or select a slide deck;
* open a clean projector/display view;
* navigate slides from the teacher console;
* enter fullscreen presentation mode;
* restore the current slide after reconnecting;
* combine slides with activities;
* optionally synchronize student devices to the current slide;
* optionally allow students to revisit published slides.

Presentation state and student activity state must be independently controllable.

For example:

* the projector may remain on a figure while students answer a question;
* students may receive a question that is not visible on the projector;
* aggregate answers may later appear on the projector;
* a teacher may continue navigating slides without changing the current student activity.

## Native presentation content

The standalone package should be capable of presenting teaching content without requiring an external service.

The native presentation system should support at least:

* Markdown-based slides;
* headings and formatted text;
* code blocks;
* images;
* tables;
* mathematical content where supported by the renderer;
* embedded media;
* speaker notes;
* simple presentation themes;
* slide separators;
* fullscreen presentation.

A packaged browser presentation library such as Reveal.js may be used, but the product contract must not depend permanently on one rendering implementation.

## External presentation providers

External teaching systems may provide richer presentation content through a stable provider interface.

### VaultPub

VaultPub is an important first-party integration.

A teacher should be able to:

* browse accessible VaultPub notes;
* select a note that supports Slide View;
* present it inside LiveClassroom;
* control slide navigation;
* observe the current slide;
* restore position after reconnecting;
* associate questions or activity cue points with slide positions.

Protected content shared with students must receive only narrowly scoped temporary access.

### Other sources

The package should also support less integrated content such as:

* ordinary URLs;
* embedded web pages;
* PDF teaching material where practical;
* image-based decks;
* host-defined content providers.

PPTX conversion or high-fidelity native PowerPoint rendering is not required from the Django core and may be supplied through an optional provider or conversion plugin.

---

# Live teaching

Live teaching combines presentation and student interaction.

The teacher console should allow a teacher to:

* start an instant classroom;
* start from a prepared lesson;
* present slides;
* publish activities;
* control student access;
* monitor participation;
* close or reopen responses;
* reveal results;
* reveal correct answers;
* show explanations;
* move between presentation and interaction;
* add or modify content during class;
* pause or end the session.

Students join using:

* Django authentication;
* guest access with display name;
* roster-based access;
* or host-defined authentication policy.

Admission policies may include:

* open entry;
* join code;
* QR code;
* waiting room;
* authenticated roster only.

Live sessions should work well on classroom Wi-Fi and recover safely from temporary disconnections.

---

# Activities and questions

The activity system should support both **interactive teaching activities** and **gradable assessment questions**.

Built-in activity/question types should include:

* single choice;
* multiple choice;
* true/false;
* short text;
* long text or essay;
* numeric response;
* polls;
* ratings;
* rankings or ordering;
* word clouds;
* Markdown/media content;
* timers;
* simple browser-only interactive demonstrations.

Additional types should be registerable by third-party Django applications through stable backend and frontend plugin contracts.

The existing browser-only Bash simulation may remain as a safe teaching activity. The package must not execute arbitrary student shell commands on the server.

---

# Practice and assignments

Not every activity requires a live classroom.

Teachers should be able to publish reusable material for independent student work.

A practice or assignment may support:

* immediate or delayed feedback;
* unlimited or limited attempts;
* optional scoring;
* due dates;
* answer explanations;
* review after completion;
* teacher-visible progress;
* resuming incomplete work.

Practice mode should emphasize learning rather than examination security.

Teachers should be able to convert suitable practice material into an assessment without recreating the questions.

---

# Quizzes and examinations

Formal assessment is a core product capability.

`django-liveclassroom` should support browser-based quizzes and exams suitable for normal university and classroom use.

## Assessment configuration

An assessment may define:

* instructions;
* sections;
* questions;
* point values;
* passing thresholds;
* opening time;
* closing time;
* duration;
* number of attempts;
* question navigation policy;
* review policy;
* result-release policy;
* answer-feedback policy.

## Question selection and randomization

Assessments should support optional:

* question ordering;
* option ordering;
* question pools;
* random sampling;
* per-student question selection;
* fixed questions mixed with random questions.

The exact question set assigned to a student must be retained so that the attempt remains reproducible and auditable.

## Exam delivery

Exam mode should support:

* authenticated students;
* optional roster restriction;
* start and submission timestamps;
* countdown timers;
* autosaving;
* reconnect recovery;
* explicit final submission;
* automatic submission when configured time expires;
* server-authoritative exam timing;
* prevention of submissions after the permitted deadline;
* immutable assessment snapshots.

Closing the browser must not silently destroy an attempt.

## Examination security boundaries

The package should provide reliable assessment controls but must not pretend that an ordinary browser can guarantee cheating prevention.

Reasonable exam controls may include:

* restricted navigation inside the assessment;
* randomized questions;
* randomized answer choices;
* controlled result visibility;
* access windows;
* attempt limits;
* server-authoritative timers;
* audit events;
* optional fullscreen warnings;
* host-defined exam policies.

Dedicated lockdown browsers, remote proctoring, webcam monitoring, operating-system restrictions, and guaranteed anti-cheating enforcement are outside the core package.

They may be implemented through external systems or future integrations.

---

# Grading

Objective question types should support deterministic automatic grading.

The grading system should support:

* full credit;
* zero credit;
* partial credit where appropriate;
* configurable points;
* manual overrides;
* grading comments;
* regrading after a grading-rule correction;
* auditable score changes.

Subjective questions such as essays should support manual grading.

The data model should allow future grading plugins, including rubric-based and AI-assisted grading, without making AI grading a dependency of the core product.

Students should only see scores, correct answers, explanations, or grading comments when the assessment's release policy permits them.

---

# Results and lightweight gradebook

The package should provide enough longitudinal information to support real teaching.

For each student, teachers should be able to review:

* attendance;
* activity participation;
* practice completion;
* assessment attempts;
* scores;
* question-level performance;
* submission timing.

For a class or course, teachers should be able to review:

* assessment score distributions;
* completion rates;
* question difficulty;
* answer distributions;
* commonly missed questions;
* participation trends.

A lightweight grade summary across assessments is part of the teaching package.

The goal is not to reproduce the complete gradebook, transcript, prerequisite, registration, and institutional workflows of a full LMS.

Data should be exportable in useful machine-readable formats such as CSV and JSON.

---

# Content authoring

Teachers should normally author content through a visual web interface.

Django admin remains useful for diagnosis and maintenance but must not be required for normal teaching.

The authoring workspace should provide access to:

* courses and classes;
* lessons;
* slide decks;
* questions;
* question banks;
* assessments;
* reusable activities;
* uploaded teaching materials.

Teachers should be able to duplicate and modify reusable content without changing the source.

---

# Import and export

Structured text formats are important because teaching material should be easy to create, version, generate, and reuse.

Support Markdown/YAML and JSON import through the same canonical validation layer used by the web builder.

The format should be able to describe, where practical:

* slides;
* lessons;
* questions;
* assessment settings;
* reusable activities.

Import must validate the complete input before committing changes.

Export should make reusable teaching content and assessment results portable.

Interoperability formats such as QTI, SCORM, and LTI may later be provided through optional adapters; they are not required as the internal data model.

---

# Classroom history and snapshots

Reusable definitions and actual teaching occurrences must remain separate.

The general architecture is:

**reusable content → immutable delivery snapshot → student/runtime records → retained history**

Editing a reusable lesson, deck, question, or assessment must not silently rewrite historical sessions or completed attempts.

When a classroom or assessment begins, the system must retain enough information to determine exactly what students received.

Live editing may be allowed where appropriate, but substantive edits must create revisions rather than overwrite previously answered content.

Earlier responses remain attached to the exact revision that was shown to the student.

---

# Teacher, display, and student experiences

The package has several coordinated but distinct interfaces.

## Teacher workspace

Used to:

* create content;
* manage question banks;
* prepare lessons;
* create assessments;
* configure classrooms;
* launch teaching;
* control presentations;
* monitor students;
* grade work;
* inspect analytics.

## Teacher console

Optimized for operating an active classroom.

It should provide fast controls for:

* slide navigation;
* activity publication;
* response status;
* timers;
* reveal state;
* admission;
* chat;
* participant status.

## Classroom display

A clean presentation surface intended for:

* projector;
* lecture-room display;
* screen sharing.

Teacher controls should not appear on the public display.

## Student experience

A mobile-first interface for:

* joining classes;
* viewing published teaching content;
* answering live activities;
* accessing slides when permitted;
* completing practice;
* taking exams;
* reviewing results.

## Grading and review workspace

Teachers should be able to inspect:

* individual submissions;
* question-level results;
* manual grading queues;
* class analytics;
* teaching-session history.

---

# Users and permissions

Reuse the host project's `AUTH_USER_MODEL`.

Do not define an independent account system.

Common roles include:

* teacher;
* co-teacher;
* teaching assistant;
* read-only observer;
* authenticated student;
* guest participant.

Hosts must be able to supply authorization callbacks or adapters.

Permissions should distinguish capabilities such as:

* author content;
* start classrooms;
* manage students;
* control presentation;
* view named responses;
* grade assessments;
* manage shared content.

Opening an inspection interface must never silently create attendance or a participant record.

Delegated actions performed by staff on behalf of a student must retain the staff actor in the audit history.

---

# Content sharing and reuse

Teachers should be able to maintain a personal teaching library.

Reusable objects may be:

* private;
* shared with specific teachers;
* shared read-only;
* copied into another teacher's library;
* supplied as host-managed demonstrations.

Sharing a lesson or assessment must grant access only to content actually required by that object.

Sharing must not expose unrelated private files, lessons, classrooms, assessment attempts, AI conversations, or student data.

Copies become independent unless an explicit future synchronization feature is introduced.

---

# AI authoring assistance

AI should assist teachers in preparing teaching material without becoming the authority that publishes or grades content automatically.

The authoring workspace may provide a teacher-facing AI assistant capable of helping with tasks such as:

* generating questions;
* improving questions;
* generating distractors;
* producing explanations;
* converting notes into slides;
* proposing lesson structure;
* creating practice exercises;
* summarizing teaching materials;
* suggesting assessment questions.

The reusable package must use host-provided AI backends rather than owning provider credentials.

Teachers explicitly choose protected material supplied as AI context.

AI-generated content remains a draft until explicitly accepted by the teacher.

Credentials, provider reasoning, and protected source contents must not be written into ordinary logs or stored unnecessarily.

AI-assisted grading may be added through a future grading plugin, but human review and auditable grading policy must remain possible.

---

# Realtime architecture and resilience

Live teaching should support approximately 100 connected students per classroom as a normal target, with multiple classrooms operating concurrently.

Use Django Channels for WebSocket communication.

The database remains authoritative.

HTTP commands:

* validate permissions;
* validate current state;
* persist changes transactionally.

Realtime messages notify clients that newer state exists; WebSockets are not the authoritative data store.

PostgreSQL deployments may use `LISTEN/NOTIFY` as a lightweight cross-worker wake-up mechanism.

SQLite should remain suitable for standalone development and simple single-process deployments.

Clients must recover from:

* missed WebSocket messages;
* reconnects;
* browser refreshes;
* worker restarts;
* unstable classroom Wi-Fi.

Exam submissions and timers must remain correct even when realtime delivery is temporarily unavailable.

---

# Auditability and data integrity

Teaching data must be trustworthy.

Important mutations should be:

* permission checked;
* transactionally persisted;
* revision aware;
* idempotent where needed;
* auditable.

The system should retain, according to host retention policy:

* participant identity;
* attendance;
* lesson and assessment snapshots;
* assigned exam questions;
* answer revisions;
* activity revisions;
* timing;
* grading changes;
* session events;
* chat history where enabled.

A completed historical session or assessment must not be rewritten merely because reusable source content changed later.

---

# Extensibility

The reusable package should provide stable extension points for:

* activity types;
* question types;
* content providers;
* slide providers;
* authentication and authorization;
* course and roster integration;
* grading strategies;
* AI providers;
* background jobs;
* exports;
* host-specific policies.

Extensions should not require forking the package.

---

# Distribution and Django integration

Ship `django-liveclassroom` as a normal installable Python distribution.

The package should include its frontend assets and should not require a separately deployed frontend service.

Django remains responsible for:

* authentication;
* permissions;
* URL routing;
* server-side validation;
* initial application bootstrapping;
* persistence.

Interactive interfaces may use packaged React and TypeScript components.

Static assets must be namespaced and must not reset or interfere with the host application's styles.

Public APIs should use a versioned contract such as `/api/v1/`.

The package should support SQLite for development and small deployments and PostgreSQL for production multi-worker deployments.

Exact supported Django and dependency versions belong in `pyproject.toml` and the README rather than being permanent product aims.

The user interface should support English and Simplified Chinese.

---

# Reference projects

Neighboring and external projects should be treated as design references rather than mandatory runtime dependencies.

## AirQuiz

Learn from:

* low-friction room entry;
* QR joining;
* realtime progress;
* exam delivery;
* classroom-network resilience;
* reconnect behavior;
* result export.

Unlike the earlier live-classroom-only direction, useful exam concepts such as question pools and per-student randomization are valid capabilities for `django-liveclassroom`.

## RELATE

Learn from:

* course and flow concepts;
* reusable typed content;
* validation;
* question definitions;
* attempts;
* grading;
* durable history.

Do not copy the full LMS scope or require RELATE runtime compatibility.

## VaultPub

Use VaultPub as a strong presentation/content integration.

LiveClassroom should integrate with its Markdown and Slide View capabilities without making VaultPub mandatory for standalone teaching.

---

# Non-goals

The core package is not intended to become:

* a university student-information system;
* a full Moodle/Canvas replacement;
* a video-conferencing platform;
* a remote-proctoring platform;
* a lockdown browser;
* a collaborative whiteboard platform;
* a certificate marketplace;
* an arbitrary code-execution service.

Features such as institutional enrollment, transcripts, complex prerequisites, video meetings, webcam proctoring, SCORM, LTI, QTI, and specialized code execution should be implemented through integrations when needed rather than expanding the core indiscriminately.

---

# Success criteria

The product direction is successful when a teacher can install `django-liveclassroom` and use the same package to perform the major workflows of ordinary teaching.

A teacher can:

* create reusable teaching content without Django admin;
* prepare a slide deck;
* present slides in a classroom;
* combine slides with interactive questions;
* run teacher-paced live teaching;
* publish independent student practice;
* build and reuse a question bank;
* create a scored quiz;
* create a timed formal exam;
* optionally randomize questions and answer choices;
* reliably collect and autosave student answers;
* automatically grade objective questions;
* manually grade subjective questions;
* control when students see answers, explanations, and scores;
* review individual and aggregate performance;
* maintain lightweight class-level grade summaries;
* export useful results;
* reuse and improve teaching material without rewriting historical sessions.

Students can:

* join easily from phones or computers;
* participate in live teaching;
* view permitted presentation content;
* answer interactive questions;
* complete self-paced practice;
* take timed exams safely through reconnects;
* review results when the teacher permits it.

Developers can:

* install the package into an existing Django project;
* run the standalone reference project;
* integrate host authentication and rosters;
* add custom activity and question types;
* add slide/content providers;
* add grading or AI backends;
* operate production deployments without maintaining a separate frontend application.

Historical classroom sessions and assessment attempts remain reproducible and auditable.

Realtime live teaching remains usable with approximately 100 students per classroom under normal production deployment.

---

# Product direction versus implementation status

`AIM.md` describes the intended product and architectural direction.

It should **not** be used as a changelog or as a list of features that happen to be implemented today.

Implementation status belongs in:

* `README.md`;
* project issues;
* milestones;
* a `ROADMAP.md`;
* an implementation record or test evidence.

A feature being described in this document means that the architecture should allow and ultimately support it. It does not imply that the feature is already complete.

When implementation choices conflict with the teaching goals in this document, optimize for the teaching workflow while preserving data integrity, package reusability, security, and historical reproducibility.
