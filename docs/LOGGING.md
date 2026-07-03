# Logging Framework Specification – SpaManager

Tài liệu này đặc tả cơ chế ghi nhật ký hệ thống (Logging) trong SpaManager, cách phân biệt các loại nhật ký và quy tắc viết log chuẩn.

---

## 1. Phân biệt các Phân hệ Nhật ký (Logging Classification)

Hệ thống SpaManager phân biệt rõ ràng giữa 2 phân hệ nhật ký hoàn toàn độc lập:

1. **System Log (Nhật ký hệ thống)**:
   * **Mục đích**: Ghi lại vòng đời ứng dụng, các sự kiện nghiệp vụ nền, lỗi hệ thống và các vấn đề bảo mật.
   * **Lưu trữ**: Lưu vào các file tệp tin (.log) trên đĩa cứng có cơ chế quay vòng (Log Rotation).
   * **Đối tượng đọc**: Quản trị viên hệ thống, Lập trình viên kiểm tra lỗi (Debug).

2. **Activity Log (Nhật ký thao tác)**:
   * **Mục đích**: Ghi lại lịch sử hoạt động có chủ đích của người dùng để phục vụ tra cứu trên giao diện Admin.
   * **Lưu trữ**: Lưu trong cơ sở dữ liệu SQLite (bảng `activity_logs`).
   * **Đối tượng đọc**: Chủ Spa (Owner) giám sát hoạt động của nhân viên.

---

## 2. Cấu trúc và tệp tin System Log (`logs/`)

Các tệp tin nhật ký hệ thống được lưu trong thư mục `/logs` ở gốc dự án và được chia thành 3 tệp tin chuyên biệt:

### A. `application.log`
* **Nhiệm vụ**: Ghi nhận các sự kiện hoạt động bình thường ở mức độ nghiệp vụ chung.
* **Các sự kiện cần ghi**:
  * Khởi động/Dừng hệ thống.
  * Bắt đầu và kết thúc quá trình Excel Import/Export.
  * Các sự kiện Sao lưu (Backup) và Phục hồi (Restore) cơ sở dữ liệu.
  * Hoàn thành các tác vụ nền định kỳ (Cron Jobs).
* **Mức độ log**: `INFO` hoặc `WARNING`.

### B. `error.log`
* **Nhiệm vụ**: Chỉ ghi nhận các lỗi, sự cố phát sinh ngoài ý muốn.
* **Các sự kiện cần ghi**:
  * Exception hệ thống (`SpaManagerException`, `ValueError`, v.v.).
  * Lỗi cơ sở dữ liệu (`IntegrityError`, `OperationalError`).
  * Lỗi đọc ghi tệp tin (`IOError`).
* **Mức độ log**: `ERROR` hoặc `CRITICAL` kèm theo **Stack Trace** chi tiết.

### C. `security.log`
* **Nhiệm vụ**: Chỉ ghi nhận các sự kiện bảo mật, kiểm toán tài khoản.
* **Các sự kiện cần ghi**:
  * Đăng nhập thành công / thất bại.
  * Đăng xuất.
  * Thay đổi mật khẩu tài khoản.
  * Truy cập trái phép / Phân quyền bị từ chối (`PermissionDeniedException`).
* **Mức độ log**: `INFO` (cho sự kiện thành công) hoặc `WARNING`/`ERROR` (cho sự kiện thất bại hoặc truy cập trái phép).

---

## 3. Định dạng Nhật ký (Log Format)

### A. Định dạng ghi file (File Format)
Tất cả các file nhật ký sử dụng chung định dạng đa dòng (multi-line) rõ ràng, dễ phân tích:

* **Sự kiện thông thường**:
  ```text
  [2026-06-29 14:30:12]
  INFO
  IMPORT
  Imported 15 customers from Excel successfully.
  ```

* **Sự kiện lỗi (kèm Stack Trace)**:
  ```text
  [2026-06-29 14:32:05]
  ERROR
  DATABASE
  sqlite3.IntegrityError: UNIQUE constraint failed: users.username
  Traceback (most recent call last):
    File "routes/auth.py", line 45, in register
      db.session.commit()
  ```

### B. Định dạng hiển thị Console (Development Mode)
Khi chạy ở chế độ **Development (`app.debug = True`)**, log sẽ hiển thị có màu trên Terminal để dễ quan sát trực quan:
* `INFO` - Màu xanh lá (Green)
* `WARNING` - Màu vàng (Yellow)
* `ERROR` - Màu đỏ (Red)
* `CRITICAL` - Màu tím (Magenta)

---

## 4. Cấu hình quay vòng nhật ký (Log Rotation)

Để tránh dung lượng file log tăng vô hạn làm tràn đĩa cứng:
* Cấu hình quay vòng tự động bằng `RotatingFileHandler`.
* Dung lượng tối đa: **5 MB** mỗi file (`LOG_ROTATION_SIZE = 5 * 1024 * 1024`).
* Số lượng file lưu giữ tối đa: **5 file** gần nhất (`LOG_BACKUP_COUNT = 5`).

---

## 5. Quy tắc và Bảo mật đối với Lập trình viên

> [!CAUTION]
> **Tuyệt đối KHÔNG ghi các thông tin nhạy cảm vào log file dù ở bất kỳ level nào:**
> * Mật khẩu dạng rõ (Plaintext password).
> * Mật khẩu đã băm (Password Hash).
> * Token xác thực (API Token, JWT).
> * Session ID hoặc thông tin Cookie.

> [!IMPORTANT]
> **Không sử dụng hàm `print()` trần để debug trong code sản phẩm:**
> * Sử dụng `app_logger.debug(...)` khi cần ghi log debug.
> * Sử dụng `app_logger.audit(...)` cho các sự kiện kiểm toán đặc thù.
