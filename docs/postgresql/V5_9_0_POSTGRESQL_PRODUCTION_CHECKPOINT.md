# v5.9.0 PostgreSQL Production Checkpoint

## Scope

- PostgreSQL production cutover completed.
- Fresh PostgreSQL database.
- No SQLite data migration.
- SQLite data was test data.
- Backup Center guarded for PostgreSQL mode.
- v5.9.0 is the new stable checkpoint.

## Completed tasks

- 5.9.1 Railway PostgreSQL provisioning
- 5.9.2 Production SQLite backup and freeze plan
- 5.9.3 Fresh PostgreSQL schema initialization plan
- 5.9.4 PostgreSQL cutover rehearsal and validation plan
- 5.9.5 Production DATABASE_URL cutover
- 5.9.6 Post-cutover QA and PostgreSQL Backup Center guard
- 5.9.7 v5.9.0 production checkpoint

## Production state

- Production database engine: PostgreSQL.
- App service uses PostgreSQL `DATABASE_URL` via Railway reference variable.
- Do not paste raw `DATABASE_URL`.
- SQLite database is no longer the production database.
- PostgreSQL tables exist.
- Owner bootstrap passed.
- Core app smoke passed.

## Validation summary

- App deploy pass.
- Owner login pass.
- Customer/service/data entry pass.
- Backup Center PostgreSQL warning/guard pass.
- Full unittest pass.
- compileall pass.

## Backup/restore status

- App Backup Center no longer runs SQLite DB backup/restore in PostgreSQL mode.
- PostgreSQL DB backup should be handled by Railway/PostgreSQL provider.
- Restore SQLite backup into PostgreSQL is blocked.
- Future enhancement may add PostgreSQL provider backup integration, but not in v5.9.0.

## What changed from v5.8.0

- Production database moved from SQLite to PostgreSQL.
- SQLite test data was not migrated.
- Fresh PostgreSQL schema initialized.
- Owner seeded on clean PostgreSQL database.
- Backup Center guarded for PostgreSQL mode.
- Documentation/runbooks updated.

## What is not included

- No workspace/multi-tenant feature yet.
- No Google registration/onboarding yet.
- No PostgreSQL `pg_dump`/`pg_restore` implementation inside app.
- No PostgreSQL CI required job yet unless separately completed.
- No migration of old SQLite test data.

## Operational notes

- Keep PostgreSQL service.
- Do not delete PostgreSQL data.
- Use Railway/PostgreSQL backups for DB-level backup.
- Keep secrets only in Railway variables.
- Do not commit database dumps/backups.
- If rollback needed, follow runbook.

## Next milestone

v6.0 — Workspace Foundation

or, if user wants before workspace:

v5.9.x polish/hotfix only.
