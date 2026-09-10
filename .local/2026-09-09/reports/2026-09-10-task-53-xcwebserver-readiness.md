# Task 53 — xcWebServer activation readiness

## Status: READY FOR REVIEW; NOT ACTIVATED

This is a current, read-only host inspection. No xcWebServer file, database, process,
scheduler, static tree, deployment configuration, or VaultPub share was changed.

## Observed host state

- Host checkout: `/data1/pub/web/xcWebServer`, current host commit `a5f4356` with
  unrelated dirty templates/tests preserved.
- The host imports the editable package from
  `/data/p/xiaolong/django-liveclassroom/django-liveclassroom/src/liveclassroom/__init__.py`.
  No reinstall is required for package source visibility.
- `python manage.py check` passed.
- `classroom/urls.py` mounts `liveclassroom.urls` at `/classroom/`; the host keeps the
  package namespace.
- Host settings configure `XcWebServerVaultPubProvider`, the existing teacher authorizer,
  guest entry, `classroom/base.html`, and `STATIC_ROOT=BASE_DIR/'staticfiles'`.
- The observed development process is `manage.py runserver --insecure 0.0.0.0:9000`.
  No service-manager/restart command was assumed or executed.
- The checked migration state is `0001`–`0006` applied. Additive migrations `0007` through
  `0021_authoringjob_artifact_type_authoringdraft` are pending. The read-only plan listed
  the corresponding create/add operations without applying them.
- No scheduler configuration for `expire_assessment_attempts` or
  `grade_pending_attempts` was found by the read-only repository/process inspection.
  This host currently has an in-memory channel layer, so this inspection is not
  multi-worker PostgreSQL relay evidence.

## Reviewed activation sequence

The following remains a reviewable activation procedure, not authorization to execute it:

```zsh
source /data/p/anaconda3/etc/profile.d/conda.sh
conda activate django
export PATH="/data/p/bin:$PATH"
cd /data1/pub/web/xcWebServer

# Confirm the above state immediately before mutation.
python manage.py check
python manage.py showmigrations liveclassroom
python manage.py migrate liveclassroom --plan

# After host backup/checkpoint and explicit activation authorization:
python manage.py migrate liveclassroom
# Run only if the confirmed deployment serves STATIC_ROOT rather than the current
# development runserver --insecure path:
python manage.py collectstatic --noinput

# Register these in the host's established scheduler once per minute:
python manage.py expire_assessment_attempts --limit 500
python manage.py grade_pending_attempts --limit 500
```

Before a restart is proposed, inspect the actual hosting process manager and select its
existing restart mechanism. Do not kill the current `runserver` process or invent a
systemd/tmux command. After activation, use synthetic authorized host accounts to test
the Course/Class/deck/assessment/VaultPub/live/review/export path and browser-closed
expiry. Verify only `xcwebserver-liveclassroom-v1` managed VaultPub shares are revoked.

## Gate

Applying the pending migrations, registering scheduler commands, collecting static
files where required, restarting host workers, and host browser/data tests are host
mutations. They require explicit activation authorization and remain unperformed.
Task 53 cannot be accepted while Task 49/50/51/52 retain their documented partial
boundaries.
