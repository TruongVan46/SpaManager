# Workspace Migration Execution Gate and Deployment Control

## Purpose

This document defines the control gate that must pass before any executable workspace migration can be introduced into `migrations/versions/` and before Railway can be allowed to run `python -m flask --app app db upgrade` against production.

The gate is intentionally strict because Railway pre-deploy migration execution is automatic once executable migration code exists.

## Hard rule

- Do not create or merge an executable workspace migration until this gate is explicitly approved.
- Do not rely on Railway pre-deploy to “test” the migration safely.
- Do not treat documentation-only candidates as deployable artifacts.
- The migration must be blocked before the file reaches `migrations/versions/`.

## Gate requirements

### 1. Candidate review complete

- The docs-only candidate has been reviewed.
- The candidate matches the current model and schema design.
- The candidate still keeps `workspace_id` nullable during the first pass.

### 2. Local rehearsal complete

- The rehearsal plan has been followed in a local or staging database.
- The default workspace backfill is proven safe.
- Duplicate-sensitive tables have been reviewed before unique constraints are introduced.
- No destructive downgrade is required for the first pass.

### 3. Backup and recovery verified

- A production-safe backup exists before any migration execution.
- Recovery from that backup has been rehearsed.
- The rollback story is a controlled data plan, not a blind schema drop.

### 4. Deployment authority confirmed

- The owner has explicitly approved the executable migration path.
- There is a clear decision that Railway may run the migration automatically at deploy time.
- The deployer understands the exact revision being introduced.

### 5. Production readiness confirmed

- There is no unresolved duplicate-data risk that would make constraints unsafe.
- There is no hidden dependency on workspace-scoped query code that has not yet shipped.
- The migration does not introduce surprise changes to auth, backup, PDF, or import/export behavior.

## Deployment control policy

### Before approval

- Keep the workspace migration as documentation-only.
- Keep the candidate out of `migrations/versions/`.
- Keep Railway deployment behavior unchanged.

### After approval

- Add the executable migration only in a dedicated implementation task.
- Re-run rehearsal checks against a local/staging database.
- Confirm the exact revision name and down-revision chain before merge.
- Deploy only when the backup and recovery plan is still current.

## Railway safety note

If an executable migration is present, Railway’s pre-deploy `db upgrade` can execute it automatically.

That means the only safe control point is **before** the file reaches `migrations/versions/`.

## Exit criteria

The gate is open only when all of the following are true:

- rehearsal passed,
- recovery verified,
- owner approved,
- and the executable migration is ready for a controlled deploy.

## Follow-up

Once this gate is opened, the next step is to implement the executable migration in a separate task and keep the deployment sequence tightly controlled.

The local rehearsal evidence lives in `docs/workspace/WORKSPACE_MIGRATION_LOCAL_REHEARSAL_EVIDENCE.md`.
