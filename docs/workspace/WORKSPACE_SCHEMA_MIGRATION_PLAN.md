# Workspace Schema Migration Plan

## Migration file

- **File:** `migrations/versions/0003_workspace_foundation.py`
- **Revision:** `0003_workspace_foundation`
- **Down revision:** `0002_google_auth_approval`
- **Message:** Workspace foundation tables and nullable workspace scope columns

---

## Tables created

### `workspaces`

| Column | Type | Nullable | Notes |
| :--- | :--- | :--- | :--- |
| `id` | SERIAL PK | No | |
| `name` | VARCHAR(150) | No | Human-readable spa name |
| `slug` | VARCHAR(150) | No, UNIQUE | URL-safe identifier |
| `status` | VARCHAR(20) | No, default `active` | `active`, `pending`, `suspended`, `archived` |
| `created_by_id` | INTEGER FK -> users | Yes | Audit trail |
| `notes` | TEXT | Yes | Admin notes |
| `created_at` | TIMESTAMP | No | |
| `updated_at` | TIMESTAMP | No | |

Indexes: `ix_workspaces_slug`, `ix_workspaces_status`, `ix_workspaces_created_at`, `ix_workspaces_created_by_id`.

### `workspace_members`

| Column | Type | Nullable | Notes |
| :--- | :--- | :--- | :--- |
| `id` | SERIAL PK | No | |
| `workspace_id` | INTEGER FK -> workspaces | No | |
| `user_id` | INTEGER FK -> users | No | |
| `role` | VARCHAR(20) | No, default `staff` | `owner`, `admin`, `staff` |
| `status` | VARCHAR(20) | No, default `active` | `active`, `invited`, `disabled` |
| `invited_by_id` | INTEGER FK -> users | Yes | Optional inviter |
| `joined_at` | TIMESTAMP | Yes | Set on activation |
| `created_at` | TIMESTAMP | No | |
| `updated_at` | TIMESTAMP | No | |

Constraints: `uq_workspace_members_workspace_user UNIQUE(workspace_id, user_id)`.
Indexes: `ix_workspace_members_workspace_id`, `ix_workspace_members_user_id`, `ix_workspace_members_workspace_role`, `ix_workspace_members_workspace_status`.

---

## Columns added (nullable phase 1)

`workspace_id INTEGER NULL REFERENCES workspaces(id) ON DELETE SET NULL` added to:

| Table | Index created |
| :--- | :--- |
| `customers` | `ix_customers_workspace_id` |
| `services` | `ix_services_workspace_id` |
| `appointments` | `ix_appointments_workspace_id` |
| `invoices` | `ix_invoices_workspace_id` |
| `invoice_details` | `ix_invoice_details_workspace_id` |
| `activity_logs` | `ix_activity_logs_workspace_id` |
| `settings` | `ix_settings_workspace_id` |

**`users` intentionally excluded** — workspace membership is tracked via `workspace_members` table (Option B).

---

## Nullable phase explanation

`workspace_id` is `NULL`-able in this first phase for the following reasons:

1. Existing production data was created before workspace isolation existed. Making the column `NOT NULL` immediately would require a complete backfill before the migration could be applied safely.
2. Application code has not yet been updated to supply `workspace_id` on every write (that is Task 6.5.5). If the column were `NOT NULL`, every existing create/update path would fail.
3. Once Task 6.5.5 enforces workspace context on all writes and production data has been verified, a follow-up migration can tighten `workspace_id` to `NOT NULL` on each table.

---

## Backfill / Default Workspace

The migration creates one **Default Spa** workspace (`slug = 'default-spa'`) if it does not yet exist, and:

- assigns `created_by_id` to the first active `OWNER` user.
- backfills `workspace_id = 1` on all existing rows where `workspace_id IS NULL`.
- inserts a `workspace_members` row for every active user, mapping global roles `OWNER → owner`, `ADMIN → admin`, `STAFF → staff`, using `ON CONFLICT DO NOTHING` for idempotency.

### Local validation result

| Check | Status |
| :--- | :--- |
| `flask db upgrade` applied | PASS |
| `flask db current` = `0003_workspace_foundation` | PASS |
| `workspaces` table present | PASS |
| `workspace_members` table present | PASS |
| `workspace_id` column on `customers` | PASS |
| `workspace_id` column on `services` | PASS |
| `workspace_id` column on `appointments` | PASS |
| `workspace_id` column on `invoices` | PASS |
| `workspace_id` column on `invoice_details` | PASS |
| `workspace_id` column on `activity_logs` | PASS |
| `workspace_id` column on `settings` | PASS |
| Default Spa workspace row created | PASS — id=1, slug=`default-spa` |
| Owner membership created | PASS — user_id=1, role=owner |
| NULL `workspace_id` rows on customers | 0 |
| NULL `workspace_id` rows on services | 0 |
| NULL `workspace_id` rows on appointments | 0 |
| NULL `workspace_id` rows on invoices | 0 |

---

## Production migration status

**NOT RUN.**

Production migration will be handled as a separate controlled approval task after application code for workspace isolation is complete and a production backup and approval runbook exists.

---

## SQLAlchemy model changes

The following models were updated to declare `workspace_id`:

- `models/customer.py` — `Customer.workspace_id` (`nullable=True`)
- `models/service.py` — `Service.workspace_id` (`nullable=True`)
- `models/appointment.py` — `Appointment.workspace_id` (`nullable=True`)
- `models/invoice.py` — `Invoice.workspace_id` (`nullable=True`)
- `models/workspace.py` — `Workspace` and `WorkspaceMember` models (already existed, unchanged in this task)

---

## Google approval behavior

**Not changed in this task.** Approving a Google user still only sets `approval_status = active` and `is_active = True`. Auto-creation of a workspace for new spa owners is deferred to Task 6.5.3.

---

## Next tasks

| Task | Scope |
| :--- | :--- |
| **6.5.3** Auto-create workspace on approval | When `UserService.approve_pending_user` is called, automatically create a new `Workspace` and assign the approved user as `owner` in `workspace_members`. |
| **6.5.4** Current workspace context | Add `current_workspace_id` to Flask session on login; provide a `get_current_workspace()` helper accessible to routes and services. |
| **6.5.5** Data isolation for CRUD | Update all customer, service, appointment, invoice, statistics, and activity log queries to filter by `current_workspace_id`. |
| **6.5.6** Staff/manager creation inside workspace | Ensure that when an `OWNER` or `ADMIN` creates a new user, the new user is automatically enrolled as a `workspace_member` of the creator's workspace. |
| **6.5.7** Workspace isolation tests and production readiness | Write integration tests that verify cross-workspace data leakage is impossible; perform final readiness review. |
| **6.5.8** Production migration approval / runbook | Execute controlled production migration following the approval runbook, including a Railway backup checkpoint and verification window. |

---

## Downgrade behavior

The `downgrade()` function:

1. Drops `workspace_id` index and column from each scoped business table if they exist.
2. Drops `workspace_members` table and its indexes.
3. Drops `workspaces` table and its indexes.

All drops use `IF EXISTS` or `_has_*` guards so the downgrade is safe even if a partial upgrade left the schema in an intermediate state.

> [!WARNING]
> Running `downgrade` in production would destroy all workspace assignments and the Default Spa row. Only use `downgrade` in development/staging environments.
