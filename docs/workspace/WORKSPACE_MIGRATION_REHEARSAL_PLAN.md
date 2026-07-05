# Controlled Workspace Migration Rehearsal Plan

## Purpose

This plan describes the safe rehearsal path for the workspace foundation migration before any executable migration is ever considered for production.

The goal is to prove the migration can be applied, verified, and rolled back safely in a controlled local or staging environment without touching the live Railway deployment flow.

## Non-goals

- Do not create or ship an executable migration in `migrations/versions/` yet.
- Do not change production `DATABASE_URL`, `APP_VERSION`, or schema behavior.
- Do not introduce workspace-scoped query logic before the migration foundation is rehearsed.
- Do not modify backup, restore, import, export, PDF, CSRF, or auth behavior in this step.

## Rehearsal inputs

- Candidate artifact: `docs/workspace/migration_candidates/0002_workspace_foundation.py.txt`
- Draft model spec: `docs/workspace/WORKSPACE_MODELS_AND_MIGRATION_DRAFT.md`
- Schema intent: `docs/workspace/WORKSPACE_SCHEMA_DESIGN.md`
- Architecture audit: `docs/workspace/WORKSPACE_ARCHITECTURE_AUDIT.md`

## Rehearsal phases

### Phase 1 — Preflight

- Confirm the candidate remains docs-only and is not executable by Railway.
- Confirm the baseline migration `0001_baseline` is still the only executable workspace migration in `migrations/versions/`.
- Confirm no production-sensitive files are modified outside the workspace docs area.
- Confirm there is a backup and recovery plan for the database being rehearsed.

### Phase 2 — Local database rehearsal

- Apply the baseline schema to a local or staging copy.
- Review the workspace candidate against the current models and tables.
- Verify the proposed `workspaces` and `workspace_members` tables fit the current schema naming conventions.
- Confirm nullable `workspace_id` backfill assumptions are still valid for existing rows.

### Phase 3 — Duplicate and integrity review

- Check for duplicate-sensitive rows in customer, service, appointment, invoice, and settings data.
- Confirm the default workspace backfill does not require destructive cleanup.
- Confirm the candidate keeps `workspace_id` nullable until scoping code exists.
- Confirm risky unique constraints stay deferred until data is audited.

### Phase 4 — Recovery rehearsal

- Validate that the rehearsal database can be restored to its pre-rehearsal state.
- Confirm no irreversible data transformation is required for the first pass.
- Confirm rollback remains a controlled data plan rather than a blind schema drop.

### Phase 5 — Approval gate

- Only after local/staging rehearsal passes should an executable migration be drafted.
- The executable migration should be reviewed before any production push.
- Production deploy remains blocked until the owner explicitly approves the executable migration path.

## Verification checklist

- [ ] Candidate file stays in `docs/workspace/migration_candidates/`.
- [ ] No file is added to `migrations/versions/` for workspace v6.0.5 rehearsal.
- [ ] Rehearsal database can be created and torn down safely.
- [ ] Default workspace backfill assumptions are documented and accepted.
- [ ] Duplicate-risk areas are identified before any unique constraint is introduced.
- [ ] Rollback path is written down and reviewed.
- [ ] Railway pre-deploy behavior is unchanged.

## Exit criteria

The rehearsal is complete only when:

- the candidate remains non-executable,
- the local/staging rehearsal steps are reviewed and understood,
- the default workspace backfill strategy is accepted,
- and no production migration is scheduled without a separate implementation approval.

## Follow-up

After this rehearsal plan is approved, the next step is to implement the migration in a separate controlled task with explicit deploy safety review.
