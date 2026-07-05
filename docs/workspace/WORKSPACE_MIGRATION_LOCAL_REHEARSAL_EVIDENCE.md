# Workspace Migration Local Rehearsal Evidence

## Purpose

This document captures the local rehearsal evidence for the workspace migration foundation review.

The rehearsal was intentionally kept non-destructive and documentation-only. No executable migration was added to `migrations/versions/`.
The rehearsal used a local Docker Desktop PostgreSQL toolchain in **Mode A**.

## Evidence summary

| Check | Evidence |
|---|---|
| Candidate remains docs-only | `docs/workspace/migration_candidates/0002_workspace_foundation.py.txt` stays outside `migrations/versions/`. |
| No executable workspace migration added | `migrations/versions/` still contains only the baseline migration. |
| Railway pre-deploy risk avoided | No new executable migration file was introduced, so Railway cannot auto-run workspace migration code. |
| Rehearsal plan documented | `docs/workspace/WORKSPACE_MIGRATION_REHEARSAL_PLAN.md` defines the local/staging rehearsal path. |
| Execution gate documented | `docs/workspace/WORKSPACE_MIGRATION_EXECUTION_GATE.md` blocks merge/deploy until approval. |
| Repository scope stayed safe | No production DB, schema, auth, backup, or export behavior was changed for this task. |

## Local validation evidence

The following validation was completed successfully during the rehearsal work:

- `python -m unittest discover -s tests -p "test*.py" -v`
- `python -m compileall .`

### Validation result

- Unit tests passed.
- Compilation passed.
- Workspace rehearsal docs and safety tests remained green.

## Critical rehearsal evidence

| Item | Status | Notes |
|---|---|---|
| Rehearsal environment | PASS | Docker Desktop local PostgreSQL on `spamanager_workspace_prodlike` was used for the rehearsal. |
| Temp executable migration in `migrations/versions/` | YES (temporary) | `migrations/versions/0002_workspace_foundation.py` was created only for the local dry-run and then deleted. |
| `python -m flask --app app db upgrade` | PASS | Applied `0002_workspace_foundation` locally. |
| `python -m flask --app app db current` | PASS | Reported `0001_baseline` before migration and `0002_workspace_foundation` after migration. |
| Schema verification | PASS | `workspaces`, `workspace_members`, and nullable `workspace_id` columns were verified. |
| Data verification | PASS | Default workspace and owner membership were verified; orphan `workspace_members` count was `0`. |
| Final result | PASS | Local production-like PostgreSQL rehearsal completed successfully. |

## Review notes

- The migration candidate is still documentation-only.
- The execution gate remains the only approved control point before any executable migration is ever added.
- The local rehearsal evidence supports the current decision to keep production migration behavior unchanged.
- 6.0.11 confirms a production-like PostgreSQL rehearsal PASS in Mode A with Docker Desktop.
- App smoke UI was not run, so any UI smoke result remains NOT RUN unless separately validated.
- The PostgreSQL rehearsal environment setup guide is documentation-only and now reflects a working local toolchain.
- The toolchain decision is documented in `docs/workspace/WORKSPACE_POSTGRESQL_REHEARSAL_TOOLCHAIN_DECISION.md` and now records Option A as selected.

## Conclusion

The workspace migration foundation has now completed a local production-like PostgreSQL rehearsal in Mode A, while app smoke UI remains a separate validation item if not run.

6.0.13 now packages the approval checklist in `docs/workspace/WORKSPACE_EXECUTABLE_MIGRATION_APPROVAL_PACKAGE.md`; it does not create an executable migration or approval marker.

The repository now has:

- a rehearsal plan,
- an execution gate,
- and local rehearsal evidence,

but **no executable workspace migration**.
