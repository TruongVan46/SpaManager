# Version 6.6 — Task 6.6.3
# Permanent Purge Schema and Migration Proposal

## 1. Status and scope

Đây là schema/migration proposal documentation-only, dựa trên policy Owner-approved của Task 6.6.2.

- Chỉ workspace purge thuộc Phase 1.
- Account purge deferred.
- Shared user không bị purge cùng workspace.
- Group owner/account + workspace purge không thuộc Phase 1.
- Minimal synchronous no-migration path: **REJECTED**.
- Không tạo Alembic/custom migration, không sửa model/runtime và không mutate database.

## Owner-approved migration proposal decision

Decision date: **2026-07-11**  
Decision status: **OWNER APPROVED WITH REQUIRED DOCUMENTATION REVISIONS**  
Approved migration scope: **Workflow-only permanent workspace purge schema proposal**

Owner đã approve provisional revision `0007_permanent_purge_workflow` với `down_revision = 0006_user_ws_soft_delete`, gồm `workspace_purge_requests`, `purge_legal_holds`, `purge_lifecycle_events`, `workspaces.purged_at`, `workspaces.purge_request_id`, terminal workspace tombstone, workspace-specific Phase 1 workflow, account purge deferred, no backfill/no auto-scheduling, no business FK changes trong 0007, không sửa InvoiceDetail ORM/schema trong 0007, guarded downgrade và fail-closed Railway rollout.

Đây chưa phải migration file creation approval, model/runtime implementation approval, local PostgreSQL execution approval, Railway deployment approval hoặc production purge approval.

Migration file creation chỉ được **AUTHORIZED TO OPEN** sau khi Task 6.6.3 documentation được review, commit/push hoàn tất, `HEAD == origin/main`, working tree sạch và Owner xác nhận “ổn”. Hiện tại: migration file creation **NOT YET AUTHORIZED**, migration execution **NOT APPROVED**, runtime implementation **NOT APPROVED**, PostgreSQL/Railway deployment **NOT APPROVED**.

### Evidence inputs

- `docs/workspace/PERMANENT_PURGE_DEPENDENCY_POLICY_DISCOVERY.md`
- `docs/workspace/PERMANENT_PURGE_SECURITY_RETENTION_POLICY.md`
- Migration chain `migrations/versions/0001_baseline.py` through `0006_user_workspace_soft_delete.py`.

## 2. Schema and migration audit

### 2.1 Current migration chain

| Revision | Down revision | Evidence | Relevant result |
|---|---|---|---|
| `0001_baseline` | `None` | `migrations/versions/0001_baseline.py:1-18` | Creates current model tables; downgrade intentionally unsafe. |
| `0002_google_auth_approval` | `0001_baseline` | `migrations/versions/0002_google_auth_approval.py:4-8` | Adds Google/auth approval fields and user constraints. |
| `0003_workspace_foundation` | `0002_google_auth_approval` | `migrations/versions/0003_workspace_foundation.py:3-7` | Adds workspaces, members, nullable business `workspace_id` columns, FK/indexes and backfill. |
| `0004_settings_ws_key` | `0003_workspace_foundation` | `migrations/versions/0004_settings_workspace_constraint.py:25-31` | Replaces global setting uniqueness with partial workspace/system indexes. |
| `0005_member_soft_delete` | `0004_settings_ws_key` | `migrations/versions/0005_member_soft_delete.py:3-7` | Adds member removal provenance. |
| `0006_user_ws_soft_delete` | `0005_member_soft_delete` | `migrations/versions/0006_user_workspace_soft_delete.py:3-7` | Adds user/workspace soft-delete provenance. |

Current application migration head is `0006_user_ws_soft_delete`. The project uses the lightweight migration loader in `core/migration_cli.py:10-11,102-194`, which stores the current revision in `alembic_version`; this proposal uses the same revision chain convention.

### 2.2 Existing model facts

| Entity/table | Evidence | Current facts relevant to purge |
|---|---|---|
| User | `models/user.py:7-47` | Integer PK; unique username/email/oauth; approval fields; `deleted_at`, `deleted_by_id`, `deletion_reason`; actor FKs use `ON DELETE SET NULL`. |
| Workspace | `models/workspace.py:6-31` | Integer PK; unique slug; status; owner creator; soft-delete provenance; members cascade from ORM. |
| WorkspaceMember | `models/workspace.py:42-70` | Integer PK; workspace/user FKs; role/status; removed provenance; unique `(workspace_id,user_id)` and role/status indexes. |
| Customer | `models/customer.py:4-17` | Integer PK; nullable `workspace_id` FK/index; legacy string `deleted_by`. |
| Service | `models/service.py:3-16` | Integer PK; nullable `workspace_id` FK/index; legacy string `deleted_by`. |
| Appointment | `models/appointment.py:4-18` | Integer PK; customer/service FKs; nullable `workspace_id` FK/index; legacy string `deleted_by`. |
| Invoice | `models/invoice.py:4-20` | Integer PK; customer FK; nullable `workspace_id` FK/index; legacy string `deleted_by`. |
| InvoiceDetail | `models/invoice_detail.py:3-10` | Integer PK; invoice/service FKs; ORM has no `workspace_id` field although migration 0003 adds the database column. |
| Setting | `models/setting.py:5-20` | Nullable workspace FK with `ON DELETE SET NULL`; NULL means system-level; workspace/system uniqueness is managed by migration 0004. |
| ActivityLog | `models/activity_log.py:4-20` | Integer PK; nullable user/workspace FKs; workspace FK uses `ON DELETE SET NULL`; indexed created_at/module/action/severity. |

### 2.3 Existing schema conventions and compatibility

- PKs are integer autoincrement-style SQLAlchemy columns.
- Timestamps are SQLAlchemy `DateTime` values populated by `utils.timezone_utils.utc_now`; the application uses UTC-aware policy input and must not trust client timestamps.
- Status, role and action values are strings rather than database enums.
- Existing migrations branch on the SQLAlchemy dialect and use SQLite `sqlite_master` checks or PostgreSQL information schema checks. New proposal tables should use portable string status values and SQLAlchemy types.
- PostgreSQL partial indexes are used by migration 0004, but SQLite cannot be assumed to support every PostgreSQL-specific expression identically. Required correctness must be enforced by portable constraints/application validation, with optional PostgreSQL indexes documented separately.
- Existing business `workspace_id` fields are nullable and commonly use `ON DELETE SET NULL` from migration 0003. This is unsafe as the sole purge attribution mechanism.
- `InvoiceDetail.workspace_id` exists in the database migration path but is absent from `models/invoice_detail.py`; this is ORM/schema drift and must not be silently changed in this task.

## 3. Design options and recommendation

### 3.1 Purge request/lifecycle storage

#### Option A — workspace-specific table

Concept: `workspace_purge_requests` with a real `workspace_id` FK.

- Pros: enforceable Phase 1 target FK, clear workspace constraints, no premature account polymorphism.
- Cons: future account purge needs a separate table or later migration.

#### Option B — generic polymorphic table

Concept: `purge_requests(target_type, target_id)`.

- Pros: one table appears future-compatible.
- Cons: `target_id` has no enforceable FK, target integrity becomes application-only, and polymorphic target rules complicate provenance and audit.

#### Option C — generic table with nullable typed FKs

Concept: nullable `workspace_id` and `user_id` with a check that exactly one is set.

- Pros: future account support and enforceable typed FKs.
- Cons: unnecessary Phase 1 complexity, cross-target status rules, and hard-delete behavior for either target still needs separate policy.

#### Recommendation

Choose **Option A** for Phase 1. Do not add `user_id` to the first migration. Account purge remains deferred and must receive a separate policy/schema review.

### 3.2 Target FK and workspace tombstone

Evaluated alternatives:

| Alternative | Assessment |
|---|---|
| `ON DELETE RESTRICT` | Recommended for request and retained financial/audit context. Prevents root deletion while lifecycle references remain. |
| `ON DELETE SET NULL` | Rejected as the only strategy; it loses tenant context and can turn tenant settings into system settings. |
| No FK | Rejected for Phase 1; target integrity would be application-only. |
| Archive/snapshot table | Recommended if a future policy insists on root hard-delete; not created in this proposal. |
| Keep workspace tombstone row | Recommended Phase 1 outcome. A soft-deleted/archived root preserves invoice, audit and FK context. |

**Recommendation: `BLOCK ROOT HARD DELETE`.** A completed purge may dispose approved business data, but the workspace root remains a tombstone/retained attribution row while Invoice, ActivityLog, settings or external dependency policy requires it. A later hard-delete/archive strategy needs a separate Owner-approved migration.

The lifecycle record must retain at least original workspace ID, name/slug snapshot, deletion timestamp, deletion actor snapshot, lifecycle ID, manifest hash, result and row counts.

Terminal workspace slug remains reserved in Phase 1. The current workspace slug is unique and the tombstone row is retained, so slug reuse is not allowed while that row exists. `0007` does not change or release the slug and does not rekey the tombstone. Archive/rekey/slug reuse requires a separate policy and migration. Workspace name need not be unique; confirmation uses the immutable name snapshot, while slug snapshots in request/event records survive completion.

#### Terminal workspace tombstone schema

Add the following nullable columns to `workspaces`:

| Column | Type | Nullable | Default | FK / constraint | Purpose |
|---|---|---:|---|---|---|
| `purged_at` | Project `DateTime` convention | Yes | `NULL` | Index `ix_workspaces_purged_at` | Immutable terminal time marker. |
| `purge_request_id` | Same integer PK type as request table | Yes | `NULL` | FK to `workspace_purge_requests.id` with `ON DELETE RESTRICT`; unique `uq_workspaces_purge_request_id` | Binds one terminal workspace to one completed lifecycle. |

Provisional check name: `ck_workspaces_purge_terminal_consistency`.

```text
(
    purged_at IS NULL
    AND purge_request_id IS NULL
)
OR
(
    purged_at IS NOT NULL
    AND purge_request_id IS NOT NULL
    AND deleted_at IS NOT NULL
)
```

Do not add `workspace.purge_status`. The request table owns the lifecycle state; `purged_at IS NOT NULL` is the persisted terminal marker. The circular FK is created only after both tables/columns exist.

#### Restore invariant

Future runtime contract:

```text
Workspace can be restored only when:
deleted_at IS NOT NULL
AND purged_at IS NULL
AND no executing/completed lifecycle exists.
```

```text
purged_at IS NOT NULL
=> RESTORE BLOCKED
=> workspace cannot become active again
```

Future restore route/service must lock the target row or use an equivalent stale-state guard, recheck `purged_at` and lifecycle status, fail closed during `EXECUTING`, and never set `deleted_at = NULL` while `purged_at IS NOT NULL`. This is runtime/model work for a later task, not implementation in 6.6.3.

#### Workspace state semantics

| Workspace fields | Request state | Meaning | Restorable? |
|---|---|---|---:|
| `deleted_at IS NULL`, `purged_at IS NULL` | none | Active | No restore needed |
| `deleted_at IS NOT NULL`, `purged_at IS NULL` | none/requested/pending | Soft-deleted | Yes, subject to guards |
| `deleted_at IS NOT NULL`, `purged_at IS NULL` | `EXECUTING` | Purge mutation in progress | No |
| `deleted_at IS NOT NULL`, `purged_at IS NOT NULL` | `COMPLETED` | Terminal tombstone | No |
| Any inconsistent combination | any | Invalid/fail-closed | No |

`purged_at` never represents `EXECUTING`.

#### Phase 1 completion semantics

The Phase 1 semantic is **Terminal workspace tombstone with approved selective disposition**, not full physical tenant erasure.

`COMPLETED` is permitted only when one atomic transaction or verified completion protocol confirms:

1. Request remains `APPROVED`.
2. Requester differs from approver and execution trigger.
3. Retention is reached.
4. No active legal/operational hold exists.
5. Manifest version/hash still matches the approved record.
6. Every disposition in the manifest is complete.
7. No active workspace membership/access remains.
8. Workspace receives `purged_at` and `purge_request_id`.
9. Request changes to `COMPLETED`.
10. Append-only completion event is written.
11. Transaction commits successfully.

Any failure must rollback, must not set `purged_at`, must not set `COMPLETED`, and must not write a successful completion event.

Phase 1 does not guarantee physical erasure of every workspace-related row. It permanently disables restoration and access, applies approved selective dispositions, retains financial/audit dependencies and preserves the workspace row as a terminal tenant tombstone. Full erasure, PII anonymization and root hard-delete remain separate policy/migration decisions.

Terminal transaction invariant:

```text
workspace.purge_request_id == request.id
request.workspace_id == workspace.id
request.status transitions to COMPLETED
workspace.purged_at == request.completed_at
workspace.deleted_at IS NOT NULL
```

Where the implementation permits, `workspace.purged_at`, `request.completed_at` and the completion event `event_at` use the same server timestamp. FK/unique/check constraints provide database enforcement; same-target binding, lifecycle state, manifest/hold/actor checks, timestamp equality and atomic completion require application and transaction enforcement. An FK alone does not prove the two rows refer to the same target.

### 3.3 Retention deadline

Recommended fields:

- `target_deleted_at` — immutable deletion event snapshot.
- `eligible_at` — persisted server-side UTC timestamp.
- `retention_policy_version` — records the policy used for the calculation.

Persisting `eligible_at` prevents a policy change or timezone conversion from silently changing an existing request. Restore invalidates the lifecycle; a new soft-delete event creates a new lifecycle and eligibility window. An index on `(status, eligible_at)` supports safe eligibility lookup. The service must recheck `workspace.deleted_at`, provenance and legal hold before approval and mutation.

### 3.4 Status state machine

Proposed string states:

```text
REQUESTED -> PENDING_RETENTION -> PENDING_APPROVAL -> APPROVED -> EXECUTING -> COMPLETED
EXECUTING -> RETRY_PENDING -> EXECUTING
REQUESTED/PENDING_RETENTION/PENDING_APPROVAL/APPROVED -> CANCELLED
REQUESTED/PENDING_RETENTION/PENDING_APPROVAL/APPROVED -> REJECTED
PENDING_RETENTION -> EXPIRED
RETRY_PENDING -> CANCELLED
Any non-terminal pre-execution state -> BLOCKED
EXECUTING -> FAILED or COMPLETED
```

Terminal states are `COMPLETED`, `CANCELLED`, `REJECTED`, `EXPIRED` and `FAILED`. `BLOCKED` is non-terminal but non-executable; `RETRY_PENDING` is also non-terminal and is reserved for a reviewed execution retry. Only a server-side manual/reviewed retry may move `RETRY_PENDING` to `EXECUTING`; `outcome_unknown = true` blocks automatic retry and requires manual reconciliation. Every attempt writes a lifecycle event and increments `attempt_count` in the same transaction that starts it. No new lifecycle ID is created for a retry. Completed/cancelled/rejected/expired/failed/restored lifecycles cannot execute again. `BLOCKED` cannot be approved or executed and is never automatically unblocked. After a server-side recheck, it may move to `PENDING_RETENTION`, `PENDING_APPROVAL`, `CANCELLED` or `EXPIRED`; if retention is reached, the server regenerates the manifest and returns to `PENDING_APPROVAL`. Prior approval, typed confirmation and manifest hash are invalidated; hold clearance must be recomputed. `outcome_unknown = true` cannot use this unblock flow. Database checks can constrain known values; service validation must enforce transition ordering and concurrency.

### 3.5 Actor references

Proposed nullable FKs on the request row:

- `requested_by_id`;
- `approved_by_id`;
- `rejected_by_id`;
- `cancelled_by_id`;
- `execution_triggered_by_id`.

Use `ON DELETE SET NULL` only with immutable actor snapshots (`*_username_snapshot`, role/provider snapshot) so anonymization cannot erase provenance. Requester/approver and requester/execution actor inequality remain application rules; portable DB checks cannot reliably express all lifecycle-stage conditions. The Phase 1 contract requires requester and approver to be distinct Approval Owners, and requester cannot trigger execution.

`target_deleted_by_snapshot` is required and is created server-side when the request is created. It does not depend on the deletion actor FK remaining present, never changes automatically, and contains no credential, token, secret or password. A missing/legacy/system actor uses a sanitized identity such as conceptual `SYSTEM` or `LEGACY_UNKNOWN`; the exact production formatter belongs to the runtime task.

### 3.6 Legal/operational hold storage

#### Option A — fields on request

`hold_status`, `hold_reason`, `hold_source`, `hold_checked_at` are simple but duplicate state, cannot represent a hold existing before a request, and do not support multiple hold sources or release history.

#### Option B — dedicated hold table

`purge_legal_holds` can target a workspace, future account target, or lifecycle; record hold type, source/reference, reason, active/released state, placing/releasing actor and timestamps. It supports multiple holds, history, indexed active lookup and future account compatibility.

#### Recommendation

Choose **Option B**. Phase 1 requires `workspace_id` and a nullable future `user_id` only if the typed-target rule is explicitly added; otherwise keep the first table workspace-specific. Legal hold is global at workspace/account scope and must fail closed at request, approval and pre-mutation checks. No silent override or automatic break-glass.

### 3.7 Immutable dry-run manifest

| Option | Trade-off |
|---|---|
| JSONB in PostgreSQL | Good queryability and validation, but JSONB is not portable to SQLite and size/sensitive-data controls remain necessary. |
| Hash plus external artifact | Keeps DB small, but introduces availability, transactional and provider-storage gaps. |
| Normalized child tables | Strong queryability and row-level detail, but larger migration and more complex atomicity. |

#### Recommendation

For the first portable migration, store canonical UTF-8 JSON as bounded `Text` plus `manifest_hash` and `manifest_version`. Canonical serialization uses deterministic key ordering, UTF-8 and stable separators; the application excludes passwords, tokens, DB URLs and secrets. Required content includes lifecycle ID, target/provenance, generated_at, generated_by/system, row counts, disposition summary, blocker summary, `hold_check_status`, `hold_checked_at`, `hold_check_source`, `active_hold_count`, `released_hold_count` and sanitized hold references. A future PostgreSQL JSONB projection or normalized detail tables requires a separate decision.

### 3.8 Audit retention

The current `ActivityLog.workspace_id` uses `ON DELETE SET NULL` (`models/activity_log.py:14-19`). Extending that table alone would not guarantee context after a root deletion and could couple purge audit to ordinary log retention.

#### Recommendation

Add an append-only `purge_lifecycle_events` table keyed to the lifecycle request, with immutable target/workspace snapshots, event type, actor snapshots, timestamp, result/failure category, disposition summary and row counts. Keep ordinary ActivityLog intact. A retained workspace tombstone remains the primary attribution anchor; the dedicated event table preserves lifecycle evidence even if future archive policy changes. No secrets are stored.

### 3.9 Retry and idempotency

Use one request lifecycle for each workspace deletion event, enforced by unique `(workspace_id, target_deleted_at)`, plus unique `lifecycle_id` and unique `idempotency_key`. Do not add a redundant PostgreSQL partial unique index on the same pair; the full unique constraint is the correctness baseline. Supporting indexes remain `(workspace_id,status)`, `(status,eligible_at)`, `(status,retry_eligible_at)` and the event/hold indexes. Add `attempt_count`, `last_attempt_at`, `failure_code`, `retry_eligible_at` and `outcome_unknown`.

The service must reject duplicate Approval Portal submits, concurrent restore, duplicate approval and duplicate execution triggers. Unknown external cleanup state blocks automatic retry and requires manual review. Execution requires `hold_check_status = CLEAR`, a non-stale check timestamp, a matching manifest and no active hold.

### 3.10 Cancellation and restore invalidation

Persist `CANCELLED` with `cancelled_by_id`, `cancelled_by_snapshot`, `cancelled_at`, `cancellation_reason`, `invalidated_at`, `invalidated_by_restore` and the original deletion event snapshot. A restored workspace invalidates pending/approved request state. A later soft-delete creates a new lifecycle ID and cannot reuse the old request or retention calculation.

### 3.11 Invoice and retained tenant attribution

Policy is `RETAIN OR BLOCK PURGE`. Existing invoices have nullable `workspace_id`, and InvoiceDetail has database-level workspace scope from migration 0003 but no ORM field. Therefore the recommendation is:

```text
BLOCK ROOT HARD DELETE
```

Do not set invoice workspace attribution to NULL. Keep the workspace tombstone row and retain the existing FK context. If legal/accounting later approves invoice archive/anonymization, that must define an archive tenant entity or immutable snapshot before any root deletion is considered. No such archive entity is proposed for 0007.

### 3.12 Settings

Tenant settings require explicit delete/export/archive or block. System settings (`workspace_id IS NULL`) remain outside tenant purge. Because the current FK is `ON DELETE SET NULL` (`models/setting.py:15-20`), the purge service must process tenant settings explicitly and refuse unknown rows; migration 0007 should not change the existing FK until a separate compatibility analysis proves a safe replacement.

### 3.13 InvoiceDetail ORM/schema drift

Migration 0003 adds `invoice_details.workspace_id` with nullable FK/index behavior (`migrations/versions/0003_workspace_foundation.py:261-306`), while `models/invoice_detail.py:3-10` does not map it. Recommendation: do not use the unmapped column in new runtime code and continue resolving attribution through Invoice until a dedicated ORM/schema correction is approved. Do not drop or backfill that column in 0007. Drift is a migration risk and must be tested separately.

## 4. Proposed Alembic migration

### 4.1 Candidate revision

```text
Provisional revision: 0007_permanent_purge_workflow
Down revision: 0006_user_ws_soft_delete
Status: PROVISIONAL — NOT CREATED
```

### 4.2 Proposed tables overview

The detailed column-level definitions in section 4.3 are authoritative. No abbreviated competing schema is maintained here. The proposed tables are `workspace_purge_requests`, `purge_legal_holds` and `purge_lifecycle_events`; `workspaces` receives only `purged_at` and `purge_request_id` in this proposal.

### 4.3 Column-level revision

The following tables supersede the abbreviated table descriptions above. Lengths are provisional and portable; snapshots are sanitized and never contain secrets.

#### `workspace_purge_requests`

| Column | Type | Nullable | Default | FK / ON DELETE | Index/unique/check | Purpose |
|---|---|---:|---|---|---|---|
| `id` | Integer | No | identity | PK | PK | Request row identity. |
| `lifecycle_id` | String(36) | No | none | none | UNIQUE | Immutable canonical UUID lifecycle. |
| `workspace_id` | Integer | No | none | `workspaces.id RESTRICT` | index | Phase 1 target. |
| `purge_type` | String(30) | No | `workspace` | none | check/application | Typed Phase 1 workflow. |
| `status` | String(30) | No | `REQUESTED` | none | index; application state machine | Lifecycle state. |
| `target_deleted_at` | DateTime | No | none | none | part of UNIQUE `(workspace_id, target_deleted_at)` | Deletion-event binding. |
| `target_deleted_by_id` | Integer | Yes | NULL | `users.id SET NULL` | index optional | Original deletion actor reference; may later be null/anonymized. |
| `target_deleted_by_snapshot` | String(100) | No | none | none | none | Required immutable server-created deletion-actor provenance; sanitized legacy/system identity when the FK is null/anonymized. |
| `target_workspace_name` | String(150) | No | none | none | none | Target snapshot. |
| `target_workspace_slug` | String(150) | No | none | none | none | Target snapshot and confirmation context. |
| `requested_by_id` | Integer | Yes | NULL | `users.id SET NULL` | index | Request actor. |
| `requested_by_snapshot` | String(100) | No | none | none | none | Retained actor identity. |
| `requested_at` | DateTime | No | server time | none | index optional | Request timestamp. |
| `eligible_at` | DateTime | No | calculated server time | none | `(status,eligible_at)` index | Retention deadline. |
| `retention_policy_version` | String(50) | No | none | none | none | Policy snapshot. |
| `approved_by_id` | Integer | Yes | NULL | `users.id SET NULL` | index | Approval actor. |
| `approved_by_snapshot` | String(100) | Yes | NULL | none | none | Approval provenance. |
| `approved_at` | DateTime | Yes | NULL | none | none | Approval time. |
| `rejected_by_id` | Integer | Yes | NULL | `users.id SET NULL` | index | Rejection actor. |
| `rejected_by_snapshot` | String(100) | Yes | NULL | none | none | Rejection provenance. |
| `rejected_at` | DateTime | Yes | NULL | none | none | Rejection time. |
| `rejection_reason` | Text | Yes | NULL | none | sanitized | Rejection reason. |
| `cancelled_by_id` | Integer | Yes | NULL | `users.id SET NULL` | index | Cancellation actor. |
| `cancelled_by_snapshot` | String(100) | Yes | NULL | none | none | Cancellation provenance. |
| `cancelled_at` | DateTime | Yes | NULL | none | none | Cancellation time. |
| `cancellation_reason` | Text | Yes | NULL | none | sanitized | Cancellation reason. |
| `invalidated_at` | DateTime | Yes | NULL | none | none | Restore/manifest invalidation time. |
| `invalidated_by_restore` | Boolean | No | `false` | none | check boolean | Restore invalidation marker. |
| `invalidation_reason` | String(255) | Yes | NULL | none | none | Invalidation reason code. |
| `execution_triggered_by_id` | Integer | Yes | NULL | `users.id SET NULL` | index | Non-requester execution trigger. |
| `execution_trigger_snapshot` | String(100) | Yes | NULL | none | none | Execution actor provenance. |
| `execution_started_at` | DateTime | Yes | NULL | none | none | Mutation start. |
| `completed_at` | DateTime | Yes | NULL | none | check with status | Successful terminal time. |
| `failed_at` | DateTime | Yes | NULL | none | none | Failure time. |
| `failure_code` | String(80) | Yes | NULL | none | index optional | Sanitized failure category. |
| `failure_summary` | Text | Yes | NULL | none | no secret | Sanitized diagnostic summary. |
| `manifest_version` | String(50) | No | none | none | none | Approved manifest version. |
| `manifest_canonical_text` | Text | No | none | none | application size limit | Canonical UTF-8 JSON. |
| `manifest_hash` | String(64) | No | none | none | lowercase SHA-256 check | Detect manifest drift. |
| `idempotency_key` | String(150) | No | none | none | UNIQUE | Duplicate submit guard. |
| `attempt_count` | Integer | No | `0` | none | check `>= 0` | Retry count. |
| `last_attempt_at` | DateTime | Yes | NULL | none | none | Retry telemetry. |
| `retry_eligible_at` | DateTime | Yes | NULL | none | `(status,retry_eligible_at)` index | Reviewed retry time. |
| `outcome_unknown` | Boolean | No | `false` | none | check boolean | Blocks automatic retry when transaction outcome is unknown. |
| `hold_check_status` | String(30) | No | `UNKNOWN` | none | check `UNKNOWN/CLEAR/BLOCKED/UNAVAILABLE/STALE`; index | Persisted positive hold clearance state. |
| `hold_checked_at` | DateTime | Yes | NULL | none | index optional | Hold check time. |
| `hold_checked_by_id` | Integer | Yes | NULL | `users.id SET NULL` | index | Hold-check actor. |
| `hold_checked_by_snapshot` | String(100) | Yes | NULL | none | none | Hold-check provenance. |
| `hold_check_source` | String(100) | Yes | NULL | none | none | Hold-check source. |
| `created_at` | DateTime | No | server time | none | index optional | Creation time. |
| `updated_at` | DateTime | No | server time | none | none | Update time. |

Omitted target `user_id`: intentionally omitted because account purge is deferred and the recommended Phase 1 table is workspace-specific.

#### `purge_legal_holds`

| Column | Type | Nullable | Default | FK / ON DELETE | Index/unique/check | Purpose |
|---|---|---:|---|---|---|---|
| `id` | Integer | No | identity | PK | PK | Hold row identity. |
| `hold_id` | String(36) | No | canonical UUID | none | UNIQUE | Hold identity. |
| `workspace_id` | Integer | No | none | `workspaces.id RESTRICT` | `(workspace_id,status)` index | Workspace/account blocker target. |
| `hold_type` | String(50) | No | none | none | `(status,hold_type)` index | Legal/operational category. |
| `status` | String(20) | No | `ACTIVE` | none | check `ACTIVE/RELEASED`; index | Current hold state. |
| `source` | String(100) | No | none | none | none | Hold source. |
| `external_reference` | String(150) | Yes | NULL | none | optional partial unique with source | External case/reference. |
| `reason` | Text | No | none | none | sanitized | Hold reason. |
| `placed_by_id` | Integer | Yes | NULL | `users.id SET NULL` | index | Placing actor. |
| `placed_by_snapshot` | String(100) | No | none | none | none | Placing actor provenance. |
| `placed_at` | DateTime | No | server time | none | index | Hold start. |
| `released_by_id` | Integer | Yes | NULL | `users.id SET NULL` | index | Releasing actor. |
| `released_by_snapshot` | String(100) | Yes | NULL | none | none | Release provenance. |
| `released_at` | DateTime | Yes | NULL | none | none | Release time. |
| `release_reason` | Text | Yes | NULL | none | sanitized | Release reason. |
| `created_at` | DateTime | No | server time | none | none | Creation time. |
| `updated_at` | DateTime | No | server time | none | none | Update time. |

Hold rows are inserted as `ACTIVE`. A controlled release may update only the release fields once (`status = RELEASED`, `released_by_id`, `released_by_snapshot`, `released_at`, `release_reason`); after release the row is immutable and is never hard-deleted in normal runtime. `workspace_id`, `hold_type`, `source`, `external_reference`, `reason`, `placed_by_id` and `placed_at` cannot change. Multiple active holds on one workspace are allowed; all active holds must be released before a request can be `CLEAR`. SQLite correctness uses application transaction checks.

Hold placement/release audit contract: placement always writes workspace-attributed `ActivityLog` even when no purge request exists; release does the same. Logs contain only sanitized reason/reference summaries and no unrestricted legal content or secrets. When a related non-terminal request exists, placement/release additionally writes a request-bound `purge_lifecycle_events` row with event types such as `legal_hold_placed`, `legal_hold_released` or `hold_clearance_invalidated`. No lifecycle event is created without a non-null `request_id`. After any hold change, request `hold_check_status` becomes `STALE` or `BLOCKED`, approval/manifest is invalidated, and execution is prohibited until a new positive `CLEAR` result.

#### `purge_lifecycle_events`

| Column | Type | Nullable | Default | FK / ON DELETE | Index/unique/check | Purpose |
|---|---|---:|---|---|---|---|
| `id` | Integer | No | identity | PK | PK | Event row identity. |
| `request_id` | Integer | No | none | `workspace_purge_requests.id RESTRICT` | index; `(request_id,event_sequence)` UNIQUE | Request binding. |
| `lifecycle_id_snapshot` | String(36) | No | none | none | index | Immutable lifecycle evidence. |
| `workspace_id` | Integer | No | none | `workspaces.id RESTRICT` | index | Tenant attribution. |
| `workspace_name_snapshot` | String(150) | No | none | none | none | Human-readable target evidence. |
| `event_sequence` | Integer | No | next server value | none | UNIQUE per request; check `> 0` | Event ordering. |
| `event_type` | String(40) | No | none | none | index/check known values | Lifecycle event. |
| `actor_id` | Integer | Yes | NULL | `users.id SET NULL` | index | Event actor. |
| `actor_snapshot` | String(100) | No | none | none | none | Retained actor context. |
| `event_at` | DateTime | No | server time | none | index | Event time. |
| `status_before` | String(30) | Yes | NULL | none | none | State transition evidence. |
| `status_after` | String(30) | Yes | NULL | none | none | State transition evidence. |
| `reason_code` | String(80) | Yes | NULL | none | none | Sanitized reason. |
| `sanitized_summary` | Text | Yes | NULL | none | no secret | Human-readable result. |
| `metadata_canonical_text` | Text | Yes | NULL | none | application size limit | Sanitized event metadata. |
| `metadata_hash` | String(64) | Yes | NULL | none | lowercase SHA-256 check | Metadata integrity. |
| `created_at` | DateTime | No | server time | none | none | Insert time. |

`request_id` and `workspace_id` use `RESTRICT`; event rows are append-only by application contract and are not updated/deleted during normal runtime. Existing ActivityLog alone is insufficient because its actor/workspace FKs are nullable, it is not a lifecycle state ledger, it has no guaranteed sequence/immutability contract, and ordinary log retention must not erase purge evidence.

### 4.4 Indexes and constraints

- Unique `workspace_purge_requests.lifecycle_id`.
- Unique `workspace_purge_requests.idempotency_key`.
- Unique `workspace_purge_requests(workspace_id, target_deleted_at)`; this constraint supplies the supporting lookup index.
- Index `(status, eligible_at)`.
- Index `(workspace_id, status)`.
- Index `(request_id, event_at)`.
- Index `(workspace_id, event_at)`.
- Index `(workspace_id, status)` on legal holds.
- Portable status validation in service; optional PostgreSQL CHECK constraints may be added only if migration code handles SQLite safely.
- Application validation requires exactly one Phase 1 target and correct lifecycle provenance.
- Requester/approver and requester/execution actor inequality remain application rules.

#### Constraint enforcement classification

**DB-enforced:** primary/foreign keys, unique `lifecycle_id`, unique `idempotency_key`, unique `(workspace_id, target_deleted_at)`, unique nullable `workspaces.purge_request_id`, `purged_at`/`purge_request_id` consistency check, `attempt_count >= 0`, lowercase 64-character hash format where portable, event sequence uniqueness, known status/hold-status checks where portable, and `COMPLETED` requiring `completed_at` where the check remains portable.

**Application-enforced:** requester != approver, requester != execution trigger, exact status transitions, confirmation, legal-hold interpretation, manifest contents, active membership disposition, and tenant-setting classification.

**Transaction/locking-enforced:** restore-versus-execution race, duplicate execution, approval-to-execution recheck, manifest recheck, retention recheck and terminal marker plus `COMPLETED` atomicity.

One lifecycle per workspace deletion event is enforced by the portable `UNIQUE (workspace_id, target_deleted_at)` constraint. No duplicate non-unique or partial unique index is created for the same column pair unless a later measured query plan proves a separate need. Cancelled, rejected and failed requests cannot be replaced for the same `deleted_at`; restore followed by a new soft-delete creates a new timestamp and lifecycle. `idempotency_key` remains independently unique.

### 4.5 PostgreSQL-specific and SQLite behavior

- Use portable `String`, `Text`, `Boolean`, `Integer` and `DateTime` columns for the first migration.
- Do not use PostgreSQL-only JSONB in the portable baseline; `manifest_canonical_text` is canonical text with a hash.
- No PostgreSQL partial unique index duplicates `(workspace_id,target_deleted_at)`; the full unique constraint is authoritative.
- Use SQLAlchemy inspector/dialect branches already used by migrations 0003–0006.
- Do not assume SQLite can enforce every PostgreSQL CHECK/index expression identically; test service validation on both engines.

### SQLite constraint implementation gate

Migration implementation must prove SQLite-safe handling of `workspaces.purged_at`, `workspaces.purge_request_id`, FK `ON DELETE RESTRICT`, `uq_workspaces_purge_request_id` and `ck_workspaces_purge_terminal_consistency`. SQLite implementation must not silently omit the FK, UNIQUE constraint or terminal consistency CHECK merely to make the migration pass.

If SQLite requires a table rebuild, implementation must use an explicit strategy that preserves existing columns, indexes, constraints and data, then verifies FK behavior and downgrade on isolated SQLite only. No PostgreSQL connection is permitted for the SQLite test profile. If the migration framework cannot preserve the full terminal constraint contract safely, implementation must stop as `BLOCKED` rather than weakening the schema. PostgreSQL must use the real FK, unique constraint and check constraint.

### 4.6 Upgrade ordering

1. Create `workspace_purge_requests` with nullable actor FKs and all non-target metadata columns.
2. Create `purge_legal_holds`.
3. Create `purge_lifecycle_events`.
4. Add nullable `workspaces.purged_at`.
5. Add nullable `workspaces.purge_request_id`.
6. Create workspace-to-request FK with `ON DELETE RESTRICT`.
7. Add portable indexes, unique constraints and `ck_workspaces_purge_terminal_consistency`.
8. Validate existing schema prerequisites without mutating business rows.
9. Set migration revision only after all DDL succeeds.

### 4.7 Backfill ordering

No business-row backfill is recommended. Existing deleted workspaces remain deleted but receive no purge request, no schedule and no legal hold row automatically. An Approval Owner must create a new request after deployment, which captures current provenance and retention policy. Existing `invoice_details.workspace_id` drift is not cleaned in 0007.

### 4.8 Downgrade ordering

1. Refuse downgrade if any request, hold, lifecycle event, `workspaces.purged_at` or `workspaces.purge_request_id` value exists unless explicit manual approval is recorded outside this repository.
2. Drop workspace consistency check, unique/index and workspace-to-request FK.
3. Drop `workspaces.purge_request_id` and `workspaces.purged_at`.
4. Drop event indexes and `purge_lifecycle_events`.
5. Drop hold indexes and `purge_legal_holds`.
6. Drop request indexes/constraints and `workspace_purge_requests`.

This downgrade is not lossless: completed lifecycle, audit, manifest and hold records would be destroyed. Production downgrade should be blocked when rows exist; no automatic destructive downgrade is recommended. Provider backup/recovery must be confirmed before any exceptional downgrade.

## 5. Phase 1 data disposition closure

| Data group | Phase 1 recommended disposition | Reason | FK dependency | Can lifecycle complete? | Separate approval required? |
|---|---|---|---|---:|---:|
| Workspace | **RETAIN AS TERMINAL TOMBSTONE** | Prevent restore and preserve tenant attribution | Request FK and retained business FKs use tombstone | Yes, after all blockers clear | No additional for tombstone; root hard-delete needs separate policy |
| Invoice | **RETAIN** | Financial/audit retention | `invoices.workspace_id` remains linked; `customer_id` is non-null FK to Customer | Yes | Invoice deletion requires legal/accounting approval |
| InvoiceDetail | **RETAIN WITH INVOICE** | Preserve invoice/service detail | `invoice_id` and `service_id` are non-null FKs (`models/invoice_detail.py:7-8`) | Yes | Separate approval if future deletion is proposed |
| Customer referenced by retained Invoice | **RETAIN** | `Invoice.customer_id` is non-null and financial provenance must survive | `invoices.customer_id` is non-null FK (`models/invoice.py:8`) | Yes | Legal/accounting approval for deletion |
| Service referenced by retained InvoiceDetail | **RETAIN** | `InvoiceDetail.service_id` is non-null and detail provenance must survive | `invoice_details.service_id` is non-null FK (`models/invoice_detail.py:8`) | Yes | Separate approval for deletion |
| Unreferenced Customer | **RETAIN** | Phase 1 does not anonymize or hard-delete business history | Nullable workspace scope only; no cascade disposition | Yes | Separate anonymization/deletion policy |
| Unreferenced Service | **RETAIN** | Phase 1 does not anonymize or hard-delete business history | Nullable workspace scope only; InvoiceDetail references must be checked | Yes | Separate anonymization/deletion policy |
| Appointment | **RETAIN** | Preserve history | `customer_id` and `service_id` are non-null FKs (`models/appointment.py:8-9`) | Yes | Separate history/anonymization policy |
| ActivityLog | **RETAIN** | Preserve immutable audit summary and workspace attribution to tombstone | Existing `workspace_id` is nullable `ON DELETE SET NULL`; dedicated lifecycle events supplement it | Yes | Legal/audit approval for anonymization |
| WorkspaceMember | **RETAIN AS HISTORICAL / REMOVED** | Preserve membership provenance; no active access after completion | `workspace_id` and `user_id` non-null FKs; existing removed fields | Yes only when no active member remains | No shared-user purge approval in Phase 1 |
| Tenant Setting | **EXPLICIT DELETE** only when manifest identifies tenant row, it is not system-level, no hold exists and deletion completes before marker | Avoid implicit conversion to system setting | Existing `ON DELETE SET NULL` is not used as disposition | Yes if explicit disposition completes; otherwise `RETAIN/BLOCK` | Owner/legal if retention exception |
| System Setting | **OUT OF PURGE SET** | Preserve application-level configuration | `workspace_id IS NULL` means system-level (`models/setting.py:13-18`) | Yes | No tenant purge authority |
| Potential files/media | **BLOCK COMPLETION** until ownership, disposition and external cleanup outcome are proven | No complete inventory evidence yet | External dependency, not inferred from DB rows | No until manifest says `NO KNOWN MANAGED FILE RECORDS` or records complete | Separate file/provider policy |

No Phase 1 completion physically hard-deletes the workspace root. Selective business deletion is allowed only where the approved manifest proves the disposition and all retained FK dependencies remain valid.

## 6. Backfill assessment

| Question | Recommendation |
|---|---|
| Existing rows need backfill? | No request/lifecycle backfill. Preserve existing business data. |
| Create requests for deleted workspaces? | No. Wait for explicit Approval Owner request. |
| Backfill 30-day deadline? | No; calculate only for a new lifecycle. |
| Existing deleted workspaces? | Remain deleted, unscheduled and fail-closed until a new request is created. |
| Default legal hold? | No synthetic hold row; unknown/unavailable hold source blocks request/approval/execution. |
| `invoice_details.workspace_id` cleanup? | No in 0007; retain drift for separate ORM/schema decision. |
| Legacy/null rows? | Unchanged; fail-closed and quarantine in runtime workflow. |

## 7. PostgreSQL/Railway deployment safety

Railway pre-deploy may run `python -m flask --app app db upgrade`. The migration must therefore be additive and backward-compatible with the deployed code:

- create new nullable actor references and new tables before enabling any workflow;
- avoid destructive data conversion and large business-table rewrites;
- create indexes with lock/time risk reviewed; do not assume PostgreSQL `CONCURRENTLY` is available inside the project migration transaction;
- avoid JSONB/default rewrites in the portable baseline;
- do not purge during deployment;
- old application versions must start with the new unused tables present;
- migration failure must stop rollout and preserve the prior schema/data;
- rollback is code/feature rollback first, not automatic destructive downgrade.

Safe rollout order:

1. Owner approves the proposal and a concrete migration.
2. Schema migration is reviewed and rehearsed locally on PostgreSQL from `0006`.
3. Runtime code is deployed behind a fail-closed feature state.
4. SQLite isolated compatibility tests and PostgreSQL rehearsal pass.
5. Readiness and provider recovery review pass.
6. Production enablement is explicit and separate from deployment.

### Production rollback barrier

Before the first terminal purge, migration rollback may be considered only when no lifecycle, hold, event or tombstone data exists; runtime rollback must still keep the purge feature fail-closed. After any `workspaces.purged_at IS NOT NULL` or completed lifecycle exists:

- do not deploy or roll back to a runtime version that does not understand `purged_at`, `purge_request_id` and terminal restore blocking;
- disable purge entry points;
- deploy a compatibility runtime that preserves terminal guards;
- repair forward;
- never roll back to code that permits restore and never drop the workflow schema;
- use provider backup only through the approved recovery runbook.

Old application versions may start safely only before terminal purge data exists and while purge functionality remains disabled.

## 8. Test and rehearsal plan after migration approval

### Migration structure

- Verify revision `0007_permanent_purge_workflow` and down revision `0006_user_ws_soft_delete`.
- Inspect tables, columns, FK actions, indexes, uniqueness and checks.
- Verify upgrade and guarded downgrade behavior.

### SQLite isolated profile

- Create schema in an isolated SQLite database without PostgreSQL connection.
- Verify text manifest/hash, uniqueness, status/service validation and FK behavior.
- Verify no `spamanager_dev`, Railway or production URL is touched.

### PostgreSQL rehearsal

- Upgrade disposable PostgreSQL from `0006`.
- Inspect request, hold and event tables.
- Insert safe synthetic lifecycle/hold/manifest records.
- Verify requester/approver separation, restore invalidation, duplicate lifecycle/idempotency rejection and tombstone behavior.
- Verify retained audit/invoice attribution, settings handling and orphan/FK inspection.
- Rehearse downgrade only on disposable data and confirm guard when lifecycle rows exist.

### Existing data regression

- Active workspace unchanged.
- Existing soft-deleted workspace does not receive a purge request.
- ActivityLog, Invoice, InvoiceDetail and Settings remain intact.
- Legacy/null-workspace rows remain unchanged and fail closed.

### Deployment regression

- Old code starts after additive schema migration.
- Railway pre-deploy behavior is reviewed.
- No purge action is exposed before explicit enablement.
- Feature remains fail-closed on missing policy/runtime state.

These tests are a plan only and are **not run in Task 6.6.3**.

## 9. Risk register

| Risk | Severity | Evidence | Proposed mitigation | Migration blocker? |
|---|---|---|---|---|
| Target FK context lost after workspace deletion | High | Business workspace FKs are nullable/SET NULL in migration 0003 | Block root hard-delete; retain tombstone and snapshots | Yes |
| Retained invoice loses tenant attribution | High | `models/invoice.py:20`; policy retain/block | Retain workspace root or approved archive tenant before deletion | Yes |
| ActivityLog context lost | High | `models/activity_log.py:14-19` uses SET NULL | Dedicated lifecycle events plus retained tombstone | Yes |
| Actor deletion/anonymization | High | User actor FKs use SET NULL | Actor snapshots and retained lifecycle events | Yes |
| Duplicate lifecycle | High | No current purge lifecycle table | Unique lifecycle/idempotency keys and one-lifecycle-per-deletion-event validation | Yes |
| Requester equals approver | High | No DB policy table exists | Application validation plus persisted actor fields | Yes |
| Stale request after restore | High | Workspace soft-delete fields only | Immutable deletion snapshot and lifecycle invalidation | Yes |
| Legal hold bypass | High | No current hold entity | Dedicated hold table and three fail-closed checks | Yes |
| Manifest drift | High | No current manifest storage | Canonical text, hash and recheck before execution | Yes |
| JSONB/SQLite mismatch | Medium | Project supports SQLite and PostgreSQL | Portable Text manifest; engine-specific tests | No, if portable choice kept |
| Long migration lock | Medium | New indexes/tables on Railway | Additive DDL, lock review and rehearsal | Deployment gate |
| Railway pre-deploy failure | High | Pre-deploy runs `flask db upgrade` | Disposable rehearsal and additive ordering | Yes |
| Downgrade data loss | High | Baseline downgrade is unsafe | Block downgrade with lifecycle rows; backup first | Yes |
| InvoiceDetail ORM/schema drift | High | Migration 0003 adds DB column; ORM omits it | Separate correction proposal; no silent use/drop | Yes |
| Legacy/null-workspace data | High | Nullable workspace scope in migration 0003 | Quarantine and fail-closed; no automatic assignment | Yes |
| User/account future compatibility | Medium | Phase 1 workspace-specific policy | Defer account purge and avoid generic target in 0007 | No for Phase 1 |
| Generic polymorphic target integrity | High | Generic target_id has no FK | Choose workspace-specific table | Yes |
| Purged workspace restored | Critical | Workspace currently has no terminal marker | `purged_at`, request FK, DB check and future restore guard | Yes |
| COMPLETED before disposition finishes | Critical | Existing schema has no lifecycle ledger | Atomic completion contract and manifest verification | Yes |
| Tombstone mistaken for full erasure | High | Financial/audit rows are retained | Explicit Phase 1 semantic warning | Documentation gate |
| Retained Invoice references deleted Customer | Critical | `Invoice.customer_id` is non-null | Retain financial dependency closure | Yes |
| Retained InvoiceDetail references deleted Service | Critical | `InvoiceDetail.service_id` is non-null | Retain Service dependency closure | Yes |
| Active membership remains after completion | Critical | WorkspaceMember has active status | Remove/soft-delete members and recheck before marker | Yes |
| Downgrade removes terminal guard | Critical | New workspace marker would be lost | Refuse downgrade with lifecycle data | Yes |
| Circular workspace/request FK ordering | Medium | Both tables reference each other | Explicit add/drop ordering | No |
| Old code ignores `purged_at` | High | Existing runtime has no terminal guard | Migration first; runtime fail-closed before enablement | Deployment gate |
| Rollback to pre-purge-aware runtime after completed purge | Critical | Older runtime does not understand terminal marker | Runtime compatibility barrier and forward repair | Production enablement blocker |

## 10. Recommended schema decision table

| Decision ID | Recommended schema choice | Alternatives rejected/deferred | Reason | Owner decision |
|---|---|---|---|---|
| PURGE-SCHEMA-001 | Workspace-specific request table | Generic/polymorphic table deferred | Enforceable Phase 1 target | Yes |
| PURGE-SCHEMA-002 | Canonical UUID String(36) lifecycle ID | DB-specific UUID deferred | SQLite/PostgreSQL portability and immutable identity | Yes |
| PURGE-SCHEMA-003 | Retained workspace tombstone; request FK RESTRICT | SET NULL/no FK/hard-delete root deferred | Preserve invoice/audit tenant context | Yes |
| PURGE-SCHEMA-004 | String state machine plus service validation | DB enum only deferred | Existing project convention and SQLite compatibility | Yes |
| PURGE-SCHEMA-005 | Persist `eligible_at` and retention policy version | Dynamic-only clock rejected | Stable server-side eligibility and auditability | Yes |
| PURGE-SCHEMA-006 | Nullable actor FKs plus immutable snapshots | Hard FK RESTRICT to user deferred | Preserve provenance through anonymization | Yes |
| PURGE-SCHEMA-007 | Application actor separation with persisted fields | Portable DB cross-row CHECK deferred | Lifecycle-stage rules need service validation | Yes |
| PURGE-SCHEMA-008 | Dedicated workspace legal-hold table | Duplicated request fields deferred | Multiple holds, release history and future compatibility | Yes |
| PURGE-SCHEMA-009 | Canonical Text manifest | JSONB/normalized detail deferred | Portable baseline and deterministic recovery | Yes |
| PURGE-SCHEMA-010 | SHA-256 manifest hash/version | Hashless JSON rejected | Detect manifest drift without exposing secrets | Yes |
| PURGE-SCHEMA-011 | Append-only lifecycle event table | ActivityLog-only extension deferred | Retain purge context independent of ordinary logs | Yes |
| PURGE-SCHEMA-012 | Unique lifecycle/idempotency plus one-lifecycle-per-deletion-event validation | Lock-only approach rejected | Prevent duplicate submit/execution | Yes |
| PURGE-SCHEMA-013 | Terminal cancellation with restore invalidation | Reopen/reuse request rejected | New deletion event needs new lifecycle | Yes |
| PURGE-SCHEMA-014 | Retain/block invoice and preserve workspace tombstone | NULL attribution/archive entity deferred | Financial tenant context | Yes; legal/accounting too |
| PURGE-SCHEMA-015 | Explicit tenant settings disposition; keep system rows | FK SET NULL mutation deferred | Avoid tenant-to-system conversion | Yes |
| PURGE-SCHEMA-016 | Do not change InvoiceDetail ORM/schema in 0007 | Drop/map/backfill deferred | Avoid unreviewed drift change | Yes |
| PURGE-SCHEMA-017 | No backfill or auto-scheduling | Backfill existing deleted workspaces rejected | Prevent implicit destructive lifecycle creation | Yes |
| PURGE-SCHEMA-018 | Guarded, non-lossless downgrade | Automatic destructive downgrade rejected | Lifecycle/audit data must not vanish silently | Yes |
| PURGE-SCHEMA-019 | Additive Railway rollout behind fail-closed state | Production enablement during migration rejected | Recovery and old-code compatibility | Yes |
| PURGE-SCHEMA-020 | Workspace-only schema; account compatibility deferred | Generic account target deferred | Respect Phase 1 policy boundary | Yes |
| PURGE-SCHEMA-021 | Add `workspaces.purged_at` as terminal marker | Workspace-only status field deferred | Separate terminal marker from request state machine | Yes |
| PURGE-SCHEMA-022 | Add unique `workspaces.purge_request_id` FK to completed request | No binding/hard-delete root deferred | One terminal workspace per completed lifecycle | Yes |
| PURGE-SCHEMA-023 | Restore requires `deleted_at`, `purged_at IS NULL` and no executing/completed lifecycle | Restore guard only deferred | Prevent terminal workspace reactivation | Yes |
| PURGE-SCHEMA-024 | `COMPLETED` means terminal tombstone with approved selective disposition, not full erasure | Full physical erasure deferred | Exact irreversible semantics | Yes |
| PURGE-SCHEMA-025 | Retain Invoice/InvoiceDetail/Customer/Service/Appointment closure and workspace tombstone | Root hard-delete/financial archive deferred | Preserve non-null financial FKs and audit attribution | Yes; legal/accounting too |
| PURGE-SCHEMA-026 | 0007 is workflow-only schema; runtime/model guards are later | Runtime implementation in migration rejected | Separate migration readiness from runtime readiness | Yes |
| PURGE-SCHEMA-027 | One lifecycle per `(workspace_id,target_deleted_at)` | Replacement request on same deletion event rejected | Prevent lifecycle duplication | Yes |
| PURGE-SCHEMA-028 | `RETRY_PENDING` is non-terminal; `FAILED` is final; retry requires manual review | Automatic unknown-outcome retry rejected | Prevent duplicate/uncertain mutation | Yes |
| PURGE-SCHEMA-029 | Persist positive legal-hold clearance and require `CLEAR` before execution | Transient hold check rejected | Bind approval to non-stale clearance | Yes |
| PURGE-SCHEMA-030 | Same-target terminal binding and same server timestamp are transaction invariants | FK-only same-target assumption rejected | Preserve terminal provenance | Yes |
| PURGE-SCHEMA-031 | Event names are `request_id`, `event_at`, `event_sequence` with canonical indexes | Legacy aliases rejected | Avoid schema-name ambiguity | Yes |
| PURGE-SCHEMA-032 | `target_deleted_by_snapshot` is required migration field | Nullable actor FK alone rejected | Preserve deletion provenance after anonymization | Yes |
| PURGE-SCHEMA-033 | `BLOCKED` is non-terminal and non-executable, requiring full server-side re-review | Automatic unblock rejected | Permit hold/dependency resolution without lifecycle replacement | Yes |
| PURGE-SCHEMA-034 | Hold audit uses ActivityLog before request and request-bound lifecycle events after request | Lifecycle table without request cannot audit pre-request hold | Preserve both global and request provenance | Yes |
| PURGE-SCHEMA-035 | Full unique deletion-event lifecycle; no redundant partial unique index | Partial duplicate index rejected | One correctness constraint | Yes |
| PURGE-SCHEMA-036 | Runtime rollback barrier applies after terminal purge data exists | Rollback to pre-aware runtime rejected | Prevent restore/data-integrity regression | Yes |
| PURGE-SCHEMA-037 | Persist target deletion-actor snapshot server-side | FK-only provenance rejected | Preserve sanitized legacy/system identity | Yes |
| PURGE-SCHEMA-038 | Terminal workspace slug remains reserved while tombstone exists | Slug reuse/rekey deferred | Preserve old target/audit identity | Yes |
| PURGE-SCHEMA-039 | SQLite must preserve the full terminal constraint contract | Weakening FK/UNIQUE/CHECK rejected | Keep PostgreSQL/SQLite schema parity | Yes |

Owner decision record: `PURGE-SCHEMA-001` through `PURGE-SCHEMA-039` are **APPROVED** as a workflow-only proposal. “Yes” in the final column records that the decision is migration-gated; it does not authorize migration creation or execution.

## 11. Owner migration approval checklist

- Migration scope: [x] Approved [ ] Rejected [ ] Revise
- New `workspace_purge_requests` table: [x] Approved [ ] Rejected [ ] Revise
- New `purge_legal_holds` table: [x] Approved [ ] Rejected [ ] Revise
- New `purge_lifecycle_events` table: [x] Approved [ ] Rejected [ ] Revise
- Target/tombstone `ON DELETE RESTRICT` strategy: [x] Approved [ ] Rejected [ ] Revise
- Retention fields and 30-day `eligible_at`: [x] Approved [ ] Rejected [ ] Revise
- Status model and transition validation: [x] Approved [ ] Rejected [ ] Revise
- Actor FKs and required snapshots: [x] Approved [ ] Rejected [ ] Revise
- Requester/approver/execution separation: [x] Approved [ ] Rejected [ ] Revise
- Legal hold table and fail-closed checks: [x] Approved [ ] Rejected [ ] Revise
- Canonical manifest storage: [x] Approved [ ] Rejected [ ] Revise
- Manifest hash/version: [x] Approved [ ] Rejected [ ] Revise
- Append-only purge audit storage: [x] Approved [ ] Rejected [ ] Revise
- Idempotency and duplicate execution constraints: [x] Approved [ ] Rejected [ ] Revise
- Cancellation and restore invalidation: [x] Approved [ ] Rejected [ ] Revise
- Invoice retain/block and tombstone attribution: [x] Approved [ ] Rejected [ ] Revise
- Settings disposition: [x] Approved [ ] Rejected [ ] Revise
- InvoiceDetail ORM/schema drift strategy: [x] Approved [ ] Rejected [ ] Revise
- Backfill/no-auto-scheduling strategy: [x] Approved [ ] Rejected [ ] Revise
- Downgrade guard and data-loss warning: [x] Approved [ ] Rejected [ ] Revise
- Railway rollout/recovery plan: [x] Approved [ ] Rejected [ ] Revise
- Future account purge compatibility: [x] Approved [ ] Rejected [ ] Revise — account purge deferred
- Workspace terminal marker `purged_at`: [x] Approved [ ] Rejected [ ] Revise
- Workspace `purge_request_id` terminal binding: [x] Approved [ ] Rejected [ ] Revise
- No `Workspace.purge_status` column: [x] Approved [ ] Rejected [ ] Revise
- Root hard-delete blocked: [x] Approved [ ] Rejected [ ] Revise — rejected for Phase 1/deferred
- Phase 1 terminal tombstone semantics: [x] Approved [ ] Rejected [ ] Revise
- Retain Customer/Service/Appointment in Phase 1: [x] Approved [ ] Rejected [ ] Revise
- Retain Invoice/InvoiceDetail/ActivityLog: [x] Approved [ ] Rejected [ ] Revise
- Historical WorkspaceMember retention and no active access: [x] Approved [ ] Rejected [ ] Revise
- Explicit tenant Setting deletion: [x] Approved [ ] Rejected [ ] Revise
- Block completion on unresolved external files/media: [x] Approved [ ] Rejected [ ] Revise
- 0007 workflow-only schema scope: [x] Approved [ ] Rejected [ ] Revise
- Refuse destructive downgrade with lifecycle data: [x] Approved [ ] Rejected [ ] Revise
- BLOCKED non-terminal re-review semantics: [x] Approved [ ] Rejected [ ] Revise
- Hold audit before purge request via ActivityLog: [x] Approved [ ] Rejected [ ] Revise
- Request-bound hold lifecycle events: [x] Approved [ ] Rejected [ ] Revise
- One lifecycle per workspace deletion event enforced by UNIQUE (workspace_id, target_deleted_at): [x] Approved [ ] Rejected [ ] Revise
- No redundant PostgreSQL partial unique index: [x] Approved [ ] Rejected [ ] Revise
- Runtime rollback barrier after terminal purge: [x] Approved [ ] Rejected [ ] Revise
- Target deletion-actor snapshot NOT NULL: [x] Approved [ ] Rejected [ ] Revise
- Terminal workspace slug reservation: [x] Approved [ ] Rejected [ ] Revise
- SQLite full terminal constraint implementation gate: [x] Approved [ ] Rejected [ ] Revise
- `RETRY_PENDING` versus terminal `FAILED`: [x] Approved [ ] Rejected [ ] Revise
- Persisted positive legal-hold clearance: [x] Approved [ ] Rejected [ ] Revise
- Same-target terminal binding and timestamp invariant: [x] Approved [ ] Rejected [ ] Revise
- Canonical lifecycle-event column names: [x] Approved [ ] Rejected [ ] Revise

Invoice deletion: **DEFERRED — separate legal/accounting approval required.**  
Account purge schema: **DEFERRED.**  
Runtime purge implementation: **NOT APPROVED.**  
Migration execution: **NOT APPROVED.**

Không tạo approval marker. Owner approval ở checklist này là approval riêng cho migration proposal, không phải migration creation approval.

## 12. Final classification

`MIGRATION PROPOSAL APPROVED / READY FOR DOCUMENTATION CLOSURE`

Lý do:

- Có recommendation nhất quán cho workspace-specific lifecycle.
- Invoice/audit attribution được giải quyết bằng retained workspace tombstone và dedicated lifecycle events.
- Upgrade/backfill/downgrade và Railway rollout đã được mô tả.
- Owner đã approve từng schema decision, với invoice deletion, account purge, root hard-delete, runtime implementation và migration execution explicitly deferred/not approved.
- Chưa tạo migration, chưa sửa model và chưa mutate database.

Task 6.6.3 chưa DONE cho đến khi actual diff được review, commit/push hoàn tất, `HEAD == origin/main`, working tree sạch và Owner xác nhận `ổn`.

Không dùng `MIGRATION APPROVED FOR EXECUTION`, `MIGRATION CREATED`, `READY FOR RUNTIME IMPLEMENTATION` hoặc `READY FOR PRODUCTION`.

## 13. Validation and scope

Task này chỉ tạo proposal Markdown và thêm một README link. Không chạy tests, compileall, database, migration, PostgreSQL, Docker hoặc Railway.

Không sửa discovery/policy, runtime, models, repositories, routes, services, templates, tests hoặc migrations. Không tạo artifact backup/import/PDF và không sửa Excel templates.

Provisional migration remains documentation-only:

```text
0007_permanent_purge_workflow — PROVISIONAL — NOT CREATED
```

Không stage, commit hoặc push.
