# v5.9.5 Production DATABASE_URL Cutover

## Status

WAITING OWNER RAILWAY ACTION

## Scope

- Production `DATABASE_URL` cutover from SQLite to PostgreSQL.
- Fresh PostgreSQL database.
- No SQLite data migration.
- No destructive cleanup.
- No secrets in docs.

## Preconditions

- PostgreSQL service is ready.
- SQLite backup/freeze is confirmed.
- Owner confirms clean cutover.
- Required Railway env variables are ready.

## Cutover steps

- Set app `DATABASE_URL` to the Railway PostgreSQL reference variable.
- Redeploy app.
- Run schema init.
- Confirm `db current`.
- Confirm owner bootstrap.
- Run the smoke checklist.

## Evidence template

Use this format without secrets:

```text
Cutover date/time:
Railway project/environment:
PostgreSQL service name:
App DATABASE_URL changed to reference variable: yes/no
DATABASE_URL raw value exposed: no
SQLite backup confirmed: yes/no
Freeze writes confirmed: yes/no
db upgrade result:
db current result:
App deploy result:
Owner seed result:
Owner login result:
Core CRUD smoke result:
Invoice smoke result:
Settings/activity log result:
Import/export/PDF route result:
Backup Center warning checked:
Rollback path still available: yes/no
Final result: PASS/FAIL
Notes:
```

## Rollback

- Do not delete PostgreSQL service.
- Do not delete SQLite DB / Volume / backup.
- Change app `DATABASE_URL` back to SQLite if the cutover fails.
- Redeploy / restart the app.
- Check app boot and owner login on SQLite.
- Record the PostgreSQL error before retrying.

## What not to do

- Do not paste secret `DATABASE_URL` values.
- Do not delete SQLite DB / Volume / backup.
- Do not run restore.
- Do not change `APP_VERSION`.
- Do not change schema / model / migration code.
- Do not mark v5.9.0 released yet.

## Next task

v5.9.6 — Post-cutover QA and rollback check.
