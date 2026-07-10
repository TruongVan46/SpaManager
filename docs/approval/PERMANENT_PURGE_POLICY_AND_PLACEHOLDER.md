# Permanent Purge Policy and Safe Placeholder

## Executive summary

SpaManager supports application-data soft-delete and restore. Application-data permanent purge is **not implemented** and runtime paths are blocked. This document is policy-ready only; implementation remains blocked.

## Current lifecycle matrix

| Lifecycle | Status |
| --- | --- |
| Soft-delete business data | Supported |
| Restore business data | Supported |
| STAFF/ADMIN soft-delete and restore | Supported |
| OWNER + Workspace soft-delete and restore | Supported |
| Account/Workspace permanent purge | Not implemented / blocked |
| Legacy business permanent-delete | Disabled in 6.5.23b (`eb8e307`) |
| Automatic business cleanup | Disabled |
| Backup artifact deletion | Separate Backup Center file lifecycle |

## Legacy history and placeholders

Business hard-delete previously existed in Recycle Bin and was disabled after discovery found active-record deletion, restore-versus-purge race, financial-history loss and non-atomic audit risk. Account/Workspace purge has never been implemented. Disabled placeholders in Approval Portal, Workspace User Management and Recycle Bin have no action URL, form action or mutation JavaScript.

## Dependency and cascade matrix

| Entity | Key dependencies | ORM/database delete behavior | Hard-delete policy |
| --- | --- | --- | --- |
| User | `approved_by_id -> users.id` (nullable, `ON DELETE SET NULL`); `deleted_by_id -> users.id` (nullable, `ON DELETE SET NULL`); `Workspace.created_by_id -> users.id`; `WorkspaceMember.user_id`, `invited_by_id`, `removed_by_id`; `ActivityLog.user_id` | User has no `workspace_id` column in the current model/schema. The actor FKs explicitly use `SET NULL`; membership FKs are confirmed below. | Blocked; retain or anonymize audit data |
| Workspace | `created_by_id -> users.id` (nullable, `SET NULL` in migration); `deleted_by_id -> users.id` (nullable, `SET NULL`); members and workspace-scoped business rows/settings | `Workspace.members` uses ORM `cascade="all, delete-orphan"`; workspace-scoped FKs are nullable and PostgreSQL migration 0003 uses `ON DELETE SET NULL` | Blocked; co-owner/shared ownership must be resolved |
| WorkspaceMember | `workspace_id -> workspaces.id` (non-null, `ON DELETE CASCADE`); `user_id -> users.id` (non-null, `ON DELETE CASCADE`); `invited_by_id` and `removed_by_id -> users.id` (nullable, `ON DELETE SET NULL`) | Lifecycle metadata is exactly `removed_at`, `removed_by_id`, and `removal_reason`; status is also present. Hard-deleting a workspace can delete members through both ORM delete-orphan and database cascade. | Blocked with workspace group purge |
| Customer / Service | `workspace_id -> workspaces.id` (nullable; PostgreSQL migration uses `SET NULL`); `Appointment`/`Invoice` references are non-null business FKs | `deleted_by` is a nullable username/string column, not a database FK. No safe purge cascade policy exists. | Blocked |
| Appointment | `customer_id -> customers.id` and `service_id -> services.id` (non-null); nullable workspace FK as above | `deleted_by` is string metadata, not a database FK. Outbound non-null references make delete order material. | Blocked |
| Invoice / InvoiceDetail | Invoice `customer_id` is non-null; InvoiceDetail `invoice_id` and `service_id` are non-null; nullable workspace FK is added by migration 0003 | `deleted_by` is string metadata, not a database FK. Invoice detail is dependent financial data. | Retain until approved financial policy |
| Setting | `workspace_id -> workspaces.id` nullable, `ON DELETE SET NULL` | SET NULL does not safely convert a tenant setting into a valid system setting: it can lose tenant ownership and create an orphan/legacy or ambiguously scoped row, with leakage or unexpected fallback risk. | Explicit retain/delete/reassign decision required |
| ActivityLog | `user_id -> users.id` nullable; `workspace_id` is added as a nullable workspace FK by migration 0003; reference IDs are plain metadata | `user_id` has no explicit `ondelete` in the current model, and the baseline does not confirm an explicit delete action. The current model does not declare `workspace_id` although migration 0003 adds it; this mismatch requires care. | Retain/anonymize, never blind-delete |

## Future policy proposals

### STAFF/ADMIN account purge

Only an APPROVAL_OWNER may request; a different authorized approver must approve after re-authentication. Require an approved retention window, no legal/audit hold, backup evidence, dry-run manifest and a PostgreSQL recovery rehearsal. Prefer anonymizing identity while retaining ActivityLog.

### OWNER-only purge

Never purge an OWNER while any owned/shared workspace, active membership or unresolved dependency exists. OWNER-only purge must not imply workspace purge and requires an explicit ownership-transfer or detachment plan.

### OWNER plus Workspace purge group

Block when a valid co-owner exists or shared ownership is unresolved. Require lifecycle event/job identity, second approval, backup/recovery proof, manifest review, locking, bounded batches and resumable execution. The delete order must be verified on PostgreSQL before production use.

### Business entity purge

Do not purge from web requests or solely by age. Require an approved retention value, restore window expiry, financial/audit hold checks, manifest, re-authentication, second approval, idempotency key and transaction boundaries. `cleanup_old_records()` and legacy methods must remain disabled.

## Data, audit and media handling

Financial invoices/details require a retention/compliance decision before any physical removal. ActivityLog should be retained and anonymized where appropriate, with actor, approver, manifest ID, counts, timestamps and backup evidence recorded atomically. Media cleanup runs only after database success and needs retry/reconciliation design.

Personal-data anonymization remains a business/compliance decision: identify fields, retention basis, reversible versus irreversible transformation and audit evidence before implementation. A possible retention period may be proposed later, but is **PENDING BUSINESS/COMPLIANCE APPROVAL** and must not be hard-coded in runtime.

## Restore, backup and approval prerequisites

No active account/workspace may be purged; no target may be purged inside its restore window; no unresolved valid co-owner or shared workspace may be purged. Each future operation requires explicit business-owner approval, destructive-action re-authentication, a separate second approver, backup evidence, recovery runbook and a successful recovery test.

The dry-run manifest must identify immutable target snapshots, dependency classification, planned action, counts, holds, backup evidence and approval state. It must use a lifecycle event ID or purge-job identifier rather than `deleted_at + deleted_by_id`.

## Execution safeguards and blockers

Future implementation requires `lifecycle_event_id` or `purge_job` schema, retention configuration, dry-run manifest, second approval, destructive-action re-authentication, locking/idempotency/retry design, media cleanup strategy, dedicated recovery runbook and PostgreSQL FK/cascade rehearsal. No large purge runs in a web request; failures fail closed and must have clear resume boundaries.

Execution must define bounded batches, transaction boundaries, concurrency locks, idempotency keys and resumable retry state. FK constraints may reject an unsafe delete order and cascades may delete dependent rows; they are not a reliable security control. Application authorization, a reviewed manifest, transaction boundaries and retention policy remain mandatory, and FK behavior must be rehearsed on PostgreSQL. Automatic age-only purge, re-enabling `cleanup_old_records()`, re-enabling legacy service methods, blind ActivityLog deletion and financial purge without approved rules are prohibited.

## PostgreSQL readiness and remaining risks

Before any production implementation, rehearse the exact FK/cascade sequence and recovery on isolated PostgreSQL. Remaining blockers include final retention, financial and personal-data decisions; ActivityLog anonymization; media retry design; co-owner resolution; job schema; approval workflow; and recovery evidence.

## Automated evidence

`tests/test_permanent_purge_placeholder.py` verifies placeholders, common purge URLs, absence of account/workspace purge services and fail-closed business entry points. `tests/test_business_permanent_delete_disabled.py` covers the legacy business route and data no-side-effect behavior.

## Conclusion

**POLICY READY / IMPLEMENTATION BLOCKED**. Soft-delete and restore are the only supported application-data lifecycle actions. Purge remains blocked pending schema, policy, approval, backup/recovery and PostgreSQL rehearsal prerequisites.
