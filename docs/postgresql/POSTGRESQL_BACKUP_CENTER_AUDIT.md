# PostgreSQL Backup Center Audit

## 1. Scope
Tài liệu này thực hiện audit (rà soát) toàn bộ Trung tâm sao lưu (Backup Center), cơ chế phân quyền (access control) và mức độ sẵn sàng sau khi tích hợp Google Auth/OAuth và cổng phê duyệt tài khoản (`approval_bp`).
- **Trạng thái hiện tại:** Hệ thống đang chạy ở chế độ PostgreSQL-only trên production (Railway).
- **Mục tiêu của audit:** Đảm bảo hệ thống SQLite legacy backup/restore cũ được cô lập hoàn toàn khi chạy PostgreSQL, tránh các thao tác ghi phá hủy hoặc xung đột dữ liệu từ giao diện, đồng thời chuẩn bị phương án mở lại Backup Center một cách an toàn cho PostgreSQL ở các sprint tiếp theo.

---

## 2. Current UI State
Hiện tại trên giao diện Cài đặt (`/settings`):
- **Thông báo cảnh báo (Alert warning):** Hiển thị ở trên cùng khu vực Sao lưu & Khôi phục với nội dung:
  > *“Tính năng sao lưu/khôi phục của SpaManager đang tạm khóa trong chế độ PostgreSQL. Vui lòng dùng quy trình sao lưu PostgreSQL theo runbook thay vì Backup Center.”*
- **Nút Tạo bản sao lưu:** Bị vô hiệu hóa (`disabled aria-disabled="true"`) kèm tooltip: *`Backup Center dang b? kha khi ch?y PostgreSQL`*.
- **Nút Nhập bản sao lưu:** Bị vô hiệu hóa với cấu hình tương tự nút tạo.
- **Nút Khôi phục (ở từng dòng danh sách bản sao lưu cũ):** Nút `btn-restore-backup` bị vô hiệu hóa nếu hệ thống phát hiện chạy PostgreSQL (`{% if b.status != 'Valid' or backup_engine == 'postgresql' %}disabled{% endif %}`).
- **Wording SQLite cũ:** Trong phần "Thông tin phần mềm" (`#card-about`), nhãn Cơ sở dữ liệu đang fix cứng hiển thị chữ `SQLite` (dòng 425-427 trong `templates/setting/index.html`), đây là điểm cần làm sạch ở sprint tiếp theo để đồng bộ với engine thực tế (`backup_engine`).

---

## 3. Current Routes
Tất cả các route liên quan đến Backup Center vẫn được khai báo trong blueprint `setting_bp` (`routes/setting.py`):
1. `/settings` (GET): Trang cài đặt chính, hiển thị Backup Center.
2. `/settings/backup` (POST): Tạo bản sao lưu mới.
3. `/settings/backup/download/<string:backup_id>` (GET): Tải xuống bản sao lưu cũ.
4. `/settings/backup/delete/<string:backup_id>` (POST): Xóa bản sao lưu vĩnh viễn trên đĩa và metadata.
5. `/settings/backup/notes/<string:backup_id>` (POST): Cập nhật ghi chú của bản sao lưu.
6. `/settings/backup/restore/<string:backup_id>` (POST): Phục hồi cơ sở dữ liệu từ ID bản sao lưu.
7. `/settings/backup/upload` (POST): Tải file backup từ ngoài lên để kiểm tra.
8. `/settings/restore-wizard/validate/<string:backup_id>` (GET): Xác thực bản sao lưu trong Restore Wizard.
9. `/settings/restore-wizard/confirm` (POST): Xác nhận khôi phục từ Wizard.
10. `/settings/restore` (POST): Khôi phục trực tiếp từ file upload lên.

**Quyền truy cập:**
- Các route này được bảo vệ ở mức blueprint qua hàm `@setting_bp.before_request`:
  ```python
  @setting_bp.before_request
  def _require_settings_permission():
      current_user = AuthService.get_current_active_user()
      if not current_user:
          abort(401)
      if not can_manage_settings(current_user):
          abort(403)
  ```
- Chỉ có vai trò quản trị (`OWNER` hoặc `ADMIN`) mới có quyền truy cập. Các vai trò khác (`STAFF`, `APPROVAL_OWNER`) và các tài khoản chưa được duyệt (`pending`, `rejected`, `disabled`) hoàn toàn bị chặn ở mức route.

---

## 4. Current Services
- **`backup_service.py` (`BackupService.create_backup`):**
  Chặn trực tiếp ở đầu hàm nếu không chạy SQLite:
  ```python
  if not BackupService.is_sqlite_database(app):
      app_logger.warning("Backup Center is disabled: only supported on SQLite databases...")
      return None, None, None
  ```
- **`restore_service.py` (`RestoreService.restore_database`):**
  Chặn trực tiếp ở đầu hàm nếu cấu hình cơ sở dữ liệu là PostgreSQL:
  ```python
  if is_postgresql_database(app.config.get('SQLALCHEMY_DATABASE_URI', '')):
      return False, get_postgresql_restore_guard_message()
  ```

---

## 5. Current Permission Model
- **OWNER / ADMIN:** Có quyền truy cập trang `/settings` và gọi các route Backup Center (nhưng hành động ghi/khôi phục bị chặn ở mức logic code nếu chạy PostgreSQL).
- **STAFF:** Bị chặn hoàn toàn, trả về lỗi 403 Forbidden.
- **APPROVAL_OWNER:** Bị chặn hoàn toàn. Do vai trò `APPROVAL_OWNER` không nằm trong danh sách quản trị (`MANAGER_ROLES = {OWNER, ADMIN}`), đồng thời `require_login()` toàn cục chuyển hướng tài khoản này về `/approval/pending`.
- **Pending/Rejected/Disabled Users:** Bị chặn truy cập toàn bộ hệ thống bởi `can_access_app` guard.

---

## 6. SQLite Legacy Findings
- Code xử lý SQLite backup/restore trong `BackupService` và `RestoreService` vẫn tồn tại đầy đủ và đóng vai trò fallback/test-only.
- Route tải xuống (`/settings/backup/download/<string:backup_id>`) và xóa file (`/settings/backup/delete/<string:backup_id>`) không bị chặn PostgreSQL trực tiếp vì đây là các tác vụ đọc/xóa file cũ trên đĩa vật lý, không ảnh hưởng đến PostgreSQL database hiện tại.
- Các route upload file `.db`/`.sqlite` khôi phục đều bị chặn chặn cứng bằng cảnh báo an toàn từ `utils/database_engine.py` nên không thể chạy hoặc ghi đè dữ liệu.

---

## 7. PostgreSQL Policy Findings
- **Nhận diện chế độ:** Hệ thống nhận diện chế độ PostgreSQL động qua phân tích chuỗi kết nối `SQLALCHEMY_DATABASE_URI`.
- **Chính sách Production:**
  - Tuyệt đối không phục hồi (restore) tự động thông qua giao diện web để tránh nguy cơ timeout, nghẽn luồng kết nối, và lỗi dữ liệu dở dang.
  - Mọi thao tác phục hồi dữ liệu trên production phải được tiến hành thủ công bằng CLI command (như `pg_restore`) thông qua các runbook vận hành ngoài phạm vi ứng dụng Web.
  - Sao lưu tự động trên production sử dụng cơ chế Backup tự động của nhà cung cấp hạ tầng (Railway Postgres database-level backups).

---

## 8. OAuth/Approval Guard Findings
Tài khoản Google mới đăng nhập (chưa được duyệt) hoặc tài khoản bị vô hiệu hóa/từ chối hoàn toàn không có khả năng tiếp cận Backup Center hay bất kỳ route nào của SpaManager.
- Trạng thái `approval_status == 'pending'` ngăn cản hàm `can_access_app` trả về `True`.
- Guard toàn cục `require_login` kiểm tra trạng thái này trước khi xử lý route, đảm bảo an toàn tuyệt đối.

---

## 9. Risks
- **Branding nhầm lẫn:** Trực quan phần mềm vẫn báo chạy trên `SQLite` dù thực tế đang chạy `PostgreSQL`, tạo cảm giác hệ thống chưa đồng bộ.
- **Bypass Client-side:** Nút bấm trên UI chỉ bị disabled ở client. Nếu admin cố ý gửi POST request đến `/settings/backup` hoặc `/settings/restore`, ứng dụng vẫn nhận request nhưng rất may mắn là route backend và service layer đã cài đặt sẵn chốt chặn PostgreSQL nên yêu cầu sẽ bị từ chối an toàn với mã lỗi 400.

---

## 10. Recommended Next Tasks
Để mở lại Backup Center hoặc cải thiện trải nghiệm vận hành với PostgreSQL ở các sprint tiếp theo, khuyến nghị thực hiện các task sau:
1. **Task 6.4.2 UI policy definition:** Xác định rõ ràng các chức năng PostgreSQL-aware được hỗ trợ trên giao diện (ví dụ: chỉ cho phép tạo backup PostgreSQL qua pg_dump từ UI, tải xuống `.dump` file, nhưng cấm tuyệt đối tính năng Khôi phục/Restore trực tiếp từ UI).
2. **Task 6.4.3 PostgreSQL-aware UI cleanup:** Thay đổi nhãn Cơ sở dữ liệu trong `#card-about` hiển thị động theo `backup_engine` (SQLite hoặc PostgreSQL).
3. **Task 6.4.4 Route reopen guard:** Định cấu hình mở lại các endpoint tạo backup PostgreSQL, gọi lệnh `pg_dump` an toàn và ghi nhận metadata tương tự luồng SQLite cũ.
4. **Task 6.4.5 Integration tests:** Viết thêm integration test kiểm tra luồng tạo backup PostgreSQL ảo (mock) và tải xuống file `.dump`.
