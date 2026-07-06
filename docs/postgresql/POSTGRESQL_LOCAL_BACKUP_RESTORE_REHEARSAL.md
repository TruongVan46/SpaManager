# PostgreSQL Local Backup/Restore Rehearsal

## Scope

- Task 6.1.6.
- Local Docker PostgreSQL only.
- Production Railway PostgreSQL was not used.
- No production `DATABASE_URL` was used.
- No production migration was run.
- No migration executable or approval marker was created.

## Environment

- Container: `spamanager-postgres`
- Image: `postgres:16`
- Port: `localhost:5433 -> 5432`
- Source DB: `spamanager_dev`
- Restore check DB: `spamanager_restore_check`
- Local PostgreSQL user: `spamanager`
- Password omitted by policy

## Rehearsal Summary

- `pg_dump`: PASS
- Backup format: PostgreSQL custom format
- Backup size: `33991` bytes
- `pg_restore` to temporary DB: PASS
- `alembic_version` after restore: `0001_baseline`
- Table sanity check: PASS, `11` tables
- Flask `db current` against temporary restore DB: PASS, `0001_baseline`
- Route smoke: SKIPPED
- Cleanup: restore DB dropped, local dump removed
- Final result: PASS

## Tables Observed

- `activity_logs`
- `alembic_version`
- `appointments`
- `customers`
- `invoice_details`
- `invoices`
- `services`
- `settings`
- `users`
- `workspace_members`
- `workspaces`

## Notes

- First attempt using role `postgres` failed because the local container role is `spamanager`.
- The `0`-byte dump from that failed attempt was removed and was not used.
- The successful rehearsal used `POSTGRES_USER=spamanager`.
- No secrets or real `DATABASE_URL` values are documented here.

## Validation

- `python -m unittest`: PASS, `151` tests
- `python -m compileall .`: PASS
- `git diff --check`: PASS

## Safety Confirmations

- No migration executable was created.
- No approval marker was created.
- `APP_VERSION` was not changed.
- Railway settings / `DATABASE_URL` were not changed.
- Production migration was not run.
- Production `DATABASE_URL` was not used.
- Backup/runtime artifacts were removed or ignored and not tracked.
- Excel templates were not changed.
