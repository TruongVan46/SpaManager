# Workspace Docs

This folder collects the early v6.0 planning docs for workspace support.

## Documents

- [Workspace architecture audit](WORKSPACE_ARCHITECTURE_AUDIT.md)
- [Workspace schema design](WORKSPACE_SCHEMA_DESIGN.md)
- [Workspace models and migration draft](WORKSPACE_MODELS_AND_MIGRATION_DRAFT.md)
- [Controlled workspace migration rehearsal plan](WORKSPACE_MIGRATION_REHEARSAL_PLAN.md)
- [Workspace migration execution gate and deployment control](WORKSPACE_MIGRATION_EXECUTION_GATE.md)
- [Workspace migration local rehearsal evidence](WORKSPACE_MIGRATION_LOCAL_REHEARSAL_EVIDENCE.md)
- [Workspace migration candidate](migration_candidates/0002_workspace_foundation.py.txt)

## Notes

- These documents are design-only.
- Workspace model code was added in 6.0.4 behind safe tests.
- No workspace migration executable or workspace query logic is implemented yet.
- The migration candidate is documentation-only and cannot be executed by Railway pre-deploy.
- The rehearsal plan stays documentation-only and defines the safe path before any executable migration.
- The execution gate defines when a future executable migration may be introduced and how Railway deploy control is kept safe.
- The local rehearsal evidence records the checks that were completed without introducing executable migration code.
