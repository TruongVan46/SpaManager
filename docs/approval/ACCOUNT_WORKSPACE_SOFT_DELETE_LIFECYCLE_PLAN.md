# Kế hoạch Thiết kế Vòng đời Xóa mềm Tài khoản & Workspace (Account/Workspace Soft Delete Lifecycle Plan)

## 1. Mục tiêu (Purpose)
Tài liệu này đề xuất phương án thiết kế hệ thống và vòng đời cho việc **xóa mềm (soft-delete) tài khoản người dùng** và **xóa mềm workspace** trong hệ thống SpaManager.
Mục tiêu chính:
* Đảm bảo tính an toàn dữ liệu trên production (production-safe).
* Hỗ trợ khôi phục hoàn toàn (fully restorable) khi có thao tác nhầm lẫn.
* Hỗ trợ chính sách dọn dẹp dữ liệu vĩnh viễn (purge/permanent delete policy) theo giai đoạn mà không gây mâu thuẫn ràng buộc khóa ngoại (integrity constraints) trong PostgreSQL.
* Đảm bảo các hoạt động này không làm rò rỉ dữ liệu hoặc phá hỏng tính năng cô lập workspace hiện tại.

---

## 2. Trạng thái hiện tại (Current State)
* **Bảng User:**
  * Có các trường quản lý phê duyệt và kích hoạt: `is_active` (Boolean), `approval_status` (pending, active, rejected, disabled).
  * Chưa có cơ chế đánh dấu xóa mềm chuyên biệt (ví dụ: `deleted_at`).
* **Bảng Workspace:**
  * Có trường `status` (active, pending, suspended, archived).
  * Chưa có cơ chế đánh dấu xóa mềm chuyên biệt (`deleted_at`).
* **Bảng WorkspaceMember:**
  * Đã được nâng cấp ở Task 6.5.12 (Migration 0005): Thêm các trường metadata xóa mềm: `status` (có giá trị `"removed"`), `removed_at`, `removed_by_id`, `removal_reason`.
  * Hỗ trợ đầy đủ việc xóa mềm nhân viên (STAFF/ADMIN) ra khỏi một workspace cụ thể.
* **Các thực thể kinh doanh (Customer, Service, Appointment, Invoice):**
  * Đều đã có cơ chế xóa mềm tích hợp: Cột `deleted_at` (DateTime) và `deleted_by` (String).
* **Cài đặt (Setting):**
  * Được lưu theo cặp `key`-`value` và được lọc theo `workspace_id`. Không có cột xóa mềm riêng.
* **Nhật ký hoạt động (ActivityLog):**
  * Chỉ lưu `user_id` thực hiện hành động. Chưa có cột `workspace_id` để phân nhóm log hoạt động theo từng workspace riêng biệt.
* **Thùng rác (Recycle Bin):**
  * Đang hỗ trợ khôi phục và xóa vĩnh viễn mức tenant đối với 4 thực thể kinh doanh: `Customer`, `Service`, `Appointment`, và `Invoice`.
  * Chưa và không nên hỗ trợ hiển thị `User` hoặc `Workspace` bị xóa mềm tại đây (việc quản lý tài khoản/workspace bị xóa thuộc thẩm quyền hệ thống của `APPROVAL_OWNER` thông qua Approval Portal).

---

## 3. Các điểm nghẽn hiện tại (Current Blockers)
* **Thiếu các cột đánh dấu xóa mềm:** Bảng `users` và `workspaces` chưa có cột `deleted_at`, `deleted_by_id`, `deletion_reason`.
* **Chưa có cơ chế liên đới xóa mềm (Cascade Soft-delete):** Khi một tài khoản `OWNER` bị xóa mềm, workspace tương ứng và toàn bộ nhân viên trong đó vẫn ở trạng thái hoạt động bình thường, gây mâu thuẫn logic phân quyền.
* **FK Constraints trong PostgreSQL:** Nếu thực hiện xóa cứng (hard-delete) workspace hoặc user, cơ sở dữ liệu sẽ trả về lỗi vi phạm ràng buộc khóa ngoại (Foreign Key Violation) từ các bảng liên quan như `appointments`, `invoices`, `settings`, `activity_logs`.
* **Nhật ký hoạt động thiếu Workspace Context:** `ActivityLog` không có `workspace_id` làm cho việc lọc lịch sử hoặc dọn dẹp lịch sử của một workspace bị xóa vĩnh viễn gặp khó khăn và kém tối ưu hiệu năng.

---

## 4. Đề xuất Schema Migration tương lai
Đề xuất tạo migration tiếp theo (ví dụ: `0006_account_workspace_soft_delete`), nhưng **KHÔNG** tạo file thực tế trong task thiết kế này.

### 4.1. Bảng `users` (User)
Thêm các cột mới (tất cả đều cho phép `NULL` để đảm bảo an toàn nâng cấp):
* `deleted_at`: DateTime (nullable) - Đánh dấu thời điểm tài khoản bị xóa mềm.
* `deleted_by_id`: Integer (nullable) - FK liên kết tới `users.id` của người thực hiện xóa (thường là `APPROVAL_OWNER`).
* `deletion_reason`: String(255) (nullable) - Lý do xóa tài khoản.
* *Khuyến nghị:* Dùng `deleted_at IS NOT NULL` để đánh dấu xóa mềm thay vì ghi đè lên `approval_status` (để giữ nguyên trạng thái trước khi xóa phục vụ việc khôi phục chính xác).

### 4.2. Bảng `workspaces` (Workspace)
Thêm các cột mới:
* `deleted_at`: DateTime (nullable) - Đánh dấu thời điểm workspace bị xóa mềm.
* `deleted_by_id`: Integer (nullable) - FK liên kết tới `users.id` thực hiện xóa.
* `deletion_reason`: String(255) (nullable) - Lý do xóa workspace.

### 4.3. Bảng `workspace_members` (WorkspaceMember)
Đã đủ trường cần thiết từ Migration 0005. Tuy nhiên, có thể bổ sung cột:
* `removal_scope`: String(50) (nullable) - Nhận diện việc xóa thành viên là do "STAFF_REMOVAL" đơn lẻ hay do "WORKSPACE_CASCADE_DELETE" (khi workspace bị xóa).

### 4.4. Bảng `activity_logs` (ActivityLog)
* *Khuyến nghị tách rời:* Để tránh rủi ro khi chỉnh sửa bảng nhật ký có lượng dữ liệu lớn trên production, việc bổ sung cột `workspace_id` (Integer, FK tới `workspaces.id` ON DELETE SET NULL) và thực hiện chạy script backfill lịch sử log cũ **sẽ được tách riêng ra khỏi migration 0006**. Thao tác này sẽ được xử lý ở một task và migration riêng biệt sau này (ví dụ migration `0007_activity_log_workspace_id`) để tiến hành audit độc lập.

---

## 5. Vòng đời Xóa mềm Tài khoản (Account Soft Delete Lifecycle)
* **Quyền hạn:** Chỉ tài khoản có vai trò `APPROVAL_OWNER` mới được quyền xóa mềm tài khoản của người dùng khác hệ thống thông qua Approval Portal.
* **Nguyên tắc an toàn:** Không cho phép tự xóa chính mình hoặc xóa các tài khoản `APPROVAL_OWNER` khác.
* **Khi xóa tài khoản STAFF / ADMIN:**
  1. Gán `User.deleted_at = utc_now()`, `User.deleted_by_id = current_user.id`, `User.deletion_reason = reason`.
  2. Vô hiệu hóa quyền đăng nhập của tài khoản (ghi đè logic `can_access_app` để trả về `False` nếu `deleted_at` khác null).
  3. Cập nhật trạng thái tất cả liên kết thành viên của tài khoản này thành `"removed"` trong bảng `workspace_members`.
  4. Giữ nguyên toàn bộ lịch sử hoạt động và dữ liệu nghiệp vụ của nhân viên này tạo ra trước đó.
  5. Ghi nhận Activity Log sự kiện xóa tài khoản hệ thống.
* **Khi xóa tài khoản OWNER:**
  1. Thực hiện các bước xóa mềm tài khoản tương tự như STAFF.
  2. Tự động kích hoạt luồng xóa mềm liên đới (cascade) toàn bộ các Workspace thuộc sở hữu chính của OWNER này.

---

## 6. Vòng đời Xóa mềm Workspace (Workspace Soft Delete Lifecycle)
* **Trạng thái xóa mềm:** Một workspace được coi là bị xóa mềm khi `workspaces.deleted_at IS NOT NULL`.
* **Ẩn thông tin lập tức:**
  1. Các bộ chọn workspace (workspace selector) và dịch vụ tự động gán workspace khi đăng nhập (`ensure_current_workspace_session`) phải lọc bỏ các workspace bị xóa mềm.
  2. Bất kỳ request nào cố ý truy cập workspace đã bị xóa mềm bằng ID trực tiếp sẽ bị chặn lập tức và trả về lỗi 404 (Fail-closed).
* **Quản lý dữ liệu nghiệp vụ:**
  * Nhờ cơ chế lọc workspace ở cấp truy vấn toàn cục (`WorkspaceService.scoped_query`), toàn bộ dữ liệu nghiệp vụ của workspace bị xóa mềm sẽ tự động ẩn đi mà không cần lặp qua từng bản ghi `Customer`/`Appointment`/`Invoice` để ghi `deleted_at`. Điều này giúp tối ưu hóa hiệu năng cơ sở dữ liệu trên production.

---

## 7. Vòng đời Khôi phục (Restore Lifecycle)
* **Quyền hạn:** Chỉ `APPROVAL_OWNER` mới có thể khôi phục tài khoản hoặc workspace bị xóa mềm.
* **Quy trình Khôi phục Workspace:**
  1. Đặt `deleted_at = None`, `deleted_by_id = None`, `deletion_reason = None` trên bảng `workspaces`.
  2. Workspace sẽ hiển thị trở lại bình thường. Dữ liệu nghiệp vụ hiển thị lại ngay lập tức.
* **Quy trình Khôi phục Tài khoản:**
  1. Đặt `deleted_at = None`, `deleted_by_id = None`, `deletion_reason = None` trên bảng `users`.
  2. Khôi phục trạng thái thành viên workspace tương ứng (`status = "active"` cho các liên kết có `removal_scope` là cascade).
  3. Giữ nguyên trạng thái `is_active` và `approval_status` gốc của tài khoản trước khi xóa (nếu trước khi xóa tài khoản bị disabled/rejected thì sau khi restore vẫn giữ nguyên trạng thái đó để bảo mật).

---

## 8. Chính sách Xóa vĩnh viễn (Permanent Delete / Purge Policy)
* **Quy tắc an toàn:**
  * Chỉ được phép thực hiện xóa vĩnh viễn (purge) đối với các đối tượng đã được chuyển sang trạng thái xóa mềm (soft-deleted).
  * Yêu cầu xác thực hai yếu tố (2FA) hoặc nhập chuỗi xác nhận bắt buộc.
  * Tự động sao lưu (backup) cơ sở dữ liệu trước khi thực hiện dọn dẹp.
  * Thiết lập thời gian lưu trữ tối thiểu (retention period), ví dụ: dữ liệu xóa mềm sẽ được lưu giữ ít nhất 30 hoặc 60 ngày trước khi cho phép purge vĩnh viễn.
* **Quy trình giải phóng khóa ngoại (Purge Sequence):**
  Để tránh lỗi khóa ngoại trong PostgreSQL, thứ tự dọn dẹp phải tuân thủ nghiêm ngặt:
  1. `invoices` và `invoice_details`
  2. `appointments`
  3. `customers`
  4. `services`
  5. `settings` (các bản ghi cài đặt của workspace đó)
  6. `workspace_members`
  7. `workspaces`
  8. `users` (nếu xóa vĩnh viễn tài khoản người dùng)
  9. `activity_logs`: Đề xuất ẩn danh (anonymize) thay vì xóa hoàn toàn để phục vụ công tác đối soát an ninh hệ thống sau này.

---

## 9. Đề xuất Giao diện (UI/UX Proposal)
* **Danh sách tài khoản hệ thống (Approval Portal):**
  * Thêm bộ lọc Tab: "Đang hoạt động" và "Đã xóa mềm".
  * Tài khoản đã xóa mềm sẽ hiển thị kèm nút "Khôi phục" (Restore) và nút "Xóa vĩnh viễn" (Purge).
* **Hộp thoại xác nhận (Confirmation Modals):**
  * Khi bấm xóa tài khoản OWNER: Hiển thị cảnh báo màu đỏ thông báo rõ ràng rằng toàn bộ workspace tương ứng và dữ liệu của nó cũng sẽ bị xóa mềm liên đới.
  * Yêu cầu nhập đúng username của tài khoản hoặc tên slug của workspace để xác nhận hành động.

---

## 10. Cơ chế Kiểm soát Quyền và Bảo mật
* **Chặn đăng nhập:** Hàm `can_access_app` trong model `User` sẽ được bổ sung điều kiện chặn:
  ```python
  @property
  def can_access_app(self):
      return bool(self.is_active and self.is_approval_active and not self.deleted_at)
  ```
* **Chặn chọn workspace:** Cập nhật điều kiện truy vấn trong `ensure_current_workspace_session`:
  ```python
  Workspace.query.filter(Workspace.id == id, Workspace.deleted_at.is_(None))
  ```

---

## 11. Các ca kiểm thử cần thiết (Tests Needed)
1. **Kiểm thử xóa mềm Staff/Admin:** Xác nhận tài khoản bị đánh dấu `deleted_at`, không thể đăng nhập, biến mất khỏi danh sách hoạt động của hệ thống.
2. **Kiểm thử xóa mềm Owner:** Xác nhận tài khoản Owner bị xóa mềm kéo theo toàn bộ Workspace liên kết bị đánh dấu `deleted_at`.
3. **Kiểm thử truy cập Workspace bị xóa:** Xác nhận người dùng khác không thể truy cập hoặc truy vấn dữ liệu thuộc workspace đã xóa mềm (trả về 404).
4. **Kiểm thử khôi phục Workspace:** Xác nhận khôi phục thành công, hiển thị đầy đủ dữ liệu nghiệp vụ nguyên vẹn.
5. **Kiểm thử khôi phục tài khoản bị khóa trước đó:** Xác nhận sau khi khôi phục, tài khoản vẫn ở trạng thái khóa gốc (`is_active = False`).
6. **Kiểm thử thứ tự Purge vĩnh viễn:** Xác nhận việc dọn dẹp cơ sở dữ liệu trên PostgreSQL không bị lỗi vi phạm ràng buộc khóa ngoại.

---

## 12. Lộ trình Triển khai Đề xuất (Recommended Implementation Breakdown)
Hệ thống được chia thành các bước nhỏ tuần tự để đảm bảo kiểm soát chất lượng chặt chẽ:
* **Giai đoạn 1 (Task 6.5.15):** Tạo migration `0006` chỉ bổ sung các cột xóa mềm nullable (`deleted_at`, `deleted_by_id`, `deletion_reason`) vào hai bảng `users` và `workspaces`.
* **Giai đoạn 1a (Task 6.5.15a / Tương lai):** Tạo migration `0007` riêng biệt để bổ sung cột `workspace_id` vào bảng `activity_logs` cùng script backfill an toàn (nhằm tách rời rủi ro của bảng log có khối lượng dữ liệu lớn).
* **Giai đoạn 2 (Task 6.5.16):** Xây dựng logic nghiệp vụ (Service) và giao diện Approval Portal phục vụ việc xóa mềm tài khoản Staff/Admin/Owner.
* **Giai đoạn 3 (Task 6.5.17):** Cập nhật hệ thống Middleware, AuthService và Workspace Isolation để ẩn và chặn toàn bộ truy cập vào các Workspace và tài khoản đã bị xóa mềm.
* **Giai đoạn 4 (Task 6.5.18):** Triển khai tính năng Khôi phục (Restore) tài khoản và workspace.
* **Giai đoạn 5 (Task 6.5.19):** Triển khai cơ chế Dọn dẹp vĩnh viễn (Purge) theo thứ tự ưu tiên khóa ngoại kèm theo thông báo xác nhận an toàn.
* **Giai đoạn 6 (Task 6.5.20):** Kiểm toán an toàn (Security & Production-readiness audit) toàn diện trước khi phát hành chính thức.

---

## 13. Những mục tiêu nằm ngoài phạm vi (Explicit Non-goals)
* Không viết bất kỳ mã nguồn chạy runtime nào trong giai đoạn thiết kế.
* Không tạo bất kỳ file migration vật lý nào trong dự án tại task này.
* Không chỉnh sửa hay thay đổi bất kỳ dữ liệu nào hiện có trên môi trường Production.
* Không thực hiện dọn dẹp hoặc xóa cứng bất kỳ dữ liệu lịch sử nào trong giai đoạn đầu tiên của quá trình triển khai sau này.

---

## 14. Các câu hỏi mở cần thảo luận (Open Questions)
1. **Hỗ trợ Owner sở hữu nhiều Workspace:** Nếu một tài khoản OWNER làm chủ nhiều workspace khác nhau, khi xóa tài khoản OWNER đó, hệ thống có nên xóa mềm toàn bộ các workspace đó hay yêu cầu chuyển nhượng quyền sở hữu (transfer ownership) trước khi xóa?
2. **Thời gian lưu trữ tối thiểu (Retention Period):** Nên quy định thời gian lưu trữ tối thiểu của dữ liệu xóa mềm trước khi được phép Purge là bao lâu? (Gợi ý: 30 ngày).
3. **Ẩn danh hay Xóa nhật ký hoạt động (ActivityLog Purging):** Khi thực hiện Purge vĩnh viễn một tài khoản, chúng ta nên xóa sạch ActivityLog của họ hay chỉ ẩn danh thông tin cá nhân (anonymize) của họ để giữ lại lịch sử đối soát hệ thống?

---

## 15. Trạng thái thực tế triển khai (Actual Implementation Status)
* **Task 6.5.16 (DONE):**
  * Đã triển khai chức năng xóa mềm tài khoản **STAFF/ADMIN** ở cấp hệ thống thông qua Approval Portal.
  * Chỉ `APPROVAL_OWNER` được quyền xóa mềm.
  * Không cho phép xóa chính mình, không cho phép xóa tài khoản `APPROVAL_OWNER` khác.
  * Không cho phép xóa tài khoản `OWNER` trong task này (sẽ xử lý ở bước workspace lifecycle riêng sau).
  * Tài khoản đã xóa mềm được ẩn khỏi các danh sách hoạt động, xuất hiện trong tab "Đã xóa mềm" trên Approval Portal.
  * Tài khoản đã xóa mềm có `can_access_app` trả về `False` và bị chặn đăng nhập/truy cập hoàn toàn.
* **Task 6.5.17 (DONE):**
  * Đã triển khai chức năng khôi phục tài khoản **STAFF/ADMIN** đã bị xóa mềm thông qua Approval Portal.
  * Chỉ `APPROVAL_OWNER` được quyền khôi phục.
  * Khi khôi phục: gán `deleted_at = None`, `deleted_by_id = None`, `deletion_reason = None`.
  * Nếu trạng thái duyệt là `active`, khôi phục quyền đăng nhập (`is_active = True`). Nếu không, giữ nguyên `is_active = False` để đảm bảo an toàn.
  * Không cho phép khôi phục tài khoản `OWNER` trong task này (sẽ được xử lý ở bước workspace lifecycle riêng sau).
  * Giao diện tab "Đã xóa mềm" đã kích hoạt nút "Khôi phục" với hộp thoại xác nhận.
  * Chức năng **Xóa vĩnh viễn (Purge)** vẫn chưa được triển khai (nút thao tác vẫn bị vô hiệu hóa trên giao diện).
* **Task 6.5.18 (DONE):**
  * Đã thực hiện audit mã nguồn và hoàn thành tài liệu [Kế hoạch chuẩn bị vòng đời Xóa mềm OWNER + Workspace](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/docs/approval/OWNER_WORKSPACE_SOFT_DELETE_READINESS_PLAN.md).
  * Phân tích rõ hiện trạng, thiết lập các rule xóa mềm/khôi phục OWNER/workspace, đề xuất các guard bắt buộc, thiết kế giao diện UI/UX và lộ trình chia nhỏ task cụ thể cho tương lai.
* **Task 6.5.19 / 6.5.19a (DONE):**
  * Đã triển khai và củng cố toàn bộ các **lớp bảo vệ runtime (guards)** đối với Workspace đã bị xóa mềm (`deleted_at is not None`).
  * `WorkspaceService.is_user_in_workspace` tự động trả về `False` nếu workspace đích bị xóa mềm.
  * Tầng session và helper workspace tự động clear context và fail-closed nếu workspace hiện hành bị xóa mềm.
  * Tầng truy vấn toàn cục `scoped_query` và logic `assign_workspace` tự động chặn đứng việc đọc/ghi dữ liệu nghiệp vụ thuộc workspace đã xóa mềm (kể cả trong môi trường unit test).
* **Task 6.5.20 (DONE):**
  * Đã triển khai hoàn chỉnh chức năng **Xóa mềm OWNER + Workspace** liên quan từ Approval Portal.
  * Khi APPROVAL_OWNER thực hiện xóa mềm OWNER: tài khoản OWNER bị set `is_active = False` và gán thông tin xóa mềm. Đồng thời, toàn bộ workspace đang hoạt động do OWNER sở hữu cũng bị gán `deleted_at = datetime.utcnow()`.
  * OWNER đã bị xóa mềm sẽ xuất hiện trên danh sách "Đã xóa mềm", nút "Khôi phục" đối với OWNER vẫn bị vô hiệu hóa an toàn (chờ triển khai ở giai đoạn sau).
  * Chức năng **Xóa vĩnh viễn (Purge)** vẫn chưa được triển khai (nút thao tác vẫn bị vô hiệu hóa trên giao diện).
