# Task 6.5.22 — OWNER/Workspace Lifecycle Smoke + Security Audit

## 1. Phạm vi audit

Audit bao phủ vòng đời do `APPROVAL_OWNER` thực hiện:

1. Xóa mềm tài khoản `OWNER`.
2. Xác định workspace nào được xóa mềm theo ownership policy.
3. Chặn truy cập workspace đã xóa mềm theo cơ chế fail-closed.
4. Khôi phục tài khoản `OWNER`.
5. Chỉ khôi phục workspace thuộc cùng sự kiện xóa owner theo deletion provenance.
6. Xác nhận dữ liệu nghiệp vụ đại diện vẫn giữ nguyên và đọc lại được sau restore.

Task không thay đổi schema, migration, purge, hard-delete hoặc cấu trúc `ActivityLog`.

## 2. Runtime flow hiện tại

- Xóa mềm: `UserService.soft_delete_owner_workspace(actor, user_id, reason=None)`.
- Khôi phục: `UserService.restore_owner_workspace(actor, user_id)`.
- Route xóa mềm: `POST /approval/users/<id>/soft-delete-owner-workspace`.
- Route khôi phục: `POST /approval/users/<id>/restore-owner-workspace`.
- `Workspace.deleted_at` là source of truth để các workspace guard chặn truy cập.
- `WorkspaceMember` và dữ liệu nghiệp vụ không bị cascade update hoặc delete.
- `soft_delete_account()` và `restore_account()` tiếp tục là flow riêng của STAFF/ADMIN.

## 3. Authorization matrix

| Actor | Xóa OWNER/Workspace | Khôi phục OWNER/Workspace |
| --- | --- | --- |
| APPROVAL_OWNER | Cho phép | Cho phép |
| OWNER | Từ chối | Từ chối |
| ADMIN | Từ chối | Từ chối |
| STAFF | Từ chối | Từ chối |

Các guard bổ sung:

- Không cho target chính `APPROVAL_OWNER` đang thao tác.
- Không cho target một `APPROVAL_OWNER` khác.
- Target bắt buộc có role `OWNER`.
- Delete lặp lại và restore lặp lại đều bị từ chối.
- Route mutation chỉ chấp nhận `POST`; request `GET` trả `405`.
- Form desktop/mobile đều có CSRF token.

## 4. Workspace ownership policy

### Sole owner

Workspace active mà target là active owner hợp lệ cuối cùng sẽ được xóa mềm cùng owner. Tài khoản owner và workspace dùng chung `deleted_at`, `deleted_by_id` và `deletion_reason` trong cùng transaction.

### Co-owner

Workspace được giữ active nếu còn owner khác thỏa toàn bộ điều kiện:

- Membership `role = "owner"` và `status = "active"`.
- User role là `OWNER`.
- User chưa bị xóa mềm.
- `is_active = True`.
- `approval_status = "active"`.

Membership của target và co-owner đều không bị thay đổi. Activity Log ghi rõ workspace được giữ vì còn co-owner hợp lệ.

### Multiple workspaces

Mỗi workspace được đánh giá độc lập. Một owner có thể đồng thời:

- Là sole owner của workspace cần xóa mềm.
- Là co-owner của workspace phải giữ active.
- Có membership trong workspace đã deleted trước đó và không được tác động trong bước delete mới.

## 5. Restore provenance policy

Restore không còn khôi phục mù quáng mọi workspace deleted theo owner membership.

Workspace chỉ được restore khi:

- Target có membership `role = "owner"` trong workspace.
- `workspace.deleted_at == owner.deleted_at` trước khi owner được clear soft-delete fields.
- `workspace.deleted_by_id == owner.deleted_by_id` trước khi owner được clear soft-delete fields.

`deletion_reason` không được dùng làm tiêu chí duy nhất vì nội dung reason có thể trùng giữa các sự kiện. Workspace không khớp provenance vẫn giữ deleted và được nêu trong Activity Log.

Nếu không có workspace khớp provenance, tài khoản owner hợp lệ vẫn được restore và hệ thống không tự tạo workspace mới.

## 6. Transaction và rollback

Cả delete và restore thực hiện mutation, Activity Log và commit trong một transaction.

Automated tests giả lập lỗi ghi log trước commit và xác nhận:

- Delete lỗi: owner/workspace vẫn active, không có trạng thái nửa vời và không có success log.
- Restore lỗi: owner/workspace vẫn deleted, không có trạng thái nửa vời và không có success log.
- `db.session.rollback()` được gọi qua exception path hiện hữu.

## 7. Workspace guard behavior

Automated lifecycle smoke xác nhận:

- Trước delete: current workspace hợp lệ và `scoped_query(Customer)` đọc được dữ liệu.
- Sau delete sole-owner workspace: `User.can_access_app = False`, workspace membership check fail-closed, stale `current_workspace_id` bị clear, scoped query trả rỗng và `assign_workspace` bị chặn.
- Sau restore active owner: workspace hoạt động lại, membership vẫn active và dữ liệu cũ đọc lại được.
- Sau restore owner pending/rejected/disabled: workspace đúng provenance có thể được restore nhưng owner vẫn `is_active = False` và không thể access app.
- Co-owner hợp lệ tiếp tục truy cập shared workspace trong khi target owner đã deleted không thể dùng stale session để truy cập.

## 8. Data retention invariants

Qua một vòng delete → restore, test đại diện bằng `Customer` xác nhận:

- `User.id`, `Workspace.id`, `WorkspaceMember.id` và `Customer.id` không đổi.
- Không hard-delete và không tạo bản ghi trùng.
- Không thay đổi `Customer.deleted_at`.
- Không thay đổi `WorkspaceMember.status`.
- Không tự tạo workspace mới.
- `approval_status` của owner giữ nguyên.

`Customer` được dùng làm business-data representative vì các model nghiệp vụ đều sử dụng cùng workspace guard/scoped-query architecture. Task không chạy cascade mutation trên Service, Appointment, Invoice hoặc Setting.

## 9. Automated smoke evidence

- Lifecycle/guard focused suite: `34` tests, PASS.
- Canonical full suite: `351` tests, PASS.
- Co-owner shared workspace: PASS.
- Restore provenance mismatch: PASS.
- Multiple sole-owner workspaces và unrelated workspace isolation: PASS.
- Delete/restore rollback atomicity: PASS.
- STAFF/ADMIN lifecycle regression: PASS.
- Route POST/GET, authorization, AJAX, CSRF marker và purge guard: PASS.

Canonical command:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

## 10. Manual production smoke checklist

Chỉ thực hiện trên workspace test riêng, không chứa dữ liệu thật quan trọng:

1. Tạo hai OWNER test và một shared workspace test có Customer test.
2. Xác nhận cả hai owner membership đều active trước thao tác.
3. Xóa mềm một owner qua Approval Portal; xác nhận shared workspace vẫn active và co-owner vẫn thấy Customer test.
4. Tạo một workspace test mà target là sole owner; xóa mềm target và xác nhận workspace bị chặn fail-closed.
5. Khôi phục target qua Approval Portal; xác nhận workspace cùng sự kiện xóa hoạt động lại và Customer test vẫn cùng record.
6. Xác nhận workspace deleted từ sự kiện cũ/khác không bị khôi phục.
7. Kiểm tra Activity Log có owner target, workspace đã xử lý, workspace giữ lại và workspace provenance mismatch nếu có.
8. Không dùng purge, không chỉnh DB trực tiếp và không thực hiện trên production data quan trọng.

Task 6.5.22 không yêu cầu migration hoặc thao tác production database thủ công.

## 11. Explicit non-goals

- Không permanent delete hoặc purge.
- Không hard-delete User, Workspace, WorkspaceMember hoặc business data.
- Không thêm lifecycle event/group ID vào schema.
- Không thêm hoặc backfill `ActivityLog.workspace_id`.
- Không sửa migration `0006_user_ws_soft_delete`.
- Không sửa root unittest discovery circular import.
- Không thay đổi Excel import templates.

## 12. Remaining risks

- Provenance hiện dựa trên cặp `deleted_at` + `deleted_by_id`, phù hợp với transaction hiện tại nhưng không mạnh bằng lifecycle event ID riêng.
- Dữ liệu legacy bị chỉnh thủ công hoặc bị mất một trong hai provenance fields có thể không tự restore workspace; policy hiện tại cố ý fail-safe và giữ workspace deleted.
- Automated tests dùng SQLite test profile; task chưa chạy manual smoke trên local/staging PostgreSQL hoặc production UI.
- `ActivityLog` chưa có `workspace_id`, nên log lifecycle vẫn ở cấp hệ thống và mô tả workspace bằng text.

## 13. Kết luận

**PASS WITH LIMITATIONS**

Hai lifecycle/security gap đã được harden bằng metadata hiện có, toàn bộ automated regression pass và không cần migration. Cần review code và nên chạy manual smoke trên workspace test PostgreSQL riêng trước khi coi đây là production smoke hoàn chỉnh.

## 14. Business permanent-delete follow-up

Task 6.5.23a xác nhận Recycle Bin từng có legacy hard-delete runtime cho bốn business entities. Task 6.5.23b đã vô hiệu hóa route/UI/registry và chuyển các public service methods cùng `cleanup_old_records()` sang fail-closed. Thay đổi này không tác động soft-delete hoặc restore OWNER/Workspace đã kiểm chứng trong tài liệu này.

Account/Workspace purge vẫn chưa được triển khai. Chi tiết: [Business Permanent Delete Disablement](BUSINESS_PERMANENT_DELETE_DISABLEMENT.md).
