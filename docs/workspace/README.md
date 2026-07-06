# Workspace Docs

This folder collects the early v6.0 planning docs for workspace support.

## Documents

- [Workspace architecture audit](WORKSPACE_ARCHITECTURE_AUDIT.md)
- [Workspace implementation readiness audit](WORKSPACE_IMPLEMENTATION_READINESS_AUDIT.md)
- [Workspace schema design](WORKSPACE_SCHEMA_DESIGN.md)
- [Workspace schema migration plan](WORKSPACE_SCHEMA_MIGRATION_PLAN.md)
- [Workspace models and migration draft](WORKSPACE_MODELS_AND_MIGRATION_DRAFT.md)
- [Controlled workspace migration rehearsal plan](WORKSPACE_MIGRATION_REHEARSAL_PLAN.md)
- [Workspace migration execution gate and deployment control](WORKSPACE_MIGRATION_EXECUTION_GATE.md)
- [Workspace migration local rehearsal evidence](WORKSPACE_MIGRATION_LOCAL_REHEARSAL_EVIDENCE.md)
- [Workspace executable migration approval package](WORKSPACE_EXECUTABLE_MIGRATION_APPROVAL_PACKAGE.md)
- [Workspace approval provisioning plan](WORKSPACE_APPROVAL_PROVISIONING_PLAN.md)
- [Current workspace context and session selection plan](WORKSPACE_CURRENT_CONTEXT_PLAN.md)
- [Workspace data isolation plan](WORKSPACE_DATA_ISOLATION_PLAN.md)
- [Workspace user management policy](WORKSPACE_USER_MANAGEMENT_POLICY.md)
- [PostgreSQL rehearsal environment setup](../postgresql/POSTGRESQL_REHEARSAL_ENVIRONMENT_SETUP.md)
- [PostgreSQL rehearsal toolchain decision](WORKSPACE_POSTGRESQL_REHEARSAL_TOOLCHAIN_DECISION.md)
- [Workspace migration candidate](migration_candidates/0002_workspace_foundation.py.txt)

## Notes

- These documents are design-only.
- Workspace model code was added in 6.0.4 behind safe tests.
- No workspace migration executable or workspace query logic is implemented yet.
- The migration candidate is documentation-only and cannot be executed by Railway pre-deploy.
- The rehearsal plan stays documentation-only and defines the safe path before any executable migration.
- The execution gate defines when a future executable migration may be introduced and how Railway deploy control is kept safe.
- The local rehearsal evidence records the checks that were completed without introducing executable migration code.
- The approval package collects the exact evidence required before a future executable migration can be created.
- 6.0.11 records a successful Mode A production-like PostgreSQL rehearsal using Docker Desktop local PostgreSQL.
- The toolchain decision records that Option A is selected.
