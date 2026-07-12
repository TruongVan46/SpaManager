# Version 6.6 — Task 6.6.2
# Permanent Purge Security and Retention Policy

## 1. Policy status

Đây là **policy proposal**, không phải implementation, migration approval hoặc production approval.

- Task 6.6.1 đã hoàn tất dependency discovery.
- Permanent account/workspace purge hiện chưa được triển khai.
- Business permanent delete hiện fail-closed.
- Tài liệu này không cho phép production purge.
- Task 6.6.2 đã có Owner approval theo section `Owner-approved policy decision`.

Evidence nền tảng: `docs/workspace/PERMANENT_PURGE_DEPENDENCY_POLICY_DISCOVERY.md`.

## Owner-approved policy decision

Decision date: **2026-07-11**  
Decision status: **OWNER APPROVED**  
Approved profile: **Production-grade persisted permanent purge workflow**

Owner đã phê duyệt gói production-grade được đề xuất với các giới hạn Phase 1 trong tài liệu này:

- Chỉ `APPROVAL_OWNER` được submit purge request trong Phase 1.
- Requester phải khác approver và không được trigger execution.
- Minimal synchronous no-migration path bị từ chối.
- Task 6.6.3 migration proposal được authorized to open.

Đây là product/security policy approval, không phải implementation approval, production purge approval, Alembic migration approval hoặc database mutation approval.

Task 6.6.2 chưa được coi là DONE cho đến khi documentation diff được review, commit/push hoàn tất, `HEAD == origin/main`, working tree sạch và Owner xác nhận “ổn”.

## 2. Scope separation

Workspace purge và Account/User purge là hai lifecycle độc lập.

| Purge type | Candidate scope | Main blockers | Recommended phase | Separate approval required |
|---|---|---|---|---|
| Workspace purge | Một workspace đã soft-delete cùng dependency tenant được phê duyệt | Shared user/co-owner, invoice/audit retention, nullable FK | Trước account purge | Có |
| Account/User purge | Một global user sau khi mọi membership/actor/audit dependency đã resolve | Shared memberships, Approval Owner safety, audit/identity disposition | Sau workspace policy | Có |
| Group owner + workspace purge | Owner và workspace liên quan trong một policy group | Transaction boundary, provenance, financial retention | Chỉ sau khi hai policy được approve | Có |

Recommended policy:

- Nên triển khai workspace purge policy trước.
- Account purge nên defer nếu shared-user hoặc audit policy chưa đủ rõ.
- Không gộp hai operation thành một service hoặc một permission chỉ vì cùng tên “purge”.
- Group purge owner + workspace chỉ được phép khi transaction boundary, data disposition và rollback policy đã được Owner approve.

## 3. Policy principles

### APPROVED BASELINE

Các constraint sau được kế thừa từ Task 6.6.1 và không phải câu hỏi cần quyết định lại:

1. Chỉ workspace đã soft-delete mới được xem xét purge.
2. Active workspace tuyệt đối không được purge.
3. Workspace đã restore phải có soft-delete event mới trước khi đủ điều kiện lại.
4. STAFF/ADMIN thông thường không được execute permanent purge.
5. CSRF bắt buộc.
6. Server-side authorization và target resolution bắt buộc.
7. Không tin workspace ID, user ID, role, status, retention eligibility hoặc confirmation result từ client/hidden field.
8. Chống cross-workspace IDOR bắt buộc.
9. Phải có explicit irreversible warning.
10. Phải có explicit confirmation được server kiểm tra.
11. Purge transaction phải atomic; failure phải rollback toàn bộ.
12. Không chấp nhận partial purge.
13. Shared user không bị xóa chỉ vì có membership trong target workspace.
14. Không chạy production purge trước local PostgreSQL rehearsal và readiness approval.
15. Không production smoke trước readiness approval.
16. Provider backup không được coi là Web restore có thể hoàn tác từ SpaManager UI.

### RECOMMENDED POLICY

- Hai người độc lập cho production-grade purge.
- Re-authentication trước request/approval/execute theo role.
- Dry-run manifest phải được review trước mutation.
- Invoice và audit retain mặc định.
- Fail-closed khi dependency, provenance, retention hoặc legal hold chưa resolve.

### OWNER DECISION REQUIRED

- Retention duration và retention clock.
- Exact confirmation form, case sensitivity và cooldown.
- Request/approve/execute role matrix cuối cùng.
- Account anonymization, audit retention và shared-user disposition.
- Legal/accounting exceptions.

### LEGAL/ACCOUNTING DECISION REQUIRED

- Invoice/InvoiceDetail retention.
- Customer/appointment history.
- ActivityLog retention/anonymization.
- Legal hold và backup retention.

### MIGRATION-TRIGGERING CHOICE

Migration chỉ được xem xét nếu Owner chọn persisted retention deadline, legal hold, persisted requester/approver separation, immutable in-database manifest, asynchronous job, durable retry/idempotency, cancellation state hoặc audit sentinel mà schema hiện tại không biểu diễn được.

## 4. Recommended policy profile

### Workspace eligibility

- Chỉ soft-deleted workspace.
- Active workspace bị block.
- Workspace restored phải soft-delete lại và tạo event mới.
- `deleted_at` và deletion provenance phải được recheck server-side trong transaction.
- Legacy/null-workspace dependency fail-closed.
- Bất kỳ unresolved FK, shared dependency, co-owner hoặc legal hold nào đều block.
- Client không được quyết định eligibility bằng workspace ID, status hoặc timestamp.

Evidence: `models/workspace.py:26-31`, `services/workspace_service.py:169-210`, `services/user_service.py:888-1068`.

### Retention

Owner-approved product default: **30 ngày tính từ `Workspace.deleted_at`**.

Đây là product default, không phải khẳng định nghĩa vụ pháp lý; legal/operational hold vẫn có thể block vô thời hạn.

- Legal/operational hold có thể block vô thời hạn theo policy đã approve.
- Server time và persisted lifecycle event là nguồn thời gian; không dùng client timestamp.
- Restore làm invalid purge eligibility cũ.
- Soft-delete event mới tạo retention window mới.
- Nếu current schema không lưu đủ retention/request state, workflow persisted là migration-triggering choice.

### Authorization

| Role | View deleted target | Submit request | Approve request | Execute purge |
|---|---:|---:|---:|---:|
| APPROVAL_OWNER | Yes | Yes, Phase 1 Approval Portal | Yes, for another requester | Yes, as non-requester execution trigger after gates |
| Workspace OWNER | Scoped view only | No, Phase 1 | No | No |
| ADMIN | No purge authority | No | No | No |
| STAFF | No purge authority | No | No | No |

Owner-approved Phase 1 request contract:

- APPROVAL_OWNER có thể submit request trong Approval Portal khi target được resolve server-side và không vi phạm self-purge/last-owner safeguards.
- Workspace OWNER không được submit purge request trong Phase 1: workspace có thể đã soft-delete, owner có thể không còn app access và chưa có authenticated request channel an toàn cho workspace owner.
- STAFF/ADMIN không được submit, approve hoặc execute.
- Request permission không đồng nghĩa approval và không tự tạo quyền purge.
- Request target không được lấy từ current SpaManager workspace session; target phải được resolve server-side.
- Request phải bind với đúng soft-delete lifecycle event và deletion provenance.
- Requester không được tự approve nếu two-person policy được chọn.
- Approval Owner self-purge và purge Approval Owner cuối cùng: block by default; không có automatic break-glass.
- Approval Portal target lookup không phụ thuộc current SpaManager workspace session của actor.

### Two-person approval

Production-grade recommendation: dùng two-person approval.

- Approver phải là APPROVAL_OWNER, phải khác requester và phải re-authenticate.
- Approver phải review đúng manifest, retention, legal hold và confirmation evidence.
- Requester phải là APPROVAL_OWNER; một APPROVAL_OWNER khác phải approve.
- Nếu hệ thống chỉ có một Approval Owner và người đó là requester: BLOCK, không có automatic break-glass.
- Break-glass policy nếu cần là task riêng, không thiết kế trong task này.
- Persisted requester/approver state là migration-triggering nếu schema/external evidence hiện tại không đủ.

### Execution authority and actor model

- Requester không execute hoặc trigger execution.
- Approver là APPROVAL_OWNER khác requester, có thể trigger execution sau strong re-auth và gate validation.
- Human approver không tự chọn target data để delete; server-side purge service là thành phần duy nhất thực hiện database mutation.
- Human actor trigger execution phải là Approval Owner đã được server authorize.
- Server phải recheck toàn bộ eligibility, provenance, manifest và legal hold trong transaction.
- Execution không dựa vào hidden field hoặc client-submitted approval state.
- Completed, cancelled, expired hoặc restored lifecycle không được execute.
- Execution actor, requester và approver phải được audit riêng.
- Nếu requester là Approval Owner, requester không được là approver hoặc execution-trigger actor.
- Workspace OWNER không phải requester trong Phase 1; APPROVAL_OWNER approver có thể trigger server execution sau khi tất cả gates đạt.
- Persisted actor separation requires request/approval/lifecycle state and therefore likely requires migration if this production-grade policy is selected.

### Re-authentication

- Local APPROVAL_OWNER: strong re-authentication bằng cơ chế auth hợp lệ; không chỉ dựa vào session cũ.
- Google-only APPROVAL_OWNER: OAuth re-authentication hoặc provider-safe equivalent; không yêu cầu local password không tồn tại.
- Nếu provider-safe re-auth chưa khả dụng thì fail-closed.
- Session hiện tại đơn thuần không đủ nếu Owner chọn strong re-auth.
- Không lưu password/token trong policy, log hoặc database proposal.
- Google token không được lưu trong purge audit/manifest.
- Exact runtime mechanism cần implementation discovery riêng nếu source hiện tại chưa có.

### Confirmation

Approved baseline: phải có irreversible warning và explicit confirmation server-side.

Recommended profile:

- Hiển thị target workspace, owner/account và data groups dự kiến ảnh hưởng.
- Người dùng nhập chính xác workspace name hoặc confirmation phrase.
- Server-side comparison; không tin hidden confirmation status.
- Owner-approved Phase 1: nhập chính xác workspace name và confirmation phrase; comparison exact/case-sensitive.
- Separate UI cooldown không required; retention 30 ngày và two-person approval là delay/review controls chính.
- Confirmation phải được lặp lại nếu manifest thay đổi sau lần xác nhận trước.
- Double-submit/idempotency guard là bắt buộc.

### Cancellation policy

- Request có thể cancel trước execution start theo authorization policy.
- Requester hoặc Approval Owner được cancel nếu Owner phê duyệt quyền đó.
- Restore workspace tự động làm request pending invalid/cancelled.
- Request cancelled không được approve, execute hoặc reopen âm thầm.
- New soft-delete event cần lifecycle ID và retention window mới; request cũ không tái sử dụng.
- Không có cancellation sau khi transaction mutation bắt đầu.
- Cancellation phải được audit.
- Cancellation/audit state có thể làm migration bắt buộc.

### Global legal and operational hold

Legal hold là blocker cấp workspace/account, không chỉ là concern riêng của Invoice hoặc ActivityLog.

Bất kỳ unresolved hold nào liên quan đến workspace, user/account, Invoice/InvoiceDetail, ActivityLog, customer history, active investigation, accounting retention, provider recovery incident hoặc unresolved dependency đều phải:

- block request approval;
- block execution;
- fail closed.

Server phải kiểm tra hold khi tạo request, khi approve và ngay trước mutation trong transaction. Không tin hold status từ client, không có silent override; break-glass nếu cần là policy riêng.

### Purge lifecycle identity and provenance binding

Mỗi purge request production-grade có một lifecycle ID duy nhất, bind tối thiểu với:

- purge type và target workspace/user ID;
- target `deleted_at` và `deleted_by_id` hoặc provenance tương đương;
- requester và request timestamp;
- retention eligibility timestamp;
- manifest version/hash;
- approval, approver, cancellation/expiry state và final result.

Rules:

- Lifecycle ID không được reuse.
- Request của soft-delete event cũ không hợp lệ cho event mới.
- Restore làm lifecycle hiện tại invalid/cancelled.
- Target provenance mismatch phải block.
- Completed lifecycle không được execute lần hai.
- Cancelled/rejected lifecycle không được reopen âm thầm.
- Lifecycle lookup phải server-side.

Persisted lifecycle state requires migration if this production-grade policy is selected.

### Immutable dry-run dependency manifest

Manifest phải được tạo trước approval và bao gồm tối thiểu:

- lifecycle ID, target identity và soft-delete provenance;
- retention eligibility, row counts theo table/data group;
- shared-user, sole/co-owner dependencies;
- Invoice/InvoiceDetail, ActivityLog và Setting disposition;
- legacy/null-workspace findings, unresolved dependencies và legal-hold result;
- external file/media inventory status;
- planned disposition cho từng group và manifest version/hash.

Approver phải review đúng manifest được approve. Manifest thay đổi sau approval làm approval invalid. Server phải regenerate/recheck trước execution; count hoặc dependency mismatch phải block. Manifest không được chứa password, token, DB URL hoặc secret.

Immutable in-database manifest or manifest hash requires migration. An external signed artifact is an alternative only if explicitly approved.

### Retry, idempotency and duplicate execution

- Mỗi execution dùng lifecycle ID/idempotency key.
- Double submit không tạo purge thứ hai; double approval không tạo execution thứ hai.
- Completed request trả về already-completed, không chạy lại.
- Cancelled/rejected/expired request không được retry.
- Transaction failure phải rollback toàn bộ; retry chỉ được phép sau server-side dependency recheck.
- Unknown/partial external cleanup state phải block automatic retry.
- Không ghi success audit khi DB transaction rollback.
- Timeout không được mặc định coi là success hoặc tự chạy lại mù; manual review bắt buộc khi không xác định transaction outcome.

Durable retry/idempotency requires persisted lifecycle/job state and therefore migration if selected.

## 5. Data disposition policy

| Data group | Recommended disposition | Alternative | Blocking condition | Audit requirement | Migration impact |
|---|---|---|---|---|---|
| Workspace | Retain soft-deleted until retention, then reviewed group purge | Archive | Co-owner/shared/FK/legal hold | Lifecycle event and manifest | Possible job/manifest |
| WorkspaceMember | Retain or group-dispose with workspace | Soft-delete retain | Shared user or unresolved actor | Preserve membership provenance | Possible lifecycle ID |
| Shared user | Retain; anonymize only after all dependencies resolve | Controlled detach | Any active/removed/historical dependency unresolved | Preserve sentinel actor | Possible account state |
| Workspace-only user | Retain/anonymize by approved account policy | Purge after review | Owner/audit/legal dependency | Preserve identity disposition | Optional |
| Approval Owner | Retain | Restricted anonymization | Self/last Approval Owner | Preserve system actor history | Possible approval state |
| Customer | Retain by default | Approved anonymization | Financial/history dependency | Preserve reference summary | Optional |
| Service | Retain by default | Approved anonymization | InvoiceDetail dependency | Preserve service reference | Optional |
| Appointment | Retain history | Approved anonymization | Customer/service dependency | Preserve event summary | Optional |
| Invoice | RETAIN OR BLOCK PURGE | Restricted anonymization only after accounting approval | Global legal/operational hold or accounting blocker | Immutable financial audit | Possible retention fields |
| InvoiceDetail | RETAIN OR BLOCK PURGE with Invoice | Restricted anonymization with Invoice | Global hold or non-null invoice/service references | Preserve detail summary | ORM/schema correction may be needed later |
| Tenant Setting | Explicit delete/export/archive | Quarantine | Never implicit SET NULL | Log disposition | Optional |
| System Setting | Retain outside workspace purge set | Controlled update | Never include by tenant purge | Log policy decision | None expected |
| ActivityLog | Retain minimum immutable audit summary | Approved PII anonymization | Global legal/operational hold or audit blocker | Preserve actor/time/action/context | Sentinel may require schema |
| Approval metadata | Retain or sentinel anonymize | Controlled detach | Approval provenance needed | Preserve decision evidence | Optional |
| `created_by` | Retain/sentinel | SET NULL only after approval | Provenance required | Preserve creator context | Optional |
| `approved_by` | Retain/sentinel | SET NULL only after approval | Approval audit required | Preserve approval context | Optional |
| `deleted_by` | Retain/sentinel | SET NULL only after approval | Deletion provenance | Preserve deletion event | Optional |
| `invited_by` | Retain/sentinel | SET NULL only after approval | Invitation audit | Preserve membership event | Optional |
| `removed_by` | Retain/sentinel | SET NULL only after approval | Removal audit | Preserve membership event | Optional |
| Recycle Bin-visible rows | Restore or retain until approved purge | Purge after policy | Active/restored target | Log restore/purge decision | None/possible job |
| Legacy/null-workspace rows | Fail-closed, quarantine and map | Explicit archive | Unknown tenant ownership | Record quarantine | Mapping may require migration |
| Potential files/media | Inventory and establish ownership mapping before disposition | Quarantine | Ownership not proven | File manifest | File state may require schema |
| Provider/manual backups | Independent retention/expiry policy | Legal hold | Provider recovery requirement | External evidence | Outside app transaction |

### Invoice/InvoiceDetail

Không tự tuyên bố được phép xóa invoice.

Recommended default: `RETAIN OR BLOCK PURGE pending Owner/legal/accounting policy`.

- Nếu workspace bị purge nhưng invoice retained, tenant attribution phải được giữ.
- Không để `workspace_id` tự chuyển NULL thành dữ liệu global.
- Anonymization/archive strategy phải được approve riêng.
- Nếu schema không hỗ trợ strategy đã chọn, migration trở thành bắt buộc.

### ActivityLog

Recommended default: retain minimum immutable audit summary; anonymize PII chỉ theo approved policy.

- Xác định log nào tồn tại sau purge.
- Xác định actor reference và workspace attribution.
- Không để `ON DELETE SET NULL` làm mất context ngoài ý muốn.
- Sentinel/anonymized actor có thể là migration-triggering choice.
- Global legal/operational hold ở workspace/account level phải block cả request approval và execution.

### Shared users

Recommended default: block account purge while any active, removed, historical or ownership dependency remains unresolved. Không xóa shared user cùng workspace purge.
- Shared-user disposition không bao gồm dry-run manifest hoặc retry policy; các policy đó được quyết định riêng ở `PURGE-POL-020` và `PURGE-POL-021`.

### Settings

- Tenant setting không được biến thành system setting do `SET NULL`.
- Disposition phải là explicit delete/export/archive hoặc block.
- System-level setting không nằm trong workspace purge set.

### Legacy/null-workspace rows

- Fail-closed.
- Không tự gán vào target purge.
- Cần quarantine/mapping policy riêng.

### Potential files/media

Chỉ coi là potential external dependency; inventory và ownership mapping chưa được chứng minh đầy đủ. Không khẳng định có purgeable media records.

## 6. Account purge policy

Account purge không tự động đi cùng workspace purge.

Recommended account purge eligibility:

- Không còn membership unresolved.
- Không còn owner dependency.
- Không phải Approval Owner cuối cùng.
- Không còn legal/audit blocker.
- Actor references đã có disposition.
- Retention đã hết và request/provenance còn hợp lệ.

Workspace-only user không mặc định được hard-delete. Approval Owner self-purge và last Approval Owner purge bị block theo recommended policy. Username/email/oauth uniqueness và recreate behavior cần Owner quyết định. Anonymization có thể phù hợp hơn hard delete.

| Account condition | Recommended action | Purge allowed? | Required approval | Migration concern |
|---|---|---:|---|---|
| Active account | Keep active | No | None | None |
| Soft-deleted shared user | Resolve memberships/dependencies | No | Owner/legal | Possibly request state |
| Soft-deleted workspace-only user | Review identity/audit disposition | Policy-dependent | Approval Owner + second approver | Optional |
| Approval Owner | Retain/restrict | No by default | Owner/legal | Possible last-owner state |
| Last Approval Owner | Block | No by default | Explicit Owner policy | Likely approval state |
| User with legal/audit hold | Retain | No | Legal/accounting | Hold state may require migration |

## 7. Transaction and concurrency policy

Policy proposal yêu cầu:

- Atomic database transaction.
- Server-side state recheck and target row locking hoặc equivalent stale-state guard.
- No partial purge; rollback on dependency/audit failure.
- Duplicate submission and duplicate approval handling.
- Restore-versus-purge race handling.
- Lifecycle ID, idempotency key và duplicate execution guard.
- Timeout/retry policy; persisted async retry requires idempotency.
- Global legal-hold check trước request, approval và mutation.
- Success audit chỉ sau transaction success.
- File cleanup failure sau DB commit có recovery protocol riêng.
- External/provider backup nằm ngoài database transaction.

Không viết code trong task này.

## 8. Audit policy

Proposed minimum audit events:

```text
purge_requested
purge_request_cancelled
purge_approved
purge_rejected
purge_started
purge_failed
purge_completed
```

Mỗi event cần actor, target, timestamp, lifecycle ID nếu có, disposition summary, row counts, reason và failure category. Không ghi secret/token/password/DB URL.

Audit record phải sống sót sau target purge theo approved retention/anonymization policy. Nếu current schema không giữ được audit contract đã chọn, đó là migration-triggering choice.

## 9. Migration decision matrix

| Selected policy | Existing schema sufficient? | Migration required? | Proposed schema concept | Approval gate |
|---|---|---|---|---|
| Synchronous one-time minimal purge | Có thể | NO | Dùng metadata hiện có, transaction reviewed | Owner policy approval |
| Persisted retention deadline | Chưa chứng minh | Migration required if selected | Retention deadline/event | Owner + legal approval |
| Legal hold | Chưa có evidence | Migration required if selected | Hold state/reference | Legal approval |
| Two-person approval | Chưa có persisted state evidence | Migration required if selected | Requester/approver/decision | Owner approval |
| Immutable manifest | Chưa có persisted state evidence | Migration required if selected | Manifest hash/content/result | Owner approval |
| Lifecycle/job ID | Chưa có evidence | Migration required if selected | Durable lifecycle/job identifier | Owner approval |
| Async retry | Chưa có evidence | Migration required if selected | Job state/idempotency key | Owner approval |
| Purge cancellation | Chưa có evidence | Migration required if selected | Request status/cooldown | Owner approval |
| Sentinel audit actor | Chưa có evidence | Migration required if schema cannot represent it | Sentinel identity/disposition | Legal/owner approval |
| Retained workspace audit attribution | Runtime has nullable workspace FK | Policy-dependent | Preserve or sentinel workspace context | Owner/legal approval |
| Invoice retention/anonymization | Current details are indirectly resolvable | Policy-dependent | Accounting retention/disposition state | Accounting approval |
| File cleanup state | Ownership mapping incomplete | Migration required if persisted tracking selected | File ownership/cleanup status | Owner approval |

Migration mandatory for every safe minimal synchronous implementation: `NO`.

Migration requirement for a production-grade persisted workflow: `POLICY-DEPENDENT`.

## Task 6.6.4 Owner-approved implementation amendment

This amendment records the internal-only synchronous implementation boundary. It
does not authorize production execution.

### Approved disposition

- Hard-delete only target-workspace rows from `invoice_details`, `appointments`,
  `invoices`, `customers`, `services`, `settings`, and `workspace_members`.
- Preserve `users`, `activity_logs`, `workspace_purge_requests`,
  `purge_legal_holds`, `purge_lifecycle_events`, and the terminal `workspaces`
  tombstone.
- Do not delete filesystem assets from the purge transaction.
- A target workspace is blocked while any `spa_logo` setting reference is
  non-null, non-empty, malformed, or unresolved.
- User avatars, global backups, and operational logs are preserved. PDF/Excel
  response streams and import/restore temporary files are not persistent purge
  assets.

### Approved `purge-manifest-v1` contract

- `request_id` is database input only and is excluded from canonical JSON.
- `lifecycle_id` is the canonical manifest identity.
- Provenance uses `target_deleted_at` and `target_deleted_by_id` snapshots.
- Retention contains exactly `eligible_at` and `policy_version`.
- Naive persisted timestamps are interpreted as UTC; output is
  `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
- Canonical JSON uses `ensure_ascii=True`, `allow_nan=False`,
  `separators=(",", ":")`, `sort_keys=False`, UTF-8, no BOM, and no trailing
  newline.
- Row-set fingerprints use positive integer primary keys, numeric ascending
  order, LF separators without a trailing LF, and lowercase SHA-256 hex.
- Stored canonical text and hash are recomputed and compared before approval
  and execution. No silent refresh is permitted.

### Implementation boundary

- The service is internal-only and has no route, UI, worker, scheduler, or
  startup hook.
- Legal hold, authorization, retention, status, provenance, workspace, logo,
  and manifest gates fail closed.
- Existing migration `0007_permanent_purge_workflow` is sufficient; no new
  migration is created.
- Production purge execution is not authorized. Version 6.6 is not closed.

Nếu Owner phê duyệt toàn bộ recommendation production-grade gồm persisted retention, two-person approval, actor separation, global legal hold, immutable manifest, lifecycle ID, cancellation, durable retry/idempotency và retained audit identity, thì **Task 6.6.3 migration proposal becomes required before implementation**. Đây là policy consequence, không phải migration approval.

Task 6.6.3 migration proposal: **AUTHORIZED TO OPEN**.

- Alembic migration creation: **NOT APPROVED**.
- Runtime implementation: **NOT APPROVED**.
- Task 6.6.3 chỉ được đề xuất schema, dependency analysis, backfill strategy, PostgreSQL/Railway deployment risk, downgrade strategy, test/rehearsal plan và migration approval gate.
- Không tạo file trong `migrations/versions` khi chưa có Owner approval riêng.

Không tạo migration trong Task 6.6.2.

## 10. Policy decision table

| Decision ID | Proposed policy | Rationale | Owner decision | Migration consequence |
|---|---|---|---|---|
| PURGE-POL-001 | Workspace purge chỉ xét soft-deleted workspace; active/restored bị block | Prevent live/ambiguous tenant purge | APPROVED | None for guard |
| PURGE-POL-002 | Retention default 30 ngày từ `workspace.deleted_at` | Provides review/restore window | APPROVED: 30 days from Workspace.deleted_at | Deadline persistence selected |
| PURGE-POL-003 | Restore invalidates request cũ; cancelled request không reuse; soft-delete event mới cần request/retention mới | Prevent stale request race | APPROVED | Request state if persisted |
| PURGE-POL-004 | Phase 1 chỉ APPROVAL_OWNER request; requester không được approve/execute; target server-side và bind lifecycle | Separation of duties and target integrity | APPROVED WITH PHASE-1 RESTRICTION: APPROVAL_OWNER request only | Request/lifecycle state |
| PURGE-POL-005 | Approver phải là APPROVAL_OWNER khác requester, re-authenticate và review manifest/retention/legal hold/confirmation; một Approval Owner thì BLOCK | Reduces single-actor risk | APPROVED | Requester/approver state |
| PURGE-POL-006 | Requester không tự approve; self/last Approval Owner purge block | Prevent lockout and self-approval | APPROVED | Approval/last-owner state if persisted |
| PURGE-POL-007 | Strong re-auth trước destructive action; Google-only dùng OAuth/provider-safe equivalent; unavailable thì fail-closed | Reduces stale-session risk | APPROVED | Provider-specific discovery; possible auth state |
| PURGE-POL-008 | Explicit warning + exact workspace name/phrase, server-side exact/case-sensitive comparison; no separate UI cooldown; idempotency required | Prevent accidental irreversible action | APPROVED | Persisted confirmation/idempotency if selected |
| PURGE-POL-009 | Invoice/InvoiceDetail retain or block purge; deletion requires separate legal/accounting approval | Accounting/legal protection | APPROVED DEFAULT: retain or block; legal/accounting approval still required for deletion | Possible retention/hold state |
| PURGE-POL-010 | ActivityLog retain minimum immutable summary; global hold blocks request/approval/execution; anonymize PII only by policy | Preserve audit evidence | APPROVED | Sentinel/hold state if needed |
| PURGE-POL-011 | Shared user retain; workspace purge không hard-delete shared user; account purge deferred until dependencies resolve | Prevent cross-tenant identity loss | APPROVED | Account state if persisted |
| PURGE-POL-012 | Tenant settings explicit disposition; system settings excluded | Prevent NULL-to-global conversion | APPROVED | Optional |
| PURGE-POL-013 | Legacy/null-workspace rows quarantine/fail-closed | Unknown ownership | APPROVED | Mapping migration if selected |
| PURGE-POL-014 | Potential files/media block disposition until ownership mapping is proven | Ownership not proven complete | APPROVED | File state if persisted |
| PURGE-POL-015 | Local PostgreSQL rehearsal and readiness approval precede production | Recovery and parity gate | APPROVED | None; operational gate |
| PURGE-POL-016 | Workspace-first; account purge deferred until shared/audit policy clear | Lower dependency risk | APPROVED | None for minimal flow |
| PURGE-POL-017 | Requester không execute; non-requester Approval Owner approver may trigger; server-side purge service alone mutates DB; actors audited separately | Explicit execution contract | APPROVED | Actor separation/request state |
| PURGE-POL-018 | Unique lifecycle ID binds target, provenance, retention, request, manifest, approval, cancellation/expiry and result; ID never reused | Prevent stale/provenance mismatch | APPROVED | Lifecycle state required |
| PURGE-POL-019 | Global workspace/account legal and operational hold blocks request approval and execution; unresolved hold fails closed at three checks | Avoid narrow financial/audit-only hold | APPROVED | Hold state if persisted |
| PURGE-POL-020 | Immutable server-generated dry-run manifest reviewed and rechecked; changes invalidate approval | Prevent unreviewed dependency mutation | APPROVED | Manifest/hash state |
| PURGE-POL-021 | Lifecycle idempotency/retry rules prevent duplicate execution; uncertain external cleanup blocks automatic retry | Prevent duplicate/partial purge | APPROVED | Durable job/idempotency state |

Invoice deletion, legal/accounting exceptions, break-glass và provider-specific runtime mechanism vẫn cần approval/discovery riêng. Các dòng trên là policy approval, chưa phải implementation hoặc migration approval.

## 11. Owner approval checklist

### Retention

- 30-day default: [x] Approved [ ] Rejected [ ] Revise
- Clock from `workspace.deleted_at`: [x] Approved [ ] Rejected [ ] Revise
- Restore resets eligibility: [x] Approved [ ] Rejected [ ] Revise
- New soft-delete event/new retention window: [x] Approved [ ] Rejected [ ] Revise

### Authorization and two-person approval

- Workspace OWNER request permission in Phase 1: [ ] Approved [x] Rejected [ ] Revise — DEFERRED
- APPROVAL_OWNER request permission: [x] Approved [ ] Rejected [ ] Revise
- APPROVAL_OWNER approve permission: [x] Approved [ ] Rejected [ ] Revise
- Distinct requester/approver: [x] Approved [ ] Rejected [ ] Revise
- Execution actor model: [x] Approved [ ] Rejected [ ] Revise
- No break-glass when separation unavailable: [x] Approved [ ] Rejected [ ] Revise
- Two-person approval: [x] Approved [ ] Rejected [ ] Revise
- Self-approval/self-purge/last Approval Owner block: [x] Approved [ ] Rejected [ ] Revise

### Re-authentication and confirmation

- Local account re-authentication: [x] Approved [ ] Rejected [ ] Revise — exact runtime mechanism deferred
- Google-only re-authentication: [x] Approved [ ] Rejected [ ] Revise — provider-safe implementation deferred
- Fail-closed when strong re-auth is unavailable: [x] Approved [ ] Rejected [ ] Revise
- Typed target name/phrase: [x] Approved [ ] Rejected [ ] Revise
- Case-sensitive comparison: [x] Approved [ ] Rejected [ ] Revise
- Exact phrase format: [x] Approved [ ] Rejected [ ] Revise — workspace name plus confirmation phrase
- Separate UI cooldown: [ ] Approved [x] Rejected [ ] Revise — not required in Phase 1
- Re-confirmation after manifest change: [x] Approved [ ] Rejected [ ] Revise
- Double-submit/idempotency guard: [x] Approved [ ] Rejected [ ] Revise

### Data disposition

- Invoice/InvoiceDetail: [x] Approved [ ] Rejected [ ] Revise — retain or block; deletion needs legal/accounting approval
- ActivityLog: [x] Approved [ ] Rejected [ ] Revise
- Shared users: [x] Approved [ ] Rejected [ ] Revise
- Tenant Settings: [x] Approved [ ] Rejected [ ] Revise
- Legacy/null-workspace rows: [x] Approved [ ] Rejected [ ] Revise
- Potential files/media: [x] Approved [ ] Rejected [ ] Revise — disposition blocked until mapping proven
- Provider backups: [x] Approved [ ] Rejected [ ] Revise — independent retention

### Global blockers

- Legal hold: [x] Approved [ ] Rejected [ ] Revise
- Active session/job blocker: [x] Approved [ ] Rejected [ ] Revise
- Unresolved dependency blocker: [x] Approved [ ] Rejected [ ] Revise
- Sole/co-owner blocker: [x] Approved [ ] Rejected [ ] Revise
- Last Approval Owner blocker: [x] Approved [ ] Rejected [ ] Revise

### Workflow state

- Lifecycle ID and provenance binding: [x] Approved [ ] Rejected [ ] Revise
- Immutable dry-run manifest: [x] Approved [ ] Rejected [ ] Revise
- Cancellation: [x] Approved [ ] Rejected [ ] Revise
- Retry/idempotency: [x] Approved [ ] Rejected [ ] Revise
- Duplicate submission/approval handling: [x] Approved [ ] Rejected [ ] Revise
- Audit events and retained attribution: [x] Approved [ ] Rejected [ ] Revise

### Migration-triggering workflow

- Persisted request: [x] Approved [ ] Rejected [ ] Revise
- Two-person approval state: [x] Approved [ ] Rejected [ ] Revise
- Retention deadline: [x] Approved [ ] Rejected [ ] Revise
- Legal hold state: [x] Approved [ ] Rejected [ ] Revise
- Immutable manifest: [x] Approved [ ] Rejected [ ] Revise
- Lifecycle/job state: [x] Approved [ ] Rejected [ ] Revise
- Cancellation state: [x] Approved [ ] Rejected [ ] Revise
- Sentinel/anonymized audit identity: [x] Approved [ ] Rejected [ ] Revise
- Minimal synchronous path without migration: [ ] Approved [x] Rejected [ ] Revise

### Production gates

- Workspace-first implementation: [x] Approved [ ] Rejected [ ] Revise
- Account purge deferment: [x] Approved [ ] Rejected [ ] Revise
- Local PostgreSQL rehearsal: [x] Approved [ ] Rejected [ ] Revise
- Provider recovery/runbook review: [x] Approved [ ] Rejected [ ] Revise
- Readiness checklist before production: [x] Approved [ ] Rejected [ ] Revise
- Production smoke approval: [x] Approved [ ] Rejected [ ] Revise

Deferred or separately approved items: account purge implementation, invoice deletion, legal/accounting exceptions, break-glass, Workspace OWNER request permission, and provider-specific runtime mechanism.

Không tạo approval marker trong repository.

## 12. Final classification

`POLICY APPROVED / READY FOR MIGRATION PROPOSAL`

Classification này phù hợp vì:

- Production-grade persisted profile đã được Owner approve.
- Phase 1 giới hạn request trong Approval Portal cho APPROVAL_OWNER và bắt buộc tách requester/approver.
- Minimal synchronous no-migration path đã bị reject.
- Migration-triggering choices và Task 6.6.3 authorization đã được chỉ rõ.
- Chưa có schema implementation hoặc migration approval.

Đây không phải `DONE`, `READY FOR IMPLEMENTATION`, `MIGRATION APPROVED` hoặc `PURGE APPROVED FOR PRODUCTION`.

## 13. Validation and scope

Task này chỉ cập nhật policy Markdown. README link đã tồn tại và không sửa trong revision này. Không chạy canonical tests hoặc compileall vì không có runtime change và suite có side effect rewrite protected Excel templates.

Không chạy database, migration, PostgreSQL, Docker hoặc Railway. Không sửa tests, runtime, models, routes, services hoặc migrations.

Expected files:

```text
docs/workspace/PERMANENT_PURGE_SECURITY_RETENTION_POLICY.md
docs/workspace/README.md
```

Không stage, commit hoặc push.
