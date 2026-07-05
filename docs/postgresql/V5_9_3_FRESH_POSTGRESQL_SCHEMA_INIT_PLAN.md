# v5.9.3 Fresh PostgreSQL Schema Initialization Plan

## Scope

- Plan fresh PostgreSQL schema initialization.
- No SQLite data migration.
- No production `DATABASE_URL` cutover in this task.
- No destructive actions.
- No secrets in docs.

## Current state

- Latest stable checkpoint: `v5.9.0`.
- Production app now uses PostgreSQL.
- SQLite data was test data.
- v5.9.1 provisioning guide is done.
- v5.9.2 backup/freeze plan is done.

## Preconditions

- PostgreSQL service exists.
- SQLite backup/freeze plan is reviewed.
- Owner confirms the clean cutover direction.
- Required Railway variables are ready.
- No production DB URL secrets are copied to repo.

## Required environment variables

Placeholders only:

- `DATABASE_URL`
- `SECRET_KEY`
- `DEFAULT_OWNER_USERNAME`
- `DEFAULT_OWNER_PASSWORD`
- `DEFAULT_OWNER_EMAIL`
- `APP_VERSION`
- `PERSISTENT_ROOT`

## Schema initialization commands

Use the current migration CLI commands:

```powershell
.\venv\Scripts\python.exe -m flask --app app db upgrade
.\venv\Scripts\python.exe -m flask --app app db current
.\venv\Scripts\python.exe -m flask --app app db stamp head
```

When to use each:

- `db upgrade`: create the fresh schema from the baseline on a new PostgreSQL database.
- `db current`: confirm the active revision after schema init.
- `db stamp head`: record the current revision when the schema already exists but revision tracking needs to be aligned.

## Owner bootstrap behavior

Current source behavior:

- `app.py` calls `AuthService.seed_owner_if_empty()`
- `AuthService.seed_owner_if_empty()` runs on app boot
- it uses `DEFAULT_OWNER_*` config values
- it seeds the owner only when the `users` table is empty

Operational note:

- schema init creates tables
- owner is created on first boot if the `users` table is empty
- `DEFAULT_OWNER_PASSWORD` must exist in Railway app variables
- do not write the password into docs
- change the owner password after first login if needed
- admin bootstrap is not present yet; only owner bootstrap exists

## Pre-init safety checklist

- PostgreSQL service is in the correct Railway project / environment.
- SQLite backup was created or the owner confirmed the test data can be left behind, while rollback backup is still preserved.
- Freeze writes has already started.
- App `DATABASE_URL` is still SQLite before cutover.
- No user is actively writing data.
- `DEFAULT_OWNER_USERNAME`, `DEFAULT_OWNER_PASSWORD`, and `DEFAULT_OWNER_EMAIL` are ready.
- `SECRET_KEY` is ready.
- `APP_VERSION` remains `v5.9.0` for the release after this checkpoint.
- `PERSISTENT_ROOT` is unchanged.
- No volume is deleted.

## Post-init verification checklist

- `db current` matches the expected revision.
- Tables exist: `users`, `customers`, `services`, `appointments`, `invoices`, `invoice_details`, `activity_logs`, `settings`.
- App boots with PostgreSQL.
- Owner is seeded.
- Owner login works.
- Dashboard opens.
- Customer creation works.
- Service creation works.
- Appointment creation works.
- Invoice creation works.
- Settings work.
- Activity log writes work.
- Data audit reports no serious errors.
- Backup Center does not use SQLite restore flow for PostgreSQL unless a guard is implemented later.
- No orphan / FK errors appear.

## Failure and rollback plan

If schema init or app boot fails:

1. Do not delete the PostgreSQL service.
2. Do not delete SQLite DB / backup.
3. Change the app `DATABASE_URL` back to SQLite later, when the cutover task has already switched it.
4. Restart the app.
5. Check login and app health.
6. Record the error in the checklist.
7. Do not retry until the root cause is known.

## What not to do

- Do not migrate SQLite data.
- Do not delete SQLite.
- Do not delete backup.
- Do not run restore.
- Do not commit secrets.
- Do not update `APP_VERSION`.
- Do not change schema / model / migration code.

## Next task

v5.9.4 should be PostgreSQL cutover rehearsal / staging-style validation, then v5.9.5 production `DATABASE_URL` cutover only after owner confirmation.
