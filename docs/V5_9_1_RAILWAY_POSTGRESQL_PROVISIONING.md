# v5.9.1 Railway PostgreSQL Provisioning

## Scope

- Provision Railway PostgreSQL service.
- Do not cut over app `DATABASE_URL` yet.
- Do not initialize production schema yet unless explicitly approved.
- Do not delete SQLite data or backup.
- Do not commit secrets.

## Current state

- Latest stable checkpoint: `v5.8.0`.
- App production still uses SQLite.
- SQLite data is test data and does not need migration.
- v5.9 will use fresh PostgreSQL clean cutover.

## Provisioning steps

1. Open the Railway project containing the SpaManager app.
2. Add a PostgreSQL database service.
3. Name the service clearly.
4. Wait until the PostgreSQL service is healthy.
5. Open the PostgreSQL service Variables tab.
6. Confirm these variables exist:
   - `DATABASE_URL`
   - `PGHOST`
   - `PGPORT`
   - `PGUSER`
   - `PGPASSWORD`
   - `PGDATABASE`
7. Do not paste real values into docs or repo.
8. Do not update the app service `DATABASE_URL` yet.

## App service variable plan for cutover

Future cutover task should set the app service `DATABASE_URL` to the Railway reference variable:

`DATABASE_URL=${{Postgres.DATABASE_URL}}`

Use the actual service name if different.

Do not do this in v5.9.1 unless the owner explicitly approves cutover.

## Safety checklist

- PostgreSQL service created in the correct Railway project.
- PostgreSQL service is healthy.
- App service still points to SQLite.
- App production still boots.
- No `DATABASE_URL` secret committed.
- No `APP_VERSION` change.
- No schema/model/migration changes.
- No SQLite DB deletion.
- No backup deletion.

## What not to do

- Do not run `db upgrade` on production yet.
- Do not set app `DATABASE_URL` yet.
- Do not delete the SQLite volume.
- Do not remove `PERSISTENT_ROOT`.
- Do not restore anything.
- Do not run destructive commands.
- Do not commit real Railway variables.

## Evidence to collect

Do not collect secret values.

Allowed evidence:

- PostgreSQL service name
- Railway project/environment name
- PostgreSQL service health/status
- Confirmation `DATABASE_URL` variable exists
- Confirmation app service `DATABASE_URL` has not changed
- Screenshot notes without revealing secrets, if needed

## Next task

v5.9.2 should be the production SQLite backup and freeze plan, or fresh PostgreSQL schema initialization planning depending on owner confirmation.
