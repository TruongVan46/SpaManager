# Workspace Executable Migration Approval Package

## Scope

- Summarizes the evidence required before making the workspace migration executable.
- Does not approve production migration by itself.
- Does not create the approval marker.
- Does not create `migrations/versions/0002_workspace_foundation.py`.
- Does not run production migration.

## Current status

- Candidate exists as a docs-only tested artifact: `docs/workspace/migration_candidates/0002_workspace_foundation.py.txt`
- Production-like local PostgreSQL rehearsal: PASS.
- Temporary executable migration was removed after rehearsal.
- Final repository currently has no executable workspace migration.
- Final repository currently has no approval marker.

## Evidence summary

- Environment: Docker Desktop local PostgreSQL.
- Rehearsal DB: `spamanager_workspace_prodlike`.
- Baseline source: `v5.9.0`.
- `db current` before migration: `0001_baseline`.
- Local dry-run migration: PASS.
- `db current` after migration: `0002_workspace_foundation`.
- Schema verification:
  - `workspaces` table exists.
  - `workspace_members` table exists.
  - nullable `workspace_id` columns exist on scoped business tables.
- Data verification:
  - Default Workspace exists.
  - owner membership exists.
  - orphan `workspace_members = 0`.
- App smoke UI: NOT RUN unless separately verified.
- Tests/GitHub Actions: PASS.
- Production migration: NOT RUN.

## Approval gate

The migration may only become executable when the owner confirms the exact phrase:

`approve workspace migration deploy`

Do not rely on vague approval such as:

- ok
- proceed
- continue
- do it later

The approval must be explicit.

## Required production pre-checks

- Production app is currently healthy.
- Owner can login.
- Customer/service/appointment/invoice pages still work.
- PostgreSQL provider backup created.
- Backup timestamp recorded.
- Freeze writes started.
- No import/export/restore/backup job is running.
- Railway pre-deploy behavior understood.
- Deployment window confirmed.
- Rollback strategy reviewed.
- No secrets in repo/log/chat.
- Final `git status` clean except intended migration/approval files.

## Files allowed in future approval commit

When the owner approves, the future controlled commit may include:

- `migrations/versions/0002_workspace_foundation.py`
- `docs/workspace/WORKSPACE_MIGRATION_EXECUTION_APPROVAL.md`
- `docs/workspace/WORKSPACE_MIGRATION_LOCAL_REHEARSAL_EVIDENCE.md` if a final note is needed
- `tests/test_basic.py` only if the safety test is intentionally updated for the approval marker

Do not include out-of-scope files.

## Approval marker template

Future file template for `docs/workspace/WORKSPACE_MIGRATION_EXECUTION_APPROVAL.md`:

- Approval phrase:
- Approved by:
- Date/time:
- Production backup timestamp:
- Rehearsal evidence link:
- Migration file:
- Railway deployment window:
- Rollback plan:
- Final go/no-go:

Do not create `docs/workspace/WORKSPACE_MIGRATION_EXECUTION_APPROVAL.md` in task 6.0.13.

## Future execution sequence

When the approval is real:

1. Confirm clean working tree.
2. Confirm production backup.
3. Confirm freeze writes.
4. Create approval marker.
5. Copy the tested candidate to `migrations/versions/0002_workspace_foundation.py`.
6. Ensure the file uses the project custom migration style, not Alembic `op`.
7. Run tests locally.
8. Commit the controlled migration.
9. Push during the migration window.
10. Railway pre-deploy runs `python -m flask --app app db upgrade`.
11. Watch logs.
12. Verify production `db current`.
13. Smoke test the app.
14. Unfreeze writes.

## Rollback warning

- Do not blindly downgrade production.
- If migration fails before schema or data changes, stop and inspect.
- If migration partially applies, use the provider backup/restore strategy.
- App rollback alone may not rollback schema.
- Keep a backup before migration.

## Final recommendation

Current recommendation:

READY FOR OWNER APPROVAL PACKAGE REVIEW

But:

NOT READY TO AUTO-RUN PRODUCTION MIGRATION
until the explicit owner approval phrase, backup, and migration window exist.
