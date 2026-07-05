# v5.9.2 Production SQLite Backup and Freeze Plan

## Scope

- Prepare SQLite backup and freeze plan before PostgreSQL clean cutover.
- Do not cut over `DATABASE_URL` yet.
- Do not initialize PostgreSQL schema yet.
- Do not delete SQLite DB, volume, or backup.
- Do not commit backup artifacts.

## Current state

- Latest stable checkpoint: `v5.9.0`.
- App production now uses PostgreSQL.
- SQLite data was test data and does not need migration.
- v5.9.1 created provisioning guidance before the cutover.
- The freeze plan is now historical context for the completed migration.

## Why backup still matters

Even though SQLite data is test data:

- backup gives a rollback path
- backup helps compare if needed
- backup protects against accidental destructive action
- backup allows restoring app to previous SQLite state if cutover fails

## Pre-backup checklist

- Confirm app currently boots.
- Confirm app `DATABASE_URL` still points to SQLite.
- Confirm no PostgreSQL cutover has happened.
- Confirm Railway Volume still exists.
- Confirm no one is writing data during backup.
- Confirm no backup file will be committed to Git.

## Backup options

### Option A — App Backup Center

Use the existing SQLite backup flow if available from the UI.

Checklist:

- Create backup from Backup Center.
- Confirm backup appears in the backup list.
- Confirm metadata exists.
- Do not download or upload backup into repo.
- Do not restore now.

### Option B — Railway Volume file copy

If using Railway shell or volume access:

- Locate SQLite DB path: `/app/database/spa.db`
- Copy it to a timestamped backup path under Railway Volume or download securely.

Example path only:

`/app/database/backup/pre_pg_cutover_YYYYMMDD_HHMMSS_spa.db`

Do not commit this file.

### Option C — Local/manual owner backup

If the owner downloads SQLite file manually:

- Store it outside repo.
- Name it clearly.
- Do not upload to GitHub.
- Keep it until rollback window ends.

## Freeze writes plan

Before cutover:

1. Announce maintenance window.
2. Stop creating, editing, and deleting records.
3. Stop imports.
4. Stop restore and data repair actions.
5. Optionally stop the app service briefly during the `DATABASE_URL` switch.
6. Record freeze start time.
7. Proceed to the PostgreSQL fresh init task only after backup confirmation.

## Freeze checklist

- No active user sessions doing writes.
- No customer, service, appointment, invoice, or user edits.
- No import running.
- No backup restore running.
- No `data repair --apply` running.
- Owner confirms cutover window.

## Rollback plan

If cutover fails:

1. Set app `DATABASE_URL` back to the SQLite value.
2. Restart the app.
3. Confirm login works.
4. Confirm core pages load.
5. Keep PostgreSQL service for debugging.
6. Keep the SQLite backup until the issue is resolved.
7. Record the failure reason before retrying.

## Destructive action policy

Do not delete:

- SQLite DB
- Railway Volume
- backup files
- `database/backup/`
- PostgreSQL service

until:

- PostgreSQL app boot passes
- owner login passes
- route smoke passes
- QA checklist passes
- rollback window has ended
- owner explicitly confirms deletion

## Evidence template

Use this format, without secrets:

```text
Backup type:
Backup created at:
SQLite DB path:
Backup storage location:
App version:
DATABASE_URL still SQLite: yes/no
PostgreSQL cutover done: no
Freeze start time:
Owner confirmation:
Notes:
```

## Next task

v5.9.3 should be fresh PostgreSQL schema initialization / cutover rehearsal, depending on owner confirmation.
