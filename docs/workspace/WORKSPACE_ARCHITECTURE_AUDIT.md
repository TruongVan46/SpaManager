# Workspace Architecture Audit

## Current state

- SpaManager v5.9.0 production runs on PostgreSQL.
- The app still behaves as a single-workspace / single-tenant system.
- Roles are currently global and stored on `users.role` as `OWNER`, `ADMIN`, and `STAFF`.
- Permission checks live in `core/auth/permissions.py`, route guards, and `core/auth/decorators.py`.
- Owner bootstrap is handled by `AuthService.seed_owner_if_empty()` during app startup when the baseline schema is ready.
- There is no workspace context in the session, no workspace membership table, and no workspace foreign keys on business tables yet.

## Target model

- Platform-level roles manage the platform itself: approvals, workspace lifecycle, and account onboarding.
- Workspace-level roles manage day-to-day spa operations inside a workspace.
- Workspace-scoped data must stay isolated per workspace.
- Users should only see data that belongs to their workspace.

## Current models and workspace scope

| Model/Table | Current scope | Target scope | Notes |
|---|---|---|---|
| `users` | Global identity/auth | Platform identity + workspace membership | Keep login identity global; add workspace membership later. |
| `customers` | Global single-tenant data | Workspace-scoped | Needs `workspace_id` before v6.0 query cutover. |
| `services` | Global single-tenant data | Workspace-scoped | Unique name rules should become workspace-aware. |
| `appointments` | Global single-tenant data | Workspace-scoped | Must be filtered everywhere appointment/customer/service data is loaded. |
| `invoices` | Global single-tenant data | Workspace-scoped | Reporting, export, print, and restore paths must scope by workspace. |
| `invoice_details` | Global child table via invoice | Workspace-scoped, optionally duplicated `workspace_id` | Can derive from invoice, but explicit `workspace_id` helps query performance. |
| `activity_logs` | Global audit trail | Workspace-scoped + actor user | Logs should keep actor identity and workspace boundary. |
| `settings` | Global config + spa info | Mixed: global platform settings + workspace settings | Some keys may stay global; spa profile settings should become workspace-specific. |

## Routes/services needing workspace filters

| Area | Files/routes | Workspace risk | Notes |
|---|---|---|---|
| Auth / user management | `services/auth_service.py`, `routes/auth.py`, `routes/user.py`, `services/user_service.py`, `core/auth/decorators.py` | Global identity today, no workspace membership | Needs a future split between platform role and workspace membership role. |
| Customers | `routes/customer.py`, `services/customer_service.py` | All CRUD/list/search/detail queries are global today | Must scope all customer reads, duplicates, and statistics by workspace. |
| Services | `routes/service.py`, `services/service_service.py` | Global list/search/delete/restore | Service names and dependency counts need workspace-aware constraints. |
| Appointments | `routes/appointment.py`, `services/appointment_service.py` | Calendar/list/search/status queries are global | Calendar views and status updates must be workspace-filtered. |
| Invoices | `routes/invoice.py`, `services/invoice_service.py` | Printing, export, delete, restore, detail queries are global | Invoice print/PDF/export must never cross workspace boundaries. |
| Statistics / dashboard | `routes/statistics.py`, `routes/dashboard.py`, `services/dashboard_statistics_service.py`, `services/report_service.py` | Aggregates currently cover the whole database | Must add workspace context before any multi-workspace rollout. |
| Activity logs | `routes/activity_log.py`, `services/activity_log_service.py` | Audit trail is global today | Logs should be filtered by workspace and actor. |
| Recycle bin | `routes/recycle_bin.py`, `services/recycle_bin_service.py` | Restore/permanent delete touches global tables | Restore logic must be workspace-aware to avoid cross-tenant recovery. |
| Settings / backup / restore / import | `routes/setting.py`, `services/backup_service.py`, `services/restore_service.py`, `services/import_service.py`, `repositories/backup_repository.py` | Backup Center, import, and restore are global operations | Needs a workspace-safe policy before any multi-workspace data is introduced. |
| Export / PDF | `routes/statistics.py`, `routes/invoice.py`, `utils/export_excel.py`, `utils/export_pdf.py` | Exports currently read global data | Export helpers will need workspace context and safe defaults. |
| Diagnostics / performance | `services/operational_diagnostics_service.py`, `services/performance_profile_service.py` | Global counts and system checks only | These tools will need a platform scope and possibly workspace-aware drill-downs later. |

## Workspace schema options

### Option A — `users.workspace_id`

**Pros**

- Simpler to implement for a single primary workspace per user.
- Easier migration if each spa account only belongs to one workspace.
- Fewer joins for common reads.

**Cons**

- Does not fit future multi-workspace membership well.
- Harder to support invited users across multiple workspaces.
- Platform roles and workspace roles get mixed together quickly.

### Option B — `workspace_members`

**Pros**

- Supports one user in multiple workspaces.
- Cleaner separation between platform identity and workspace membership.
- Better fit for approval/onboarding flows and future expansion.

**Cons**

- Requires an extra join for most workspace queries.
- Needs more careful migration and session/context design.

## Recommended approach

Recommended for v6.0: **Option B — `workspaces` + `workspace_members`**.

Why:

- The product roadmap already expects approved accounts and separate workspaces.
- The business data boundary needs to be explicit, not inferred from one user column.
- The current `users.role` model can continue to represent the global/platform side during transition, while workspace membership controls access to spa data.
- This gives us room to support future multi-workspace or invited-user workflows without another schema reset.

## Unique constraints plan

Current constraints are mostly global:

- `users.username` is globally unique.
- `users.email` is globally unique.
- `users.oauth_id` is globally unique.
- `settings.key` is globally unique.

Recommended future direction:

- `users.username`: keep globally unique for identity stability.
- `users.email`: keep globally unique for account identity and password reset safety.
- `users.oauth_id`: keep globally unique.
- `customers.phone` / `customers.email`: make workspace-aware uniqueness if duplicate protection remains necessary.
- `services.name`: make unique per workspace, not globally.
- `settings.key`: split into platform-global settings and workspace settings; workspace keys should be unique per workspace.

Implementation note:

- Add composite indexes like `(workspace_id, name)` or `(workspace_id, phone)` where lookup patterns need it.
- Backfill `workspace_id` first, then tighten uniqueness and nullability.

## Migration plan draft

High-level sequence for a future non-destructive migration:

1. Create `workspaces`.
2. Create `workspace_members`.
3. Create a default workspace for existing production data.
4. Assign the existing owner as the first workspace owner.
5. Add `workspace_id` to workspace-scoped tables.
6. Backfill all existing rows into the default workspace.
7. Add indexes and workspace-aware unique constraints.
8. Switch queries to require workspace context.
9. Only after backfill and verification, consider making `workspace_id` non-null where appropriate.

No migration is created in this task.

## Security checklist

- Verify every `Model.query.all()/count()/get()/filter_by()` path that touches customer, service, appointment, invoice, statistics, logs, settings, import/export, and backup flows.
- Verify `current_user` only resolves within the active workspace context.
- Verify `User.query` lookups do not accidentally expose cross-workspace users.
- Verify exports and PDFs never include another workspace’s data.
- Verify backup/restore policy is explicitly defined before introducing workspace-aware restore logic.
- Verify platform owner/admin routes remain separate from workspace owner/admin/staff routes.
- Verify admin dashboards and diagnostics do not leak global counts when workspace scope is required.

## Follow-up tasks

- 6.0.2 Workspace schema design
- 6.0.3 Workspace models and migration
- 6.0.4 Workspace context/session
- 6.0.5 Workspace-scoped queries
- 6.0.6 Workspace user management
- 6.0.7 Workspace QA and security tests
- 6.0.8 v6.0.0 checkpoint

## Related docs

- [Workspace docs index](README.md)
- [Workspace schema design](WORKSPACE_SCHEMA_DESIGN.md)
- [Workspace models and migration draft](WORKSPACE_MODELS_AND_MIGRATION_DRAFT.md)
