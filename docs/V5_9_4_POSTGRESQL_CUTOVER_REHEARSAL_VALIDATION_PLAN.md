# v5.9.4 PostgreSQL Cutover Rehearsal and Validation Plan

## Scope

- Plan rehearsal and validation before production `DATABASE_URL` cutover.
- No production cutover in this task.
- No SQLite data migration.
- No destructive actions.
- No secrets in docs.

## Current state

- Latest stable checkpoint: `v5.8.0`.
- Production app still uses SQLite.
- SQLite data is test data.
- v5.9.1 provisioning guide is done.
- v5.9.2 backup/freeze plan is done.
- v5.9.3 schema init plan is done.

## Rehearsal strategy

- Prefer local or staging rehearsal.
- Production app `DATABASE_URL` must not change during this task.
- If no staging exists, keep this as docs/checklist only until the owner explicitly approves cutover.
- Rehearsal is not production cutover.
- Do not use real secrets in docs, logs, or chat.

## Rehearsal steps

1. Confirm PostgreSQL service exists.
2. Confirm backup/freeze plan exists.
3. Confirm required env variables are ready.
4. Init schema in the rehearsal environment.
5. Check `db current`.
6. Boot the app.
7. Verify owner bootstrap.
8. Run the smoke checklist.
9. Record evidence.
10. Reset the rehearsal env or keep PostgreSQL ready for later cutover.

## Required env variables

Placeholders only:

- `DATABASE_URL`
- `SECRET_KEY`
- `DEFAULT_OWNER_USERNAME`
- `DEFAULT_OWNER_PASSWORD`
- `DEFAULT_OWNER_EMAIL`
- `APP_VERSION`
- `PERSISTENT_ROOT`

## Smoke checklist

- App boot works.
- `db current` matches the expected revision.
- Owner is seeded when the `users` table is empty.
- Owner login works.
- Dashboard opens.
- User management opens.
- Create admin/staff if that feature exists.
- Create customer works.
- Edit customer works.
- Delete/restore customer works if supported by the app.
- Create service works.
- Create appointment works.
- Appointment status update works.
- Create invoice works.
- Invoice details are correct.
- Statistics / dashboard do not error.
- Settings read/write works.
- Activity log writes work.
- Import route does not crash.
- Export / PDF route does not crash.
- Backup Center does not run SQLite restore flow incorrectly on PostgreSQL if a guard is missing; record the blocker or warning.
- Data audit reports no serious orphan / FK errors.
- No 500 errors on the main routes.

## PostgreSQL-specific checks

- Boolean fields behave correctly.
- DateTime filters behave correctly.
- Search / filter / sort behave correctly.
- Pagination behaves correctly.
- Unique username / email / oauth_id constraints behave correctly.
- FK constraints do not create orphans.
- Float / money display and calculation do not drift significantly.
- `func.date`, `strftime`, and raw SQLite-specific logic do not break.
- SQLite-specific backup / restore flow does not run by mistake.

## Pass/fail criteria

PASS if:

- Schema init passes.
- App boot passes.
- Owner login passes.
- CRUD core flows pass.
- Invoice flow passes.
- Settings / activity log pass.
- No 500s on the main routes.
- No secret leak.
- Rollback path remains available.

FAIL if:

- Schema init fails.
- Owner seed / login fails.
- App boot fails.
- DB / FK errors are serious.
- Main route returns 500.
- Production `DATABASE_URL` changes unexpectedly.
- SQLite rollback path disappears.
- A secret leaks.

## Evidence template

Use this format without secrets:

```text
Rehearsal environment:
PostgreSQL service name:
DATABASE_URL changed on production app: no
Schema init result:
db current result:
Owner seed result:
Owner login result:
CRUD smoke result:
Invoice smoke result:
Settings/activity log result:
Import/export/PDF route result:
Backup Center guard/warning result:
Data audit result:
Rollback path confirmed:
Final result: PASS/FAIL
Notes:
```

## Rollback plan

- Rehearsal rollback is not the same as production rollback.
- If the rehearsal env fails, unset `DATABASE_URL` or set it back to SQLite/local.
- Do not delete the PostgreSQL service.
- Do not delete the SQLite DB.
- Do not delete the backup.
- Record the failure and the reason.

## What not to do

- Do not change production `DATABASE_URL`.
- Do not delete SQLite DB / Volume / backup.
- Do not run restore.
- Do not commit secrets.
- Do not bump `APP_VERSION`.
- Do not change schema / model / migration code.
- Do not mark production cutover complete from rehearsal only.

## Next task

v5.9.5 should be production `DATABASE_URL` cutover only after the owner explicitly confirms:

- PostgreSQL service is ready.
- SQLite backup/freeze is confirmed.
- Schema init / rehearsal checklist is reviewed.
- Owner accepts the clean PostgreSQL start.
