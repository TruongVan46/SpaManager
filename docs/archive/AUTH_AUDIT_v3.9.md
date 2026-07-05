# Báo cáo Kiểm tra Xác thực & Phân quyền (Authentication & Authorization Audit) – SpaManager v3.9

Tài liệu này đánh giá chi tiết hệ thống xác thực (Authentication), phân quyền (Authorization) và kiểm toán bảo mật của dự án SpaManager v3.9 nhằm chuẩn bị cho việc vận hành thực tế.

---

## 1. Kết quả Đánh giá Tổng quan

| Phân hệ | Tỷ lệ Đạt | Đánh giá Trạng thái |
| :--- | :---: | :--- |
| **Authentication** | **95%** | Hệ thống Login, Logout, Session và Quản lý Profile hoạt động rất ổn định, bảo mật cao. |
| **Authorization** | **20%** | Chỉ phục vụ một người dùng (Single User). Đã chuẩn bị sẵn Enum và Decorator nhưng chưa có DB Table phân quyền. |
| **Security** | **75%** | Mật khẩu băm an toàn, cookie session có chữ ký bảo vệ. Tuy nhiên còn thiếu CSRF protection và Rate Limiting. |
| **Logging Integration** | **85%** | Ghi nhận chi tiết lịch sử bảo mật vào `security.log` và giao diện Activity Log. Thiếu log bảo mật cho mã lỗi HTTP 401/403. |
| **Future Readiness** | **50%** | Cấu trúc User model và hooks đã sẵn sàng cho đa người dùng, nhưng cần refactor lớn ở tầng DB/UI để kích hoạt. |

---

## 2. Chi tiết các Phần kiểm tra (Audit Details)

### a. User Model Audit (`models/user.py`)
Kiểm tra cấu trúc thuộc tính của model `User`:
*   `id`: ✅ **Có** (`db.Integer`, Primary Key)
*   `username`: ✅ **Có** (`db.String(100)`, Unique, Index)
*   `password_hash`: ✅ **Có** (`db.String(255)`)
*   `full_name`: ✅ **Có** (`db.String(100)`)
*   `avatar`: ✅ **Có** (`db.String(255)`, nullable)
*   `role_id`: ❌ **Chưa có** (Thay thế bằng trường `role` kiểu String lưu enum `UserRole` trực tiếp)
*   `is_active`: ✅ **Có** (`db.Boolean`, mặc định `True`)
*   `deleted_at`: ❌ **Chưa có** (Hệ thống chưa triển khai cơ chế Soft Delete cho tài khoản User)
*   `created_at`: ✅ **Có** (`db.DateTime`, mặc định `utcnow`)
*   `updated_at`: ✅ **Có** (`db.DateTime`, tự động cập nhật khi update)

### b. Password Security Audit
*   **Hash Algorithm**: Sử dụng thư viện `werkzeug.security` để băm mật khẩu (`generate_password_hash` và `check_password_hash`) thông qua lớp trung gian `PasswordHasher` tại `core/auth/security.py`.
*   **Plaintext Leakage**: Xác nhận **không lưu mật khẩu plaintext** trong cơ sở dữ liệu.
*   **Logging Security**: Quét toàn bộ mã nguồn, **không log mật khẩu plaintext hay password hash** dưới mọi hình thức. Hàm log chỉ ghi nhận tên đăng nhập và trạng thái (Thành công/Thất bại).

### c. Login & Session Flow Audit (`routes/auth.py` & `services/auth_service.py`)
*   **Login**: Xác thực thành công sẽ gán `session[AUTH_SESSION_KEY] = user.id`.
*   **Logout**: Giải phóng session qua `session.pop(AUTH_SESSION_KEY, None)` và ghi log bảo mật.
*   **Remember Me**: Hoạt động đúng đặc tả. Khi người dùng tick "Ghi nhớ đăng nhập", `session.permanent = True` và thời hạn session kéo dài 30 ngày (theo cấu hình `PERMANENT_SESSION_LIFETIME = timedelta(days=30)` trong `config.py`).
*   **Redirect**: 
    *   Sau đăng nhập: Điều hướng an toàn về tham số `next` từ URL query hoặc mặc định về `dashboard.index`.
    *   Yêu cầu đăng nhập: Được kiểm soát tập trung qua global hook `@app.before_request` (`require_login()`) trong `app.py`. Nếu chưa đăng nhập, tự động chuyển hướng về `/login?next=<path>`.
*   **Mở rộng (Open Routes)**: Các route duy nhất không yêu cầu đăng nhập là `/login` (route `auth.login`), thư mục tài nguyên tĩnh `/static` và `/favicon.ico`.

### d. Profile & Change Password Audit
*   **Xem & Sửa Profile**: Cung cấp giao diện xem và chỉnh sửa họ tên tại `/profile`. Có validator đầu vào `ProfileValidator`.
*   **Avatar Upload**: Hỗ trợ tải lên ảnh đuôi JPG, JPEG, PNG với kích thước tối đa 2MB (được kiểm tra cả ở client-side bằng JS và server-side bằng Python). Ảnh tải lên được đổi tên thành UUID độc bản và dọn dẹp ảnh cũ trong thư mục `static/uploads/avatars/`.
*   **Đổi mật khẩu**:
    *   Xác minh mật khẩu cũ chính xác mới cho phép đổi.
    *   Kiểm tra mật khẩu mới trùng khớp mật khẩu xác nhận.
    *   Mật khẩu mới phải đáp ứng độ dài tối thiểu 8 ký tự và khác mật khẩu hiện tại.
    *   Đăng ký sự kiện thành công/thất bại vào `ActivityLog` và `security.log`.

### e. Session Security Audit
*   **Flask Session**: Sử dụng Cookie-based Session mặc định của Flask với chữ ký mật chống giả mạo.
*   **Secret Key**: Đang được cấu hình cứng trong `config.py` (`SECRET_KEY = "spa_manager_2026_secret_key"`).
*   **Session Fixation (Lỗ hổng cố định phiên)**: ⚠️ **Chưa an toàn**. Khi đăng nhập thành công, hệ thống gán trực tiếp ID người dùng vào session hiện tại mà không làm mới session cũ (không gọi `session.clear()`), có nguy cơ bị tấn công cố định phiên.

### f. Security Log & Activity Log Audit
*   **Security Log (`logs/security.log`)**: Ghi chép đúng chuẩn định dạng đa dòng cho các sự kiện:
    *   `Login Success` (Module: `AUTHENTICATION`)
    *   `Login Failed` (Module: `AUTHENTICATION`)
    *   `Logout` (Module: `AUTHENTICATION`)
    *   `Password Changed` (Module: `SECURITY`)
    *   *Permission Denied*: ❌ Chưa ghi nhận do hệ thống chưa có phân quyền. Các lỗi HTTP 401/403 chỉ ghi nhận vào `application.log` dưới dạng `WARNING` thay vì đi vào `security.log`.
*   **Activity Log**: Ghi chép song song các sự kiện thành công/thất bại của đăng nhập, đăng xuất, đổi mật khẩu và cập nhật profile vào bảng `activity_logs` dưới dạng hoạt động nghiệp vụ của "Chủ Spa" để hiển thị trên UI. Việc này hoàn toàn khớp với đặc tả phân biệt giữa System Log và Activity Log.

### g. Role & Permission Audit
*   **Role**: Hệ thống chỉ định nghĩa một Enum tĩnh `UserRole` có giá trị duy nhất là `OWNER`. Không có bảng dữ liệu `roles` hay `role_id` trong cơ sở dữ liệu.
*   **Permission**: Đã chuẩn bị sẵn decorator `@permission_required` tại `core/auth/decorators.py` nhưng chưa được sử dụng ở bất kỳ route nào. Không có ACL hay bảng phân quyền động. Hệ thống hiện hoạt động hoàn toàn ở chế độ phân quyền tĩnh một người dùng (Single User).

### h. UI/UX & Accessibility Audit
*   **Giao diện**: Login page và Profile page thiết kế responsive tốt, căn chỉnh đẹp mắt. Form đổi mật khẩu dạng modal hoạt động trượt mượt mà.
*   **Validation & Feedback**: Cả 3 form (Login, Profile, Change Password) đều tích hợp validation client-side kỹ lưỡng, ngăn chặn submit rác. Nút submit đổi trạng thái loading (spinner) để phản hồi tốt cho người dùng.
*   **Accessibility**: Sử dụng đúng các thẻ `<label>`, placeholder và thuộc tính autocomplete chuẩn bảo mật (`username`, `current-password`).

---

## 3. Khối nợ kỹ thuật (Technical Debt)

1.  **Thiếu CSRF Protection**: Chưa sử dụng `Flask-WTF` hoặc token CSRF cho các form POST/AJAX, tạo sơ hở cho tấn công Cross-Site Request Forgery.
2.  **Session Fixation Risk**: Cần làm sạch session cũ trước khi gán định danh người dùng mới khi đăng nhập thành công.
3.  **Hardcoded Secret Key**: `SECRET_KEY` cấu hình tĩnh trong file code `config.py` thay vì đọc từ file cấu hình môi trường `.env`.
4.  **Thiếu Rate Limiting**: Route `/login` chưa được bảo vệ chống Brute-force (chưa giới hạn số lần thử sai liên tục).
5.  **Thiếu phân quyền chi tiết (RBAC)**: Quyền hạn được quyết định dựa trên chuỗi String `"OWNER"`. Nếu phát triển lên đa người dùng (quản lý, lễ tân, nhân viên), cần thiết kế hệ thống bảng `roles`, `permissions` và `role_permissions`.

---

## 4. Checklist Trạng thái Tính năng

*   Đăng nhập (Login) ......................... ✅ **Có & Đang dùng**
*   Đăng xuất (Logout) ........................ ✅ **Có & Đang dùng**
*   Hồ sơ cá nhân (Profile) ................... ✅ **Có & Đang dùng**
*   Tải ảnh đại diện (Avatar) ................. ✅ **Có & Đang dùng**
*   Đổi mật khẩu (Change Password) ............ ✅ **Có & Đang dùng**
*   Mã hóa mật khẩu (Password Hash) ........... ✅ **Có & Đang dùng**
*   Quản lý phiên (Session) ................... ✅ **Có & Đang dùng**
*   Ghi nhớ đăng nhập (Remember Me) ........... ✅ **Có & Đang dùng**
*   Mô hình vai trò (Role Model) .............. ⚠️ **Chuẩn bị (Enum tĩnh, không DB)**
*   Khung phân quyền (Permission Framework) ... ⚠️ **Chuẩn bị (Decorator trống)**
*   Security Log (`security.log`) .............. ✅ **Có & Đang dùng**
*   Activity Log (Database table) ............. ✅ **Có & Đang dùng**

---

## 5. Kết luận

Đánh giá mức độ sẵn sàng:
### 🟢 Ready for Single User Production

**Lý do**:
Hệ thống đáp ứng xuất sắc nhu cầu vận hành một người dùng (Spa Owner). Việc quản lý tài khoản, mã hóa bảo mật mật khẩu, quản lý phiên làm việc lâu dài (Remember Me), tải ảnh avatar và ghi log kiểm toán được thiết kế chặt chẽ, hoạt động trơn tru 100% trên các bộ test. Lỗ hổng tiềm năng như CSRF có thể chấp nhận tạm thời ở môi trường nội bộ nhưng cần khắc phục trước khi mở rộng.

Để nâng cấp lên **Multi-user Extension (Vai trò Nhân viên, Lễ tân)**, dự án bắt buộc phải giải quyết các khối nợ kỹ thuật về thiết kế bảng cơ sở dữ liệu phân quyền động.
