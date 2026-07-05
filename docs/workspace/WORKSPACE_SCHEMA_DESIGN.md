# Workspace Schema Design

## Current baseline

- Production DB: PostgreSQL.
- Latest stable checkpoint: v5.9.0.
- App is still single-workspace in schema and code.
- 6.0.1 workspace architecture audit is complete.
- Recommended architecture: `workspaces` + `workspace_members`.

## Proposed tables

### `workspaces`

| Field | Type | Nullable | Unique / Index | Notes |
|---|---|---|---|---|
| `id` | integer/bigint PK | No | PK | Surrogate key. |
| `name` | string/text | No | Index | Human-readable workspace name. |
| `slug` | string/text | No | `unique` | Stable URL-safe identifier. |
| `status` | string | No | Index | `active`, `pending`, `suspended`, `archived`. |
| `created_at` | datetime | No | Index | Creation timestamp. |
| `updated_at` | datetime | No |  | Update timestamp. |
| `created_by_id` | FK -> `users.id` | Yes | Index | Audit trail for creator. |
| `notes` | text | Yes |  | Optional admin notes. |

**Design decisions**

- `slug` should be globally unique.
- `status` should be stored as a string with app-level enum validation, not a new DB enum in v6.0.
- `owner_user_id` is not required in this table because ownership can be derived from `workspace_members.role = owner`.
- `pending` is useful for the approval/onboarding flow that is planned for v6.1.

### `workspace_members`

| Field | Type | Nullable | Unique / Index | Notes |
|---|---|---|---|---|
| `id` | integer/bigint PK | No | PK | Surrogate key. |
| `workspace_id` | FK -> `workspaces.id` | No | `unique(workspace_id, user_id)` / index | Membership boundary. |
| `user_id` | FK -> `users.id` | No | index | Identity of the member. |
| `role` | string | No | index | `owner`, `admin`, `staff`. |
| `status` | string | No | index | `active`, `invited`, `disabled`. |
| `invited_by_id` | FK -> `users.id` | Yes |  | Optional inviter. |
| `joined_at` | datetime | Yes |  | Set when invite is accepted or member is activated. |
| `created_at` | datetime | No |  | Creation timestamp. |
| `updated_at` | datetime | No |  | Update timestamp. |

**Design decisions**

- One user can belong to multiple workspaces.
- A workspace can have multiple owners if needed by business rules.
- DB-level enforcement for “exactly one owner” is intentionally deferred; app/service logic and tests should enforce minimum ownership safety first.

## Existing table changes

| Existing table | Proposed workspace fields | Indexes / constraints | Notes |
|---|---|---|---|
| `users` | None in v6.0.2 | Keep current global unique fields | Keep `users.role` for now as legacy/global role during transition. |
| `customers` | `workspace_id` | `index(workspace_id, phone)`, `index(workspace_id, email)` if needed | Workspace-scoped business data. |
| `services` | `workspace_id` | `index(workspace_id, name)` | Service names should become workspace-aware. |
| `appointments` | `workspace_id` | `index(workspace_id, appointment_time)`, `index(workspace_id, status)`, `index(workspace_id, customer_id)` | Calendar and reporting need workspace filters. |
| `invoices` | `workspace_id` | `index(workspace_id, created_at)`, `index(workspace_id, customer_id)` | Printing/PDF/export/reporting scope. |
| `invoice_details` | Optional `workspace_id` | `index(workspace_id, invoice_id)` if added | Recommended as a denormalized guard for faster workspace validation and reports. |
| `activity_logs` | `workspace_id` | `index(workspace_id, created_at)`, `index(workspace_id, user_id)` | Keep platform-level logs nullable only if a log truly has no workspace. |
| `settings` | `workspace_id` nullable or split by namespace | `unique(workspace_id, key)` for workspace settings | Global settings and workspace settings should not share ambiguous keys. |

## Role transition design

- Keep `users.role` unchanged in v6.0.2 to avoid breaking current auth and admin screens.
- Treat `users.role` as a legacy/global role during the transition period.
- Use `workspace_members.role` to express workspace-level access.
- Later, if needed, rename `users.role` to `platform_role` in a separate migration once workspace permissions are stable.

## Unique constraints and indexes

### Current global uniqueness to preserve

- `users.username`
- `users.email`
- `users.oauth_id`

### Workspace-aware uniqueness to introduce later

- `customers`: prefer workspace-aware uniqueness for phone/email if duplicate protection is still required.
- `services`: unique service name per workspace.
- `settings`: `unique(workspace_id, key)` if the key belongs to workspace scope.

### General index guidance

- Add `workspace_id` indexes on every workspace-scoped table.
- Add compound indexes that match the most common filters and sort orders.
- Do not add destructive unique constraints until backfill validation proves data is clean.

## Migration / backfill phases

### Phase 1

- Create `workspaces`.
- Create `workspace_members`.
- Insert a default workspace, for example `Default Workspace` with slug `default`.
- Add nullable `workspace_id` columns to the workspace-scoped tables.

### Phase 2

- Backfill all existing business data into the default workspace.
- Add a membership row for the current owner in the default workspace with role `owner`.
- Add additional memberships if the current data model already implies admin/staff ownership relationships.

### Phase 3

- Add workspace-aware indexes.
- Add composite unique constraints only after duplicate audit passes.
- Verify that search, reports, export, and restore flows can resolve the correct workspace context.

### Phase 4

- Once app code has switched to workspace-scoped queries, consider making `workspace_id` non-null where appropriate.

**Guardrails**

- Do not make `workspace_id` non-null too early.
- Do not add unique constraints while duplicate legacy data still exists.
- Do not delete old data during backfill.
- Do not change `users.role` in the same migration batch.

## Workspace context strategy

- The app should carry a `current_workspace_id` in session once workspace support is implemented.
- If a user has one workspace, auto-select it.
- If a user has many workspaces, default to the active membership and add a switcher later.
- Service/query helpers should receive the workspace context from the app/session layer, not from user-supplied request fields.

## Permission strategy

- Platform role: used for platform approval/account lifecycle tasks.
- Workspace role: used for workspace owner/admin/staff permissions.
- Permission checks must validate both the authenticated user and the active workspace membership.
- Platform owner/admin should not automatically see every workspace’s business data without explicit policy.

## Testing strategy

- Default workspace is created.
- Owner membership is created.
- Existing customers/services/appointments/invoices backfill with `workspace_id`.
- Customer queries only show the current workspace.
- Statistics only aggregate the current workspace.
- Export/PDF only includes the current workspace.
- Direct ID lookups do not cross workspace boundaries.
- Activity logs store `workspace_id`.
- Settings uniqueness works per workspace where required.
- Backup center does not leak workspace data.
- Platform roles remain separate from workspace roles.

## Open questions

- Should a user be allowed to join multiple workspaces immediately in v6.0, or only later?
- Do we need a workspace switcher in v6.0, or can we auto-select the active/default workspace for now?
- Should `owner_user_id` ever exist on `workspaces`, or is membership-only ownership enough long term?
- Should global settings and workspace settings remain in one table or split later?

## Follow-up tasks

- 6.0.3 Workspace models and migration draft
- 6.0.4 Default workspace bootstrap/backfill
- 6.0.5 Workspace context middleware/session
- 6.0.6 Workspace-scoped query pass
- 6.0.7 Workspace user/member management
- 6.0.8 Workspace security regression tests
- 6.0.9 v6.0.0 checkpoint
