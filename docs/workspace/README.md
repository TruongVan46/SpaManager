# Workspace Docs

This folder collects the planning and validation documents for workspace support.

## Final Release & Closure

- [SpaManager Version 6.5 — Workspace Tenant Isolation Closure](WORKSPACE_ISOLATION_CLOSURE.md) (Production Validated & Closed)

## Planning & Rehearsal Archive

- [Workspace architecture audit](WORKSPACE_ARCHITECTURE_AUDIT.md)
- [Workspace approval portal account management](WORKSPACE_APPROVAL_PORTAL_MANAGEMENT.md)
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
- [Workspace isolation readiness & smoke report](WORKSPACE_ISOLATION_READINESS_SMOKE.md)
- [Production workspace readiness checklist](WORKSPACE_PRODUCTION_READINESS_CHECKLIST.md)
- [Workspace staff soft delete smoke checklist](WORKSPACE_STAFF_SOFT_DELETE_SMOKE.md)
- [PostgreSQL rehearsal environment setup](../postgresql/POSTGRESQL_REHEARSAL_ENVIRONMENT_SETUP.md)
- [PostgreSQL rehearsal toolchain decision](WORKSPACE_POSTGRESQL_REHEARSAL_TOOLCHAIN_DECISION.md)
- [Workspace migration candidate](migration_candidates/0002_workspace_foundation.py.txt)
- [Permanent purge dependency and policy discovery](PERMANENT_PURGE_DEPENDENCY_POLICY_DISCOVERY.md)
- [Permanent purge security and retention policy](PERMANENT_PURGE_SECURITY_RETENTION_POLICY.md)
- [Permanent purge schema and migration proposal](PERMANENT_PURGE_SCHEMA_MIGRATION_PROPOSAL.md)

## Notes

- Workspace tenant isolation is fully implemented and active in production as of Version 6.5.
- The migration `0003_workspace_foundation.py` was successfully applied by Railway.
- Business data is securely scoped using direct `workspace_id` parameters and session contexts.
- All historical documents are retained here to record design decisions, rehearsal results, and architecture analysis.
