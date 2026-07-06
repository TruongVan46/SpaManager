# Workspace User Management Policy

> **Version**: 6.5.6
> **Status**: IMPLEMENTED
> **Last Updated**: 2026-07-06

---

## 1. Mục tiêu

Sau Task 6.5.6, mỗi workspace có danh sách owner/manager/staff riêng biệt:

- Chủ spa workspace A tạo nhân viên → nhân viên thuộc workspace A.
- Chủ spa workspace B tạo nhân viên → nhân viên thuộc workspace B.
- Nhân viên workspace A **không thấy** dữ liệu workspace B.
- Quản lý/nhân viên trong cùng workspace dùng chung dữ liệu của workspace đó.
- Không tạo mỗi account một Railway database riêng.
- Không tạo user global trôi nổi nếu user được tạo từ giao diện SpaManager.

---

## 2. Role Mapping

| Global Role (User.role) | Workspace Role (WorkspaceMember.role) |
|------------------------|---------------------------------------|
| `OWNER`                | `owner`                               |
| `ADMIN`                | `admin`                               |
| `STAFF`                | `staff`                               |
| `APPROVAL_OWNER`       | *(không có workspace membership)*     |

---

## 3. Role-Based Creation Permissions

| Actor Role | Có thể tạo/gán role        |
|------------|----------------------------|
| `OWNER`    | ADMIN, STAFF               |
| `ADMIN`    | STAFF only                 |
| `STAFF`    | *(không có quyền)*         |

Enforcement:
- `_get_available_roles_for_actor(actor)` trong `routes/user.py` lọc danh sách roles được phép (chỉ trả về ADMIN và STAFF cho OWNER, STAFF cho ADMIN).
- Kiểm tra `allowed_role_values` tại server-side/route-side trước khi gọi `UserService.create_user` / `update_user`.
- `UserService.create_user` chặn hoàn toàn việc tạo vai trò `OWNER` và `APPROVAL_OWNER` từ giao diện quản lý người dùng.
- `UserService.update_user` chặn hoàn toàn việc đổi vai trò của một tài khoản thành `OWNER` (nếu không phải là OWNER sẵn).
- Vai trò `OWNER` mới chỉ được tạo thông qua Google approval provisioning flow (phê duyệt bởi `APPROVAL_OWNER`).
- Chặn mọi hành vi tự nâng/đổi vai trò lên `ADMIN` nếu actor không phải là `OWNER` ở tầng service layer.

---

## 4. Workspace Scoping Rules

### 4.1 User List (`search_paginated`)

- **Production**: JOIN `workspace_members` với `workspace_id == current_workspace_id` và `status == "active"`. Fail-closed nếu không có workspace context (trả về query `User.id == -1`).
- **TESTING** (không có `_enable_workspace_isolation`): Unscoped query — backward compatible với legacy tests.
- **TESTING** (có `_enable_workspace_isolation`): Scoped theo `session["current_workspace_id"]`.

### 4.2 User Create (`create_user`)

1. Tạo `User` bình thường.
2. Sau `flush()`, gọi `WorkspaceService.add_member_for_user(workspace_id, user, global_role, actor)`.
3. Commit cả hai trong cùng transaction — rollback nếu lỗi.
4. Trong TESTING không có isolation flag: bỏ qua bước tạo membership (không phá vỡ legacy tests).
5. Trong production không có workspace context: raise `ValidationException`.

### 4.3 User Edit / Reset Password / Toggle Active

- Tất cả đều dùng `_get_workspace_scoped_user_or_404(user_id)`.
- Nếu user không thuộc workspace hiện tại → 404 Not Found (không tiết lộ sự tồn tại của user từ workspace khác).
- Cross-workspace manipulation bị chặn hoàn toàn.

---

## 5. Fail-Closed Security Guarantees

| Scenario | Behavior |
|----------|----------|
| Không có `current_workspace_id` trong session | User list trả về rỗng; create user raise ValidationException |
| User không thuộc workspace hiện tại | Edit/Reset/Toggle trả về 404 |
| Actor là `APPROVAL_OWNER` | Không có workspace context, mọi route user management 403 |
| `_enable_workspace_isolation = True` nhưng `current_workspace_id = None` | Fail-closed: query trả về rỗng |

---

## 6. WorkspaceService Helpers

### `add_member_for_user(workspace_id, user, global_role, actor)`

- Maps global role → workspace role theo bảng trên.
- Idempotent: nếu membership đã tồn tại, update `role` + `status = "active"`.
- Chỉ `flush()`, không `commit()` — caller chịu trách nhiệm transaction.

### `get_workspace_members_query(workspace_id)`

- Trả về `User.query` đã JOIN với `WorkspaceMember` có `workspace_id` và `status == "active"`.
- Trả về `None` nếu `workspace_id` là falsy.

### `is_user_in_workspace(user_id, workspace_id)`

- Kiểm tra xem user có active membership trong workspace hay không.
- Dùng bởi `_get_workspace_scoped_user_or_404`.

---

## 7. Testing Bypass Convention

Tất cả workspace-scoped operations trong `UserService` và `WorkspaceService` áp dụng
cùng pattern bypass cho TESTING:

```python
is_testing = has_app_context() and current_app.config.get("TESTING") is True
if is_testing:
    if not has_request_context() or not session.get("_enable_workspace_isolation"):
        # Legacy test compat: skip workspace scope
        ...
    workspace_id = session.get("current_workspace_id")
else:
    workspace_id = WorkspaceService.get_current_workspace_id()
```

- **Legacy tests** (không set `_enable_workspace_isolation`): bypass hoàn toàn.
- **Isolation tests** (set `session["_enable_workspace_isolation"] = True`): enforce như production.
- **Production** (không có TESTING flag): luôn enforce, không có bypass.

---

## 8. Files Affected (Task 6.5.6)

| File | Thay đổi |
|------|----------|
| `services/workspace_service.py` | Thêm `add_member_for_user`, `get_workspace_members_query`, `is_user_in_workspace` |
| `services/user_service.py` | Scope `search_paginated`, `create_user`, `update_user`, `reset_password`, `toggle_active` |
| `routes/user.py` | Actor-scoped `available_roles`, workspace-scoped `_get_user_or_404` calls |
| `tests/test_workspace_isolation.py` | Thêm `TestWorkspaceUserManagement` test class |
| `docs/workspace/WORKSPACE_USER_MANAGEMENT_POLICY.md` | Tài liệu này |

---

## 9. Không thay đổi

- `models/user.py` — không thêm `workspace_id` vào User model.
- `models/workspace.py` — không thay đổi schema.
- Migration — vẫn là `0003_workspace_foundation`.
- Google approval flow / `APPROVAL_OWNER` bootstrap / portal.
- Railway settings / `APP_VERSION`.
- Excel templates.
