# Task 53 — xcWebServer readiness refresh

## Status: READY FOR REVIEW; NOT ACTIVATED

This is a fresh, read-only host inspection on 2026-09-10. It does not apply a
migration, modify a scheduler, collect static files, restart a service, or create
host teaching data.

## Confirmed host state

- `liveclassroom` imports from the editable package checkout at
  `/data/p/xiaolong/django-liveclassroom/django-liveclassroom/src/liveclassroom/__init__.py`.
- The host mounts the package through `classroom/urls.py` at `/classroom/`.
- `http://127.0.0.1:9000/classroom/health/` returned the package health JSON and
  `/classroom/help/` returned an HTML page.
- Two host-owned `manage.py runserver --insecure 0.0.0.0:9000` processes were
  present. Their lifecycle remains host-owned; no process was changed.
- `showmigrations liveclassroom` reports migrations `0001` through `0006` as
  applied. The additive `0007` through `0021` migrations are pending. `migrate
  liveclassroom --plan` produced their exact additive operation list.
- A read-only search of the host checkout and system scheduler configuration did
  not find a registration for either `expire_assessment_attempts` or
  `grade_pending_attempts`.

## Activation boundary

The host needs explicit authorization before this sequence may be performed in
its confirmed Django environment:

```zsh
python manage.py migrate liveclassroom
# Register both, using the host's selected once-per-minute scheduler:
python manage.py expire_assessment_attempts --limit 500
python manage.py grade_pending_attempts --limit 500
```

The scheduler mechanism and any required service restart must be selected from
host operational policy after a backup/checkpoint is identified. The package
source is editable, so no package reinstall is needed. The current development
`runserver --insecure` path serves package static files after a browser refresh;
a production `STATIC_ROOT` deployment would need its separately authorized
`collectstatic --noinput` step.

After authorized activation, verify applied migrations, actual scheduler runs,
authenticated teacher/student workflows, timed expiry after browser closure, and
managed VaultPub-share cleanup. This report is readiness evidence only; it is
not host deployment or browser acceptance.
