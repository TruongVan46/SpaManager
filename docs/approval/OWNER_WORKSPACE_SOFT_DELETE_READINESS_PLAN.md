# Owner + Workspace Soft Delete Readiness Plan

## 1. Purpose
Tài liệu này chuẩn bị phương án thiết kế hệ thống và lộ trình triển khai chi tiết cho việc **xóa mềm (soft-delete) tài khoản OWNER** đi kèm với **xóa mềm Workspace** tương ứng trong hệ thống SpaManager.
Mục tiêu chính:
* Thiết kế luồng xử lý đồng bộ và an toàn khi xóa tài khoản OWNER (chủ sở hữu chính của một hoặc nhiều Spa).
* Đảm bảo tính cô lập và bảo mật dữ liệu: Một khi workspace bị xóa mềm, toàn bộ dữ liệu nghiệp vụ thuộc workspace đó phải bị ẩn lập tức và không thể truy cập từ bất kỳ API/màn hình nào.
* Thiết lập cơ chế khôi phục (restore) toàn vẹn dữ liệu cho OWNER và Workspace sau này.
* Đảm bảo không làm thay đổi hay gián đoạn các luồng nghiệp vụ hiện tại của STAFF/ADMIN.
* Xác định rõ thứ tự dọn dẹp dữ liệu vĩnh viễn (purge) để tránh lỗi vi phạm ràng buộc khóa ngoại (Foreign Key Integrity Constraints) trên PostgreSQL.

---

## 2. Current State
* **Cột schema xóa mềm (Migration 0006):**
  * Bảng `users` có: `deleted_at` (DateTime), `deleted_by_id` (FK tới `users.id`), `deletion_reason` (String).
  * Bảng `workspaces` có: `deleted_at` (DateTime), `deleted_by_id` (FK tới `users.id`), `deletion_reason` (String).
* **Trạng thái runtime hiện tại:**
  * Đã hỗ trợ xóa mềm và khôi phục STAFF/ADMIN tại Approval Portal thông qua `deleted_at` (Task 6.5.16/17).
  * Việc xóa mềm/khôi phục OWNER hiện tại đang bị chặn cứng tại tầng Service nghiệp vụ (nếu target role là `OWNER` sẽ raise `ValidationException`).
  * Việc xóa mềm/khôi phục Workspace chưa được triển khai bất kỳ logic runtime nào.
  * Các thực thể nghiệp vụ (`Customer`, `Service`, `Appointment`, `Invoice`) đã được workspace-scoped thông qua cơ chế `WorkspaceService.scoped_query` lọc theo `current_workspace_id`.
  * Bảng `activity_logs` ghi nhận nhật ký hệ thống hiện tại chưa có cột `workspace_id` phục vụ việc phân tách log.

---

## 3. Code Paths Audited
Qua quá trình audit mã nguồn của SpaManager, chúng tôi ghi nhận kết luận từ các luồng code chính như sau:

| File/Module | Kết luận Audit & Điểm cần lưu ý |
| :--- | :--- |
| [models/user.py](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/models/user.py) | Property `can_access_app` đã chặn đúng các tài khoản có `deleted_at is not None`. Tuy nhiên, thuộc tính này chỉ mới check ở tầng login cơ bản, cần rà soát lại cơ chế Google OAuth callback. |
| [models/workspace.py](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/models/workspace.py) | Bảng `workspaces` có các trường `deleted_at`, `deleted_by_id`, `deletion_reason` nhưng chưa có property `is_deleted` hay logic phụ thuộc nào được định nghĩa trên model. |
| [services/user_service.py](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/services/user_service.py) | Các phương thức `soft_delete_account` và `restore_account` đang chặn cứng vai trò `OWNER`. Cần tách biệt phương thức xóa/khôi phục dành riêng cho `OWNER` vì luồng này đi kèm tác động tới Workspace (cascade). |
| [services/workspace_service.py](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/services/workspace_service.py) | `is_user_in_workspace(user_id, workspace_id)` hiện tại chưa kiểm tra cột `deleted_at` của bảng `workspaces`. Nếu một workspace bị xóa mềm, hàm này vẫn có thể trả về `True` nếu membership trong bảng `workspace_members` còn active. |
| [services/auth_service.py](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/services/auth_service.py) | Phương thức `login` gọi `user.can_access_app` và chặn đăng nhập của tài khoản bị xóa mềm. Cần đảm bảo route Google OAuth callback (`/login/google/callback`) cũng gọi qua hàm xác thực có kiểm tra `can_access_app`. |
| [routes/approval.py](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/routes/approval.py) | Các route phê duyệt tài khoản hiện không hiển thị thông tin workspace bị ảnh hưởng khi một tài khoản OWNER bị xóa mềm. |
| `Business Services & Routes` | Các service/route chính (`CustomerService`, `AppointmentService`, v.v.) truy vấn dữ liệu thông qua `scoped_query` sử dụng `session.get('current_workspace_id')`. Nếu session vẫn lưu ID của một workspace đã bị xóa mềm, hệ thống có thể bị rò rỉ thông tin hoặc cho phép sửa đổi dữ liệu bất hợp pháp. |
| `Workspace Selector & Sidebar` | Template sidebar hiển thị danh sách các workspace của người dùng bằng cách lấy từ danh sách membership active của họ. Cần lọc bỏ các workspace có `deleted_at is not None`. |
| `Recycle Bin` | Recycle Bin chỉ quản lý việc xóa mềm/khôi phục ở mức tenant của các thực thể kinh doanh. Hoàn toàn độc lập và không liên quan đến việc quản lý tài khoản/workspace bị xóa mềm ở Approval Portal. |

---

## 4. Owner Deletion Rules
Để đảm bảo an toàn tuyệt đối cho hệ thống và tránh mâu thuẫn dữ liệu, các luật xóa mềm tài khoản OWNER được thiết kế như sau:

1. **Quyền thực hiện:** Chỉ tài khoản có vai trò `APPROVAL_OWNER` mới có quyền xóa mềm tài khoản OWNER.
2. **Không tự xóa chính mình:** `APPROVAL_OWNER` không thể tự xóa tài khoản của mình hoặc tài khoản `APPROVAL_OWNER` khác.
3. **Quy trình khi xóa OWNER:**
   * Cập nhật thông tin xóa mềm trên bảng `users`: `deleted_at = utc_now()`, `deleted_by_id = actor.id`, `deletion_reason = reason`.
   * Cập nhật `is_active = False` để khóa quyền đăng nhập của OWNER toàn cục.
   * Tự động xác định tất cả các Workspace do OWNER này sở hữu chính (thông qua `WorkspaceMember` có `user_id == owner.id` and `role == "owner"`).
   * Tiến hành xóa mềm liên đới (cascade soft-delete) tất cả các workspace tìm thấy bằng cách cập nhật các trường `deleted_at`, `deleted_by_id`, và `deletion_reason` tương ứng của bảng `workspaces`.
4. **Xử lý OWNER sở hữu nhiều Workspace (Multi-workspace Policy):**
   * Trong SpaManager, một tài khoản OWNER có thể sở hữu nhiều chi nhánh (workspace) khác nhau.
   * **Phương án đề xuất:** Khi xóa mềm tài khoản OWNER, hệ thống sẽ **xóa mềm toàn bộ các workspace** mà OWNER đó sở hữu chính.
   * **Lý do lựa chọn:** Đây là phương án an toàn nhất (fail-closed), ngăn chặn triệt để tình trạng một workspace hoạt động nhưng chủ sở hữu (OWNER) của nó đã bị khóa tài khoản toàn cục.
5. **Giữ nguyên dữ liệu nghiệp vụ:** Không được thực hiện bất kỳ thao tác xóa cứng (hard-delete) nào đối với dữ liệu của OWNER hoặc của các workspace liên quan.

---

## 5. Workspace Soft Delete Rules
Khi một workspace bị xóa mềm:

1. **Đánh dấu trạng thái:** Cột `workspaces.deleted_at` nhận giá trị thời gian hiện tại, `deleted_by_id` lưu ID của người thực hiện, `deletion_reason` lưu lý do.
2. **Quản lý cột `status`:**
   * Cột `status` của workspace (giá trị hiện tại: `active`, `pending`, `suspended`, `archived`) sẽ **được giữ nguyên trạng thái cũ** (ví dụ: đang là `active` thì vẫn giữ `active`).
   * **Lý do:** Giúp khôi phục (restore) chính xác trạng thái hoạt động ban đầu của workspace mà không làm mất thông tin phân loại hành chính (ví dụ: một workspace vốn đang bị tạm ngưng `suspended` do nợ phí, khi khôi phục lại vẫn phải ở trạng thái `suspended` chứ không được tự động chuyển thành `active`).
3. **Quản lý Workspace Members:**
   * **Không thay đổi trạng thái members:** Hệ thống sẽ giữ nguyên danh sách và trạng thái của các thành viên trong bảng `workspace_members` (trừ tài khoản OWNER đã bị khóa global).
   * **Lý do:** Giúp việc khôi phục (restore) diễn ra tức thì mà không cần duyệt qua và cập nhật hàng loạt bản ghi membership. Quyền truy cập của nhân viên vào workspace bị xóa mềm sẽ được chặn cứng tại tầng middleware / workspace guard bằng cách kiểm tra trực tiếp cột `workspaces.deleted_at`.
4. **Quản lý dữ liệu nghiệp vụ (Business Data Isolation):**
   * Tuyệt đối không cập nhật cột `deleted_at` của từng bản ghi `Customer`, `Service`, `Appointment`, `Invoice` thuộc workspace đó.
   * Toàn bộ dữ liệu này sẽ tự động bị ẩn đi vì truy vấn toàn cục (`scoped_query`) sẽ lọc bỏ dựa trên việc loại trừ các workspace đã bị xóa mềm.

---

## 6. Required Runtime Guards
Để ngăn chặn hoàn toàn việc rò rỉ dữ liệu hoặc truy cập trái phép vào tài khoản/workspace đã bị xóa mềm, hệ thống bắt buộc phải bổ sung các lớp bảo vệ (guards) sau:

### 6.1. AuthService & Google OAuth Guard
* Thuộc tính `User.can_access_app` sẽ trả về `False` nếu tài khoản có `deleted_at is not None`.
* Cần kiểm tra route nhận callback từ Google OAuth `/login/google/callback` để chắc chắn rằng sau khi lấy được thông tin user từ Google, hệ thống vẫn gọi qua logic kiểm tra `can_access_app` trước khi thiết lập session đăng nhập.

### 6.2. Current Workspace Session Selection Guard
* Trong logic xác định workspace hiện tại khi đăng nhập (`ensure_current_workspace_session` hoặc helper tương tự):
  * Không cho phép chọn workspace có `deleted_at is not None`.
  * Nếu session `current_workspace_id` trỏ tới một workspace đã bị xóa mềm, hệ thống phải thực hiện xóa thông tin này khỏi session ngay lập tức (clear session) và yêu cầu người dùng chuyển sang workspace hợp lệ khác, hoặc điều hướng về trang thông báo lỗi an toàn (Fail-closed).
  * Đối với nhân viên (`STAFF`/`ADMIN`), nếu workspace duy nhất của họ bị xóa mềm, khi đăng nhập sẽ hiển thị trang thông báo: *"Workspace của bạn đã bị vô hiệu hóa hoặc bị xóa. Vui lòng liên hệ quản trị viên."*

### 6.3. Workspace Selector UI Guard
* Trên giao diện thanh điều hướng bên (Sidebar), danh sách các spa/workspace hiển thị cho người dùng phải được lọc bỏ hoàn toàn các bản ghi có `deleted_at is not None`.
* Chặn endpoint switch workspace nếu truyền vào ID của workspace đã xóa mềm.

### 6.4. WorkspaceService Guard
* Phương thức `WorkspaceService.is_user_in_workspace(user_id, workspace_id)` phải trả về `False` nếu `workspace.deleted_at is not None`.
* Các phương thức lấy workspace hiện tại hoặc lấy danh sách workspace hoạt động của một user phải loại bỏ các workspace bị xóa mềm.

### 6.5. Tầng Truy Vấn Toàn Cục (scoped_query)
* Cập nhật helper `WorkspaceService.scoped_query` hoặc middleware lọc tenant để đảm bảo nếu workspace hiện tại đã bị xóa mềm, mọi truy vấn nghiệp vụ liên quan đến `Customer`, `Service`, `Appointment`, `Invoice`, `Setting` đều phải trả về kết quả rỗng (hoặc raise 404).

### 6.6. Approval Portal Listing
* Các tài khoản OWNER đã bị xóa mềm sẽ được hiển thị riêng biệt trong tab **"Đã xóa mềm"** của Approval Portal cùng danh sách các Workspace bị ảnh hưởng bởi tài khoản đó.

---

## 7. Proposed Implementation Breakdown
Tiến trình thực thi việc xóa mềm OWNER và Workspace được chia nhỏ thành các bước tuần tự để kiểm soát chất lượng và tránh rủi ro production:

1. **Giai đoạn 1 (Task 6.5.19) — Workspace Deleted Guard Hardening**
   * **Mục tiêu:** Xây dựng hệ thống phòng thủ, đảm bảo hệ thống chặn đứng mọi truy cập vào workspace bị xóa mềm trước khi triển khai nút bấm xóa thực tế.
   * **Chi tiết:**
     * Cập nhật `WorkspaceService.is_user_in_workspace` và các helper lọc truy vấn để loại bỏ workspace có `deleted_at is not None`.
     * Cập nhật cơ chế chọn workspace khi đăng nhập và switch workspace để tự động clear session/chặn truy cập nếu workspace đích bị xóa mềm.
     * Lọc selector trên giao diện sidebar.
     * Viết unit test giả lập cập nhật thủ công cột `deleted_at` của workspace trong database và kiểm tra xem hệ thống có tự động ẩn dữ liệu và chặn truy cập thành công hay không.
2. **Giai đoạn 2 (Task 6.5.20) — Approval Portal Soft-delete OWNER + Workspace**
   * **Mục tiêu:** Kích hoạt chức năng xóa mềm tài khoản OWNER đi kèm xóa mềm liên đới Workspace.
   * **Chi tiết:**
     * Viết phương thức `UserService.soft_delete_owner_account(actor, user_id, reason)`.
     * Mở route POST `/approval/users/<id>/soft-delete-owner` (hoặc tích hợp vào route soft-delete hiện tại).
     * Hiện nút hành động *"Xóa mềm"* cho tài khoản OWNER trên giao diện Approval Portal. Khi click sẽ hiện modal cảnh báo nguy hiểm và yêu cầu xác nhận.
     * Ghi Activity Log hành động `SOFT_DELETE_OWNER`.
     * Viết unit test kiểm tra luồng xóa mềm cascade hoạt động chính xác.
3. **Giai đoạn 3 (Task 6.5.21) — Restore OWNER + Workspace**
   * **Mục tiêu:** Kích hoạt chức năng khôi phục tài khoản OWNER và Workspace liên kết.
   * **Chi tiết:**
     * Viết phương thức `UserService.restore_owner_account(actor, user_id)`.
     * Khôi phục đồng thời tài khoản OWNER (`deleted_at = None`, `is_active = True` nếu trạng thái duyệt gốc là active) và các workspace tương ứng của OWNER đó (`deleted_at = None`).
     * Kích hoạt nút *"Khôi phục"* cho tài khoản OWNER trên tab *"Đã xóa mềm"*.
     * Viết unit test xác nhận toàn bộ quyền truy cập và dữ liệu nghiệp vụ hiển thị lại chính xác sau khi khôi phục.
4. **Giai đoạn 4 (Task 6.5.22) — Lifecycle Smoke & Security Audit**
   * **Mục tiêu:** Chạy thử nghiệm thực tế (smoke tests) trên môi trường local/staging để audit bảo mật toàn diện.
     * Kiểm tra các trường hợp đặc biệt (nhân viên thuộc workspace bị xóa cố gắng truy cập qua API trực tiếp, OWNER khôi phục khi có tranh chấp slug trùng lặp, v.v.).
5. **Giai đoạn 5 (Task 6.5.23) — Permanent Purge Strategy Placeholder**
   * **Mục tiêu:** Tích hợp kế hoạch dọn dẹp vĩnh viễn (purge) để chuẩn bị cho các đợt giải phóng tài nguyên định kỳ.

---

## 8. Restore Strategy
Khi khôi phục một OWNER và các Workspace bị xóa mềm:

1. **Kiểm tra trùng lặp (Conflict Detection):**
   * Trước khi thực hiện khôi phục, hệ thống phải kiểm tra xem `slug` của workspace cần khôi phục có bị trùng với một workspace đang hoạt động khác hay không. Nếu trùng, hệ thống sẽ tự động thêm hậu tố ngẫu nhiên (ví dụ: `slug-restored-1`) hoặc thông báo lỗi yêu cầu `APPROVAL_OWNER` đổi tên slug trước khi khôi phục.
2. **Khôi phục trạng thái OWNER:**
   * Cập nhật `deleted_at = None`, `deleted_by_id = None`, `deletion_reason = None`.
   * Khôi phục quyền đăng nhập `is_active = True` **chỉ khi** `approval_status == 'active'`. Nếu trước khi xóa, tài khoản OWNER này đang bị khóa (`disabled`/`rejected`), thì sau khi restore vẫn phải giữ `is_active = False`.
3. **Khôi phục trạng thái Workspace:**
   * Cập nhật `deleted_at = None`, `deleted_by_id = None`, `deletion_reason = None` trên bảng `workspaces`.
   * Giữ nguyên trạng thái `status` cũ của workspace.
4. **Lưu vết:** Ghi Activity Log hành động `RESTORE_OWNER`.

---

## 9. Permanent Delete / Purge Strategy

Trạng thái hiện tại: purge chưa được triển khai và bị blocked. Policy hợp nhất tại [Permanent Purge Policy and Safe Placeholder](PERMANENT_PURGE_POLICY_AND_PLACEHOLDER.md); soft-delete và restore là lifecycle duy nhất đang được hỗ trợ.
Việc xóa vĩnh viễn (purge) dữ liệu khỏi cơ sở dữ liệu vật lý bắt buộc phải được tách riêng thành một tiến trình độc lập và tuân thủ thứ tự an toàn khóa ngoại như sau:

### 9.1. Điều kiện tiên quyết (Prerequisites)
* Phải có bản sao lưu cơ sở dữ liệu (Backup) được tạo thành công ngay trước khi thực hiện.
* Workspace/OWNER phải ở trạng thái xóa mềm vượt quá thời gian lưu trữ tối thiểu quy định (Retention Period, ví dụ: 30 ngày).

### 9.2. Thứ tự dọn dẹp vật lý (Purging Order)
Để tránh lỗi vi phạm ràng buộc khóa ngoại (Foreign Key Violations) trên PostgreSQL, việc dọn dẹp phải đi từ lá đến gốc (từ các bảng phụ thuộc nhiều nhất ngược về bảng chính):

```
1. Hoá đơn chi tiết (invoice_details)
2. Hoá đơn (invoices)
3. Lịch hẹn (appointments)
4. Khách hàng (customers)
5. Dịch vụ (services)
6. Cấu hình chi nhánh (settings)
7. Thành viên chi nhánh (workspace_members)
8. Chi nhánh (workspaces)
9. Người dùng / OWNER (users)
```

### 9.3. Nhật ký hoạt động (ActivityLog Policy)
* Khi dọn dẹp vĩnh viễn một người dùng, hệ thống **không xóa** các bản ghi nhật ký hoạt động `activity_logs` của họ để phục vụ đối soát bảo mật. Thay vào đó, hệ thống sẽ thực hiện **ẩn danh hóa (anonymize)** bằng cách đặt `user_id = NULL` và thay thế tên người thực hiện trong mô tả log bằng chuỗi `"Người dùng đã bị dọn dẹp vĩnh viễn"`.

---

## 10. Test Matrix for Future Implementation

| Mã Test | Kịch bản kiểm thử | Kết quả mong đợi |
| :--- | :--- | :--- |
| **TEST-01** | Truy cập dữ liệu của Workspace đã bị xóa mềm bằng API | Trả về lỗi `404 Not Found` (Fail-closed). |
| **TEST-02** | Hiển thị Workspace đã bị xóa mềm trong bộ chọn chi nhánh | Lọc bỏ hoàn toàn, không hiển thị trên giao diện. |
| **TEST-03** | Đăng nhập tài khoản OWNER đã bị xóa mềm | Bị chặn đăng nhập ngay tại màn hình Login (trả về lỗi 401). |
| **TEST-04** | Đăng nhập nhân viên thuộc Workspace đã bị xóa mềm | Đăng nhập thành công nhưng bị điều hướng tới trang thông báo workspace bị khóa/xóa. |
| **TEST-05** | Xóa mềm OWNER sở hữu đúng 1 Workspace | OWNER bị khóa, Workspace bị đánh dấu `deleted_at` thành công. |
| **TEST-06** | Xóa mềm OWNER sở hữu nhiều Workspace | OWNER bị khóa, toàn bộ các Workspace thuộc sở hữu chính đều bị xóa mềm. |
| **TEST-07** | `APPROVAL_OWNER` tự xóa chính mình | Bị chặn và báo lỗi nghiệp vụ. |
| **TEST-08** | Khôi phục OWNER có trạng thái duyệt là `disabled` | OWNER được khôi phục các trường xóa mềm nhưng `is_active` vẫn giữ là `False`. |
| **TEST-09** | Khôi phục Workspace có slug bị trùng lặp | Hệ thống phát hiện trùng lặp và tự động điều chỉnh slug an toàn trước khi active. |
| **TEST-10** | Dọn dẹp vĩnh viễn (Purge) Workspace | Dữ liệu bị xóa sạch theo đúng trình tự khóa ngoại, không gây crash DB. |

---

## 11. UI/UX Proposal
* **Giao diện Approval Portal (Tab Active):**
  * Đối với các dòng tài khoản OWNER, thay vì nút *"Vô hiệu hóa"*, hiển thị nút **"Xóa mềm OWNER"** (màu đỏ cam).
  * Khi click nút, hiển thị hộp thoại Modal xác nhận nguy hiểm cao:
    > **CẢNH BÁO NGUY HIỂM!**
    > Hành động này sẽ khóa tài khoản OWNER và tự động ẩn toàn bộ các Workspace cùng dữ liệu kinh doanh liên kết. Nhân viên thuộc các workspace này cũng sẽ mất quyền truy cập dữ liệu.
    > Bạn có chắc chắn muốn tiếp tục?
    > *[Yêu cầu nhập địa chỉ email của OWNER để xác nhận]*
* **Giao diện Approval Portal (Tab Đã xóa mềm):**
  * Hiển thị danh sách OWNER kèm theo tên các workspace đã bị ẩn liên đới.
  * Nút **"Khôi phục"** (màu xanh) khi click sẽ mở modal xác nhận: *"Khôi phục OWNER này sẽ kích hoạt lại toàn bộ các workspace liên kết hoạt động trở lại bình thường. Bạn có chắc chắn?"*

---

## 12. Open Questions
Cần xin ý kiến quyết định từ Product Owner cho các trường hợp biên sau:
1. **Chuyển nhượng quyền sở hữu (Ownership Transfer):** Nếu một workspace có nhiều OWNER hoặc OWNER muốn chuyển nhượng quyền sở hữu cho một ADMIN trước khi rời đi, hệ thống có nên bắt buộc chuyển nhượng trước khi cho phép xóa mềm OWNER hay không?
2. **Thông báo qua Email:** Hệ thống có nên tự động gửi email thông báo cho OWNER và toàn bộ nhân viên liên quan khi một workspace bị xóa mềm hoặc khôi phục hay không?
3. **Thời gian lưu trữ tối đa (Purge Retention):** Có nên tự động chạy tiến trình Cron job dọn dẹp vĩnh viễn dữ liệu sau 30/60 ngày xóa mềm không, hay bắt buộc phải có lệnh click chuột thủ công từ `APPROVAL_OWNER`?

---

## 13. Explicit Non-goals
* Không thực hiện viết mã nguồn chạy runtime cho việc xóa/khôi phục OWNER và Workspace trong task này.
* Không tạo bất kỳ file migration vật lý nào trong dự án tại task này.
* Không thay đổi dữ liệu thực tế trên môi trường Database Production.
* Không tích hợp cột `workspace_id` vào bảng `activity_logs` trong giai đoạn này.

---

## 14. Trạng thái thực tế triển khai (Actual Implementation Status)
* **Task 6.5.19 / 6.5.19a (DONE):**
  * Đã triển khai và củng cố toàn bộ các **lớp bảo vệ runtime (guards)** đối với Workspace đã bị xóa mềm (`deleted_at is not None`).
  * `WorkspaceService.is_user_in_workspace` tự động trả về `False` nếu workspace đích bị xóa mềm.
  * Tầng session và helper workspace tự động clear context và fail-closed nếu workspace hiện hành bị xóa mềm.
  * Tầng truy vấn toàn cục `scoped_query` và logic `assign_workspace` tự động chặn đứng việc đọc/ghi dữ liệu nghiệp vụ thuộc workspace đã xóa mềm (kể cả trong môi trường unit test).
* **Task 6.5.20 (DONE):**
  * Đã triển khai hoàn chỉnh chức năng **Xóa mềm OWNER + Workspace** liên quan từ Approval Portal.
  * Khi APPROVAL_OWNER thực hiện xóa mềm OWNER: tài khoản OWNER bị set `is_active = False` và gán thông tin xóa mềm. Đồng thời, toàn bộ workspace đang hoạt động do OWNER sở hữu cũng bị gán `deleted_at = datetime.utcnow()`.
  * OWNER đã bị xóa mềm sẽ xuất hiện trên danh sách "Đã xóa mềm".
* **Task 6.5.21 (DONE):**
  * Đã triển khai chức năng **Khôi phục OWNER + Workspace** từ Approval Portal bằng service và route riêng, chỉ dành cho `APPROVAL_OWNER`.
  * Khi khôi phục, hệ thống giữ nguyên `approval_status`, chỉ bật lại `is_active` khi trạng thái duyệt là `active`, đồng thời khôi phục tất cả workspace đã xóa mềm mà OWNER sở hữu qua membership `role = "owner"`.
  * Không thay đổi hàng loạt `WorkspaceMember.status`, không tạo workspace mới và không sửa/xóa dữ liệu nghiệp vụ.
  * Chức năng **Xóa vĩnh viễn (Purge)** vẫn chưa được triển khai (nút thao tác vẫn bị vô hiệu hóa trên giao diện).
* **Task 6.5.22 (PASS WITH LIMITATIONS):**
  * Đã harden co-owner policy: xóa một OWNER không xóa mềm workspace còn co-owner hợp lệ; từng workspace được đánh giá độc lập.
  * Đã harden restore provenance: chỉ workspace có `deleted_at` và `deleted_by_id` khớp sự kiện xóa OWNER mới được khôi phục.
  * Đã kiểm chứng rollback atomicity, stale session guards, cross-workspace isolation và data-retention bằng automated smoke suite.
  * Purge và `ActivityLog.workspace_id` vẫn chưa triển khai; manual PostgreSQL smoke vẫn là giới hạn còn lại.
  * Evidence: [OWNER/Workspace Lifecycle Smoke + Security Audit](OWNER_WORKSPACE_LIFECYCLE_SMOKE_SECURITY_AUDIT.md).
