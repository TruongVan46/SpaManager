# Task 6.6.1 — Permanent Workspace/Account Purge Dependency & Policy Discovery

## 1. Scope and status

Đây là documentation-only discovery. Không triển khai purge, không sửa runtime/model/route/service/test/migration, không chạy migration/database/PostgreSQL/Railway và không tạo backup.

Permanent account/workspace purge chưa được triển khai. Business permanent delete đang fail-closed. Tài liệu này chỉ cung cấp evidence và policy questions cho coordinator.

## 2. Evidence baseline

- `migrations/versions/0001_baseline.py:1-2`: revision `0001_baseline`, không có down revision.
- `migrations/versions/0002_google_auth_approval.py:4-5, 77`: approval migration; `users.approved_by_id` dùng `ON DELETE SET NULL` trên PostgreSQL.
- `migrations/versions/0003_workspace_foundation.py:149-157`: tạo workspace/member, thêm scope và backfill.
- `migrations/versions/0003_workspace_foundation.py:217-230`: member workspace/user non-null, DB `ON DELETE CASCADE`; actor FKs dùng `SET NULL`.
- `migrations/versions/0003_workspace_foundation.py:261-307`: thêm nullable `workspace_id` cho bảy bảng và index; PostgreSQL dùng `ON DELETE SET NULL`.
- `migrations/versions/0003_workspace_foundation.py:311-380`: tạo default workspace, backfill business rows và active memberships.
- `migrations/versions/0004_settings_workspace_constraint.py:129-198`: settings uniqueness theo workspace và system-level NULL.
- `migrations/versions/0005_member_soft_delete.py:61-103`: thêm `removed_at`, `removed_by_id`, `removal_reason`.
- `migrations/versions/0006_user_workspace_soft_delete.py:61-145`: thêm soft-delete fields cho `users` và `workspaces`; actor FK PostgreSQL dùng `SET NULL`.

### 2.1 Evidence corrections

Runtime hiện tại có `ActivityLog.workspace_id` tại `models/activity_log.py:14-19`, service scope trực tiếp tại `services/activity_log_service.py:162-193`, và migration thêm cột tại `migrations/versions/0003_workspace_foundation.py:261-307`. Các tài liệu cũ như `docs/approval/ACCOUNT_WORKSPACE_SOFT_DELETE_LIFECYCLE_PLAN.md:72-73, 170-174` còn ghi cột chưa có; đó là stale planning documentation.

Migration 0003 thêm `invoice_details.workspace_id`, nhưng `models/invoice_detail.py:3-15` không map cột này. Đây là unmapped database column. Query hiện tại vẫn resolve tenant gián tiếp qua Invoice/Service; mismatch chưa tự chứng minh runtime bug hoặc migration blocker.

`users.workspace_id` không tồn tại. `git grep -n "workspace_id" -- models/user.py migrations/versions` không trả về `User.workspace_id` hoặc `users.workspace_id`; các kết quả liên quan là workspace/member và business-scope references. Vì vậy không có FK, nullable/ondelete behavior hay runtime use nào để thêm vào dependency matrix. User tenant relationship hiện được resolve qua `WorkspaceMember.workspace_id`; field này không được dùng làm bằng chứng duy nhất về tenant ownership trong multi-workspace.

## 3. Current lifecycle inventory

### 3.1 Account/User lifecycle

- Approve/create owner workspace: `services/workspace_service.py:35-99`.
- Soft-delete STAFF/ADMIN account: `services/user_service.py:799-839`; chỉ `APPROVAL_OWNER`, set `deleted_at`, `deleted_by_id`, `deletion_reason`, `is_active=False`, log và commit.
- Restore STAFF/ADMIN: `services/user_service.py:842-884`; clear soft-delete fields, chỉ bật active khi approval status active.
- `User.can_access_app`: `models/user.py:65-71`; yêu cầu active, approval active và chưa deleted.
- Approval Portal routes: `routes/approval.py:131-220`; chỉ soft-delete/restore, không có purge route.

### 3.2 Owner and workspace lifecycle

- Soft-delete OWNER/workspace: `services/user_service.py:888-979`; target phải là OWNER, workspace sole-owner bị soft-delete, co-owner hợp lệ giữ active.
- Co-owner check: `services/user_service.py:919-952`; member owner active, User role OWNER, chưa deleted, active và approval active.
- Restore provenance: `services/user_service.py:982-1068`; chỉ restore workspace khi `deleted_at` và `deleted_by_id` khớp owner event tại `1026-1039`.
- Không đổi hàng loạt `WorkspaceMember.status` và không cascade soft-delete business rows.

### 3.3 Workspace membership lifecycle

- Remove/restore staff membership: `services/user_service.py:677-796`; chỉ thay đổi membership state, không đổi global `User.is_active`.
- Membership model: `models/workspace.py:42-70`; unique `(workspace_id,user_id)`, workspace/user non-null, actor fields nullable.
- Workspace guard: `services/workspace_service.py:169-210, 224-251, 333-374`; deleted workspace bị clear session và fail-closed.

### 3.4 Recycle Bin and business-data lifecycle

- Recycle Bin listing dùng scoped query: `services/recycle_bin_service.py:55-113`.
- Restore route: `routes/recycle_bin.py:46-65`.
- `cleanup_old_records()` fail-closed, không query/delete/commit: `services/recycle_bin_service.py:115-118`.
- Business permanent delete disabled: `docs/approval/BUSINESS_PERMANENT_DELETE_DISABLEMENT.md:19-45`; tests tại `tests/test_business_permanent_delete_disabled.py:166-278`.
- Account/workspace placeholder chỉ là test guard: `tests/test_permanent_purge_placeholder.py:56-66, 202-217`.

## 4. Lifecycle operation matrix

| Operation | UI/route | Service/function | Model/repository | Authorization | State guard | Audit behavior |
|---|---|---|---|---|---|---|
| Approve account | Approval Portal POST approve | `UserService.approve_user` | User, WorkspaceService | APPROVAL_OWNER | Pending/eligible target | Approval action log |
| Soft-delete STAFF/ADMIN account | `POST /approval/users/<id>/soft-delete` | `UserService.soft_delete_account` | User, ActivityLog | APPROVAL_OWNER | Không self/approval owner/owner; chưa deleted | Success log trong transaction |
| Restore STAFF/ADMIN account | `POST /approval/users/<id>/restore` | `UserService.restore_account` | User, ActivityLog | APPROVAL_OWNER | Phải soft-deleted; active chỉ khi approval active | Success log trong transaction |
| Remove workspace membership | User management POST | `UserService.soft_delete_user` | WorkspaceMember, ActivityLog | Workspace OWNER | STAFF/ADMIN active member; không global delete | Membership action log |
| Restore workspace membership | User management POST | `UserService.restore_user` | WorkspaceMember, ActivityLog | Workspace OWNER | Removed member và workspace active | Membership action log |
| Soft-delete OWNER/workspace | `POST /approval/users/<id>/soft-delete-owner-workspace` | `UserService.soft_delete_owner_workspace` | User, Workspace, WorkspaceMember, ActivityLog | APPROVAL_OWNER | Target OWNER; co-owner giữ workspace active | Owner/workspace action log |
| Restore OWNER/workspace | `POST /approval/users/<id>/restore-owner-workspace` | `UserService.restore_owner_workspace` | User, Workspace, WorkspaceMember, ActivityLog | APPROVAL_OWNER | Owner deleted; provenance phải khớp | Restore log nêu workspace skipped/restored |
| View deleted users/workspaces | Approval Portal deleted view | `UserService.list_approval_accounts` | User/Workspace queries | APPROVAL_OWNER | Deleted filters | Read-only |
| Restore business entity | `POST /recycle-bin/restore/...` | Registry restore callbacks | Customer/Service/Appointment/Invoice | Recycle permission + actor | Soft-deleted scoped row | Restore log từ service |
| Attempt business permanent delete | Legacy URL không còn route; service methods giữ fail-closed | `permanent_delete*`, `cleanup_old_records` | Business models | Không được phép | Luôn blocked trước mutation | Không success log |
| Permanent account purge | Không có route/UI/service | NOT IMPLEMENTED | Chưa có purge repository | Chưa quyết định | Không có runtime state guard | Chưa có audit contract |
| Permanent workspace purge | Không có route/UI/service | NOT IMPLEMENTED | Chưa có purge repository | Chưa quyết định | Không có runtime state guard | Chưa có audit contract |

Hai operation permanent purge ở trên là `NOT IMPLEMENTED`, không suy đoán route/service không tồn tại thành feature.

## Approved non-negotiable purge constraints

Đây là approved baseline safety constraints, không phải policy questions cần Owner quyết định lại:

- Chỉ workspace đã soft-delete mới đủ điều kiện được xem xét purge.
- Active workspace không bao giờ được purge.
- Restored workspace phải có một soft-delete event mới trước khi đủ điều kiện lại.
- STAFF/ADMIN thường không được execute permanent purge.
- CSRF bắt buộc.
- Server-side authorization và target resolution bắt buộc.
- Không tin workspace ID, role, status hoặc eligibility từ client/hidden field.
- Chống cross-workspace IDOR bắt buộc.
- Phải hiển thị explicit irreversible warning trước khi submit.
- Phải có explicit confirmation được kiểm tra phía server; exact confirmation mechanism là policy decision.
- Purge transaction phải atomic.
- Failure phải rollback; không chấp nhận partial purge.
- Không chạy production purge trước local PostgreSQL rehearsal và readiness approval.

## 5. Database dependency matrix

| Table/model | FK column | References | Nullable | DB ON DELETE | ORM relationship/cascade | Workspace resolution | Shared/global possibility | Purge concern | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| workspaces | created_by_id | users.id | Yes | PG SET NULL | `created_by`; no cascade declared | Root tenant | Creator may be outside active tenant | Preserve creator provenance | `models/workspace.py:13,24`; `0003:173-181` |
| workspaces | deleted_by_id | users.id | Yes | SET NULL | `deleted_by`; no cascade declared | Root tenant | Actor may be purged later | Retain/anonymize actor policy | `models/workspace.py:28-31`; `0006:119-145` |
| workspace_members | workspace_id | workspaces.id | No | CASCADE | `Workspace.members` `all, delete-orphan` | Direct workspace | User may have other memberships | Workspace delete can remove members | `models/workspace.py:18-23,46`; `0003:220-230` |
| workspace_members | user_id | users.id | No | CASCADE | `user`; no member delete cascade declared | Direct membership | User shared across workspaces | Account delete can remove memberships | `models/workspace.py:47,59`; `0003:222-224` |
| workspace_members | invited_by_id | users.id | Yes | SET NULL | `invited_by`; no cascade | Membership workspace | Actor can be shared | Preserve invitation history | `models/workspace.py:50,60`; `0003:226` |
| workspace_members | removed_by_id | users.id | Yes | SET NULL | `removed_by`; no cascade | Membership workspace | Actor can be shared | Preserve removal provenance | `models/workspace.py:53,61`; `0005:76-101` |
| users | approved_by_id | users.id | Yes | SET NULL | No relationship declared for this FK | Global account | Approval actor is shared | Audit/approval provenance | `models/user.py:29`; `0002:77` |
| users | deleted_by_id | users.id | Yes | SET NULL | `deleted_by`; no cascade | Global account | Deletion actor is shared | Anonymize/retain actor decision | `models/user.py:44-47`; `0006:78-93` |
| customers | workspace_id | workspaces.id | Yes | PG SET NULL; SQLite FK without action | No ORM relationship/cascade | Direct nullable scope | NULL legacy/global possibility | Detach can leak tenant attribution | `models/customer.py:17`; `0003:267-307` |
| services | workspace_id | workspaces.id | Yes | PG SET NULL; SQLite FK without action | No ORM relationship/cascade | Direct nullable scope | NULL legacy/global possibility | Service referenced by details | `models/service.py:16`; `0003:267-307` |
| appointments | workspace_id | workspaces.id | Yes | PG SET NULL; SQLite FK without action | No ORM delete cascade | Direct nullable scope | Legacy NULL rows | Must preserve customer/service history | `models/appointment.py:18`; `0003:267-307` |
| appointments | customer_id | customers.id | No | Not declared in model/migration evidence | `customer` backref; no delete cascade | Via appointment workspace | Customer may be shared only by data quality | Delete order/FK block | `models/appointment.py:8,20` |
| appointments | service_id | services.id | No | Not declared in model/migration evidence | `service` backref; no delete cascade | Via appointment workspace | Service may be used by many invoices | Delete order/FK block | `models/appointment.py:9,21` |
| invoices | workspace_id | workspaces.id | Yes | PG SET NULL; SQLite FK without action | No ORM relationship/cascade | Direct nullable scope | NULL legacy/global possibility | Financial tenant attribution | `models/invoice.py:20`; `0003:267-307` |
| invoices | customer_id | customers.id | No | Not declared in model/migration evidence | `customer` backref; no delete cascade | Via invoice workspace | Customer may have many invoices | Financial history must retain/block | `models/invoice.py:8,22` |
| invoice_details | workspace_id | workspaces.id | Yes | PG SET NULL; SQLite FK without action | ORM does not map this column | Direct DB scope, runtime indirect | NULL legacy/global possibility | Must resolve through invoice policy | `0003:267-307`; `models/invoice_detail.py:3-15` |
| invoice_details | invoice_id | invoices.id | No | Not declared in model/migration evidence | `Invoice.details`; no delete-orphan | Via Invoice.workspace_id | Invoice is financial shared dependency | Delete detail only with invoice policy | `models/invoice.py:23`; `models/invoice_detail.py:7` |
| invoice_details | service_id | services.id | No | Not declared in model/migration evidence | `service` backref; no delete cascade | Via Invoice/Service joins | Service used by many details | Service purge must retain/block | `models/invoice_detail.py:8,12` |
| settings | workspace_id | workspaces.id | Yes | SET NULL | No ORM relationship/cascade | NULL means system-level | Tenant/system ambiguity | Never detach implicitly | `models/setting.py:13-20`; `0004:129-198` |
| activity_logs | workspace_id | workspaces.id | Yes | PG SET NULL; SQLite FK without action | No ORM workspace relationship | Direct runtime scope | System log may be NULL | Retain/anonymize audit | `models/activity_log.py:14-19`; `0003:267-307` |
| activity_logs | user_id | users.id | Yes | Not declared in model/migration evidence | `user`; no cascade | Workspace plus actor | Actor may be shared | Preserve audit reference | `models/activity_log.py:13,21` |

For every FK without an explicit action in the inspected model/migration, this document records `not declared`; it does not infer cascade or SET NULL. PostgreSQL and SQLite differences are explicitly recorded above.

## 6. Five distinct user operations

| Operation | Scope | Reversible | Membership impact | Identity impact | Typical authorization |
|---|---|---|---|---|---|
| Remove membership | One workspace | Có thể restore | Chỉ membership | Không xóa identity | Workspace management policy |
| Soft-delete user | Global account state | Có thể restore | Có thể còn membership | Giữ identity | Approval Portal |
| Permanent purge user | Global/destructive | Không | Phải resolve mọi membership | Xóa hoặc disposition identity | Chưa quyết định |
| Anonymize user | Theo policy | Thường không hoàn nguyên đầy đủ | Có thể preserve FK | Thay PII bằng sentinel | Chưa quyết định |
| Detach actor reference | Một FK cụ thể | Phụ thuộc policy | Không nhất thiết đổi membership | Có thể mất provenance | Chưa quyết định |

Các operation này không thay thế cho nhau.

## 7. Data disposition matrix

| Data type | Current relationship | Available dispositions | Main risks | Recommendation | Owner decision required | Possible migration impact |
|---|---|---|---|---|---|---|
| Workspace | Root tenant, members/business depend | Retain, group purge, archive | Cascade/orphan/tenant loss | Retain until policy | Owner/legal/accounting policy required | Job/manifest may require schema |
| WorkspaceMember | Non-null workspace/user | Retain, soft-delete, group delete | Shared user access loss | Retain or explicit group policy | Owner policy required | Possibly lifecycle ID |
| Shared user | Many memberships/actors | Retain, anonymize, detach references | Cross-tenant deletion | Block purge until all dependencies resolve | Owner policy required | Possibly request state |
| Workspace-only user | One membership | Retain, anonymize, purge | Audit/unique identity loss | Case-by-case | Owner policy required | Optional |
| Approval Owner | System actor | Retain, restricted anonymization | Lockout/provenance loss | Do not purge by default | Owner/legal policy required | Two-person state may need schema |
| Customer | Workspace-scoped, parent references | Retain, anonymize, delete | History/FK loss | Retain by default | Owner/accounting policy required | Optional |
| Service | Workspace-scoped, referenced by details | Retain, anonymize, delete | Financial references | Retain by default | Owner/accounting policy required | Optional |
| Appointment | Customer/service references | Retain, anonymize, delete | Historical loss | Retain by default | Owner policy required | Optional |
| Invoice | Financial, customer/detail references | Retain, restricted anonymization, delete | Accounting/legal loss | Retain; legal hold blocks | Owner/legal/accounting policy required | Possibly retention fields |
| InvoiceDetail | Financial child, ORM unmapped workspace column | Retain, restricted anonymization, delete with invoice | Orphan/financial loss | Follow Invoice policy | Owner/accounting policy required | ORM correction may be needed later |
| Tenant Setting | Workspace-scoped | Retain, delete, export | NULL becomes system setting | Key-by-key review | Owner policy required | Optional |
| System Setting | `workspace_id IS NULL` | Retain, controlled update | Accidental global deletion | Retain | Owner policy required | No immediate |
| ActivityLog | Workspace and actor references | Retain, anonymize actor, retention delete | Lost audit evidence | Retain minimum audit fields | Owner/legal policy required | Sentinel/job may need schema |
| Approval metadata | User approval/actor fields | Retain, anonymize actor | Loss of approval provenance | Retain or sentinel | Owner policy required | Optional |
| `created_by` | User actor FK | Retain, sentinel, SET NULL | Loss of provenance | Retain/sentinel | Owner policy required | Optional |
| `approved_by` | User actor FK | Retain, sentinel, SET NULL | Approval audit loss | Retain/sentinel | Owner policy required | Optional |
| `deleted_by` | User actor FK/string depending model | Retain, sentinel, SET NULL | Deletion provenance loss | Retain/sentinel | Owner policy required | Optional |
| `invited_by` | Member actor FK | Retain, sentinel, SET NULL | Invitation provenance loss | Retain/sentinel | Owner policy required | Optional |
| `removed_by` | Member actor FK | Retain, sentinel, SET NULL | Removal provenance loss | Retain/sentinel | Owner policy required | Optional |
| Recycle Bin rows | View over soft-deleted rows | Retain, restore, purge | User expectation/irreversibility | Restore only until policy | Owner policy required | Optional |
| Legacy/null-workspace rows | Nullable scope | Retain, quarantine, map, delete | Accidental global deletion | Quarantine/fail-closed | Owner policy required | Mapping may require migration |
| Media/uploads | Potential external files/media; existence and ownership mapping are not yet proven complete. | Retain, quarantine, delete | File/DB drift | Inventory and establish ownership mapping before selecting any disposition. | Owner policy required | File metadata may need schema |
| Provider/manual backup artifacts | External retention | Retain, expire separately | Purge cannot undo backup | Independent retention policy | Owner/legal/provider policy required | Outside app transaction |

## 8. Policy-decision matrix

| # | Policy question | Options | Security/data impact | Recommendation | Owner decision required | Migration impact |
|---:|---|---|---|---|---|---|
| 1 | Chỉ workspace đã soft-delete mới được purge? | APPROVED BASELINE | Active tenant destruction risk | Applied as non-negotiable constraint | Approved baseline; not unresolved policy | None/guard only |
| 2 | Active workspace có luôn bị block? | APPROVED BASELINE | Prevents live data loss | Applied as non-negotiable constraint | Approved baseline; not unresolved policy | None |
| 3 | Retention period là 0/7/30/60/90 ngày hay vô thời hạn? | Fixed/indefinite | Restore/legal window | Recommended explicit period | Owner/legal policy required | Deadline field may be needed |
| 4 | Retention tính từ field/timestamp nào? | deleted_at/request/approval | Wrong clock can bypass retention | Use approved lifecycle timestamp | Owner policy required | Possibly lifecycle ID |
| 5 | Restore có reset retention clock không? | Reset/preserve | Restore-purge race | Preserve provenance and define new event | Owner policy required | Maybe event state |
| 6 | Workspace restored có phải soft-delete lại trước purge? | APPROVED BASELINE | Ngăn purge workspace đã active trở lại | Applied as non-negotiable constraint | Approved baseline; not unresolved policy | None |
| 7 | Hình thức confirmation dùng workspace name hay phrase? | Workspace name/confirmation phrase | Confirmation strength and usability | Explicit server-checked confirmation required; exact form is policy-dependent | Owner policy required | None |
| 8 | Confirmation có phân biệt hoa thường không? | Case-sensitive/case-insensitive | UX vs accidental match | Server-side comparison rule must be selected | Owner policy required | None |
| 9 | Confirmation phrase cụ thể là gì? | Owner-selected phrase/typed target phrase | Accidental destructive action | Exact phrase mechanism must be selected; confirmation cannot be omitted | Owner policy required | None |
| 10 | Cooldown sau confirmation là bao lâu? | None/seconds/minutes | Double-check window | Select an explicit cooldown policy | Owner policy required | None |
| 11 | Có yêu cầu re-authentication không? | Session/password/MFA | Stale-session risk | Strongly recommended | Owner policy required | Auth state may need schema |
| 12 | Google-only account re-auth thế nào? | OAuth reauth/MFA/blocked | No local password path | Explicit provider-safe method | Owner policy required | Maybe reauth record |
| 13 | Chỉ `APPROVAL_OWNER` execute purge? | Yes/role set | Authorization boundary | Recommended | Owner policy required | None |
| 14 | Workspace OWNER request nhưng không execute? | Yes/no | Separation of duties | Recommended | Owner policy required | Request state may need schema |
| 15 | Có cần two-person approval? | One/two person | Insider/double-control risk | Strongly recommended | Owner policy required | Approval record likely needed |
| 16 | Requester và approver có phải khác nhau? | Yes/no | Self-approval risk | Recommended if two-person | Owner policy required | Approval record |
| 17 | Approval Owner có được tự purge? | Yes/no | System lockout risk | Block by default | Owner policy required | None/guard |
| 18 | Có được purge Approval Owner cuối cùng? | Yes/no | Permanent admin lockout | Block by default | Owner policy required | Last-owner state |
| 19 | ActivityLog retain/delete/anonymize? | Retain/anonymize/delete | Audit and privacy | Retain audit, anonymize PII | Legal/owner policy required | Sentinel may need schema |
| 20 | Invoice/InvoiceDetail disposition? | Retain/anonymize/delete | Accounting/legal risk | Retain; legal hold blocks | Accounting/legal policy required | Retention fields possible |
| 21 | Customer/appointment history disposition? | Retain/anonymize/delete | Service history loss | Retain by default | Owner policy required | None/optional |
| 22 | User thuộc nhiều workspace xử lý thế nào? | Block/transfer/group | Cross-tenant deletion | Block until resolved | Owner policy required | Membership manifest |
| 23 | User không còn workspace nhưng còn actor/audit refs? | Retain/anonymize/detach | Provenance loss | Retain/sentinel | Owner/legal policy required | Sentinel may need schema |
| 24 | Sole owner và co-owner xử lý thế nào? | Block/transfer/group | Shared access | Explicit separate policy | Owner policy required | Ownership event optional |
| 25 | Block khi còn active sessions? | Yes/no | Stale access | Recommended | Owner policy required | Session persistence currently not evidenced |
| 26 | Block khi còn active/background jobs? | Yes/no | Concurrent mutation | Recommended | Owner policy required | Job table may be needed |
| 27 | Có legal hold không? | Yes/no | Compliance | Must support block if selected | Legal policy required | Legal-hold state likely needed |
| 28 | Bắt buộc export/archive ngoài app trước purge? | Yes/no | Recovery/audit | Recommended | Owner/legal policy required | None |
| 29 | Provider backup retention độc lập? | Yes/no | Backup outlives app purge | Must be explicit | Provider/legal policy required | Outside app schema |
| 30 | Có cancel purge trong retention window? | Yes/no | Recovery safety | Recommended before irreversible step | Owner policy required | Request state may be needed |
| 31 | Có immutable dry-run manifest? | Optional/required | Reviewability | Strongly recommended | Owner policy required | Manifest storage may be needed |
| 32 | Audit record nào phải tồn tại sau purge? | Full/sentinel/summary | Evidence preservation | Define minimum fields | Legal/owner policy required | Sentinel schema possible |
| 33 | Purge thất bại có retry không? | Retry/manual block | Partial mutation risk | Retry only with idempotency | Owner policy required | Job state likely needed |
| 34 | Có lifecycle/job ID không? | None/synchronous/ID | Correlation/idempotency | Required for async | Owner policy required | Likely migration |
| 35 | Account và workspace purge cùng transaction? | Same/separate | Atomicity vs scope | Define group boundary | Owner policy required | None/transaction design |
| 36 | Workspace cuối cùng của user xử lý thế nào? | Block/retain/purge | Lockout and data loss | Block by default | Owner policy required | Optional lifecycle state |

Recommendations above are not approvals. “Required” appears only as a policy gate, not as an implemented runtime requirement.

## 9. Authorization and tenant-isolation assessment

Phân biệt bốn quyền:

1. View deleted target.
2. Submit/request purge.
3. Approve purge.
4. Execute purge.

Current runtime chỉ cho `APPROVAL_OWNER` soft-delete/restore account và owner workspace. Future purge phải:

- Phân biệt quyền xem deleted target, submit/request purge, approve purge request và execute purge.
- Không tin `workspace_id`, role hoặc status từ client/hidden fields.
- Resolve target bằng server-side lookup và recheck state trong transaction.
- Chống cross-workspace IDOR; shared user không bị xóa chỉ vì thuộc target workspace.
- Fail-closed với active workspace và restored workspace chưa soft-delete lại.
- Có CSRF validation, irreversible warning và typed target confirmation; comparison phải được server kiểm tra.
- Approval Portal target lookup không dựa vào current SpaManager workspace session của actor.
- Recheck `deleted_at`, actor/provenance và retention eligibility trong cùng transaction.
- STAFF/ADMIN không execute.
- Approval Owner self-purge và last-Approval-Owner là unresolved policy.
- Không giả định có persisted job/session table khi source hiện tại chưa có evidence.

## 10. Transaction and concurrency assessment

Recommendation-only, không phải implementation plan:

- Atomic commit/rollback; failure injection sau mỗi disposition step.
- Row lock hoặc equivalent stale-state guard.
- Concurrent restore versus purge, duplicate submission, duplicate approval và retry sau timeout.
- Idempotency cho lifecycle/job ID.
- Audit write failure phải rollback hoặc chuyển incident state; không tạo success log giả.
- File cleanup failure sau DB commit phải có recovery protocol riêng.
- Provider backup nằm ngoài DB transaction.
- Không để `ON DELETE SET NULL` vô tình biến tenant data thành global data.
- Phải bảo toàn audit tối thiểu sau khi target user/workspace không còn tồn tại.

## 11. Test matrix trước khi implement

### Authorization

Unauthenticated; STAFF; ADMIN; workspace OWNER; Approval Owner; requester khác approver; CSRF failure; re-auth failure.

### State guards

Active workspace; soft-deleted workspace; restored workspace; retention chưa đủ; confirmation mismatch; target không tồn tại; target đã purge; legal hold.

### Tenant isolation

IDOR workspace khác; purge A không ảnh hưởng B; shared user A/B còn tồn tại; membership B không đổi; null/global settings không bị xóa; legacy rows fail-closed.

### Data integrity

Child FK ordering; Invoice/InvoiceDetail policy; ActivityLog policy; actor FK policy; Settings policy; Recycle Bin result; no orphan; no accidental NULL/global conversion.

### Transaction/concurrency

Failure injection; full rollback; double submit; duplicate approval; concurrent restore; retry/idempotency; audit failure; file cleanup failure.

### Safeguards

Sole owner; co-owner; last Approval Owner; Approval Owner self-purge; multi-membership user; workspace-only user; Google-only re-auth.

### Environment

Canonical isolated SQLite suite; no automated PostgreSQL access unless explicitly allowed; local PostgreSQL destructive rehearsal only on disposable data; two-workspace destructive smoke; orphan/FK checks; no production purge before readiness approval.

## 12. Risk register

| Risk | Severity | Likelihood | Evidence | Mitigation | Blocking? |
|---|---|---|---|---|---|
| Cross-tenant deletion | High | Medium | Workspace-scoped FKs nullable | Server-side target and transaction recheck | Yes |
| Shared-user deletion | High | Medium | User has multi-workspace memberships | Block until every membership resolves | Yes |
| FK violation | High | Medium | Non-null member/invoice child FKs | Dependency order and PostgreSQL rehearsal | Yes |
| Partial purge | High | Medium | No purge job/manifest state | Transaction/idempotency design | Yes |
| Lost audit evidence | High | Medium | Actor/log FKs and retention unresolved | Retain/anonymize sentinel policy | Yes |
| Invoice/accounting retention conflict | High | Medium | InvoiceDetail non-null invoice/service FKs | Accounting/legal approval; retain default | Yes |
| Concurrent restore/purge | High | Low/unknown | Restore currently exists, purge absent | Lock/provenance/job guard | Yes |
| Double submission | Medium | Medium | No purge idempotency contract | Confirmation and lifecycle ID | Yes |
| Last-owner lockout | High | Low/unknown | Sole/co-owner logic exists | Block or transfer policy | Yes |
| Approval Owner self-purge | High | Low | Current self-delete guards | Explicit block policy | Yes |
| Last Approval Owner deletion | High | Low | No purge implementation | Explicit last-admin policy | Yes |
| Bypassed retention | High | Medium | No retention field | Server-side deadline and manifest | Yes |
| IDOR | High | Medium | Client requests are untrusted | Server-side lookup and workspace check | Yes |
| Google-only re-auth gap | Medium | Unknown | Provider-specific auth path | OAuth/MFA re-auth policy | Policy gate |
| `workspace_id SET NULL` global conversion | High | Medium | PG workspace FKs use SET NULL | Never detach implicitly; verify rows | Yes |
| InvoiceDetail ORM/schema drift | Medium | Confirmed | Migration column absent from ORM | Resolve through Invoice; later correction task | No, not alone |
| Railway pre-deploy migration failure | High | Unknown | Production migration history | Rehearse only on disposable environment | Yes |
| Purge-specific PostgreSQL rehearsal gap | Medium | Known limitation | Permanent purge has no implementation or destructive PostgreSQL rehearsal yet; this is not a claim that the wider application lacks PostgreSQL readiness | Disposable local PostgreSQL rehearsal before production readiness | Yes |
| File/media cleanup drift | Medium | Unknown | Potential external dependency; file/media existence and ownership mapping have not yet been proven complete. | Inventory/quarantine and separate retention | Policy gate |
| Purge relies on provider backup | High | Unknown | Provider backup external to app transaction | Separate recovery evidence | Yes |
| Legacy/null-workspace accidental deletion | High | Medium | Nullable workspace columns | Quarantine and fail-closed | Yes |

## 13. Version 6.6 roadmap

```text
6.6.1 — Permanent purge dependency and policy discovery
6.6.2 — Permanent purge security and retention policy
6.6.3 — Schema/migration proposal if required
6.6.4 — Purge service implementation
6.6.5 — Approval Portal destructive confirmation UX
6.6.6 — Cross-workspace, rollback, orphan and audit tests
6.6.7 — Local PostgreSQL rehearsal
6.6.8 — Production readiness checklist
6.6.9 — Production smoke and closure documentation
```

Mỗi task cần dependency, approval gate, migration gate và prohibited early start.

Recommendation:

- Tách workspace purge service và account purge service.
- Nên triển khai workspace policy trước account purge.
- Account purge có thể defer lâu hơn do shared-user và audit complexity.
- UI không triển khai trước service security contract và tests.
- Production smoke không thực hiện trước local PostgreSQL rehearsal.

Đây chỉ là recommendation, không phải approved scope.

| Task | Dependency | Owner approval gate | Migration gate | Prohibited early start |
|---|---|---|---|---|
| 6.6.1 | Current discovery task | Discovery diff phải được review, commit và push trước task kế tiếp | Không migration | Không mở 6.6.2 trước khi review xong |
| 6.6.2 | 6.6.1 được chấp nhận | Owner quyết định retention, disposition, permissions, audit, confirmation | Chưa implementation/schema | Không code purge |
| 6.6.3 | Policy 6.6.2 chọn schema | Migration proposal được approve riêng; đánh giá Railway pre-deploy | Chỉ mở nếu policy cần | Không tạo migration sớm |
| 6.6.4 | Approved policy và migration decision | Service contract được review | Rehearse migration trước implementation nếu cần | Không mở UI trước backend contract |
| 6.6.5 | Service authorization/state contract | UX destructive confirmation được approve | Không tự tạo schema | Không expose purge action trước backend tests |
| 6.6.6 | Reviewed implementation | Test plan được approve | Test SQLite/PostgreSQL parity | Không production smoke |
| 6.6.7 | Implementation và tests pass | Disposable local PostgreSQL only | Không production/Railway DB | Không dùng production data |
| 6.6.8 | Local rehearsal PASS | Provider recovery/runbook/readiness approval | Deployment gate review | Không deploy purge |
| 6.6.9 | Readiness checklist PASS | Explicit production approval | Closure evidence required | Không smoke production sớm |

## 14. Backup and recovery boundary

- SpaManager không có in-app PostgreSQL backup action.
- Không tạo Web backup hoặc Flask CLI backup cho purge.
- Local PostgreSQL backup chỉ theo manual PowerShell runbook đã được Version 6.4 chấp nhận.
- Production backup/restore thuộc Railway/provider và nằm ngoài application transaction.
- Provider backup không biến permanent purge thành thao tác có thể hoàn tác từ UI.
- Recovery/readiness evidence có thể là prerequisite theo policy nhưng không phải application feature.

## 15. Migration assessment

| Policy choice | Existing schema sufficient? | Migration required? | Reason |
|---|---|---|---|
| Synchronous, one-time, reviewed minimal purge dùng metadata hiện có | Có thể | NO | Không có persisted request/job nếu chấp nhận flow đồng bộ |
| Two-person approval persisted | Chưa chứng minh | Policy-dependent | Cần lưu requester/approver và decision |
| Retention deadline/legal hold persisted | Chưa có evidence | Policy-dependent | Cần deadline/hold state hoặc external source đáng tin |
| Immutable dry-run manifest | Chưa có evidence | Policy-dependent | Có thể external signed artifact hoặc schema mới |
| Async retry/idempotent job | Chưa có evidence | Migration required if this policy is selected | Cần lifecycle/job ID và trạng thái retry |
| Purge cancellation state | Chưa có evidence | Migration required if this policy is selected | Cần lưu request state/cooldown/cancel decision |
| Retained anonymized/sentinel audit identity | Chưa có evidence | Migration required if current schema cannot represent it | Cần giữ audit identity sau anonymization |
| InvoiceDetail direct workspace ORM queries | Chưa đủ | Không nhất thiết | Có thể resolve gián tiếp qua Invoice; ORM correction là task sau |

Migration mandatory for every safe minimal synchronous implementation: `NO`.

Migration requirement for production-grade persisted workflow: `POLICY-DEPENDENT`.

Migration chỉ trở thành bắt buộc nếu Owner chọn persisted retention deadline, legal hold state, persisted requester/approver separation, immutable in-database manifest, asynchronous job, durable retry/idempotency, purge cancellation state hoặc retained anonymized/sentinel audit identity mà schema hiện tại không biểu diễn được.

Không đổi classification chỉ vì ORM thiếu mapping. Chỉ chuyển sang `DISCOVERY DONE / BLOCKED FOR MIGRATION APPROVAL` nếu chứng minh không có phương án an toàn nào với schema hiện tại.

## 16. Validation

Revision này chỉ sửa documentation. Không chạy lại full suite hoặc compileall theo yêu cầu coordinator vì suite trước đã PASS 379 tests và có side effect rewrite hai protected Excel templates.

Expected scope:

```text
M docs/workspace/README.md
?? docs/workspace/PERMANENT_PURGE_DEPENDENCY_POLICY_DISCOVERY.md
```

Không có migration diff, không sửa runtime/test/schema và không có purge implementation.

## 17. Final classification

`DISCOVERY DONE / READY FOR POLICY DECISION`

Permanent purge chưa được triển khai, chưa có migration approval và không được suy ra từ tài liệu này. Bước tiếp theo là policy decision; không bắt đầu Task 6.6.2 cho tới khi policy và blocker được xử lý.
