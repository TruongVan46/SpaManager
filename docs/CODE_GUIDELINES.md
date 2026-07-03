# SpaManager Code Guidelines

Tài liệu này định nghĩa các tiêu chuẩn lập trình, đặt tên và quy ước cấu trúc dự án để đảm bảo tính đồng nhất và chất lượng mã nguồn của SpaManager.

---

## 1. Quy ước Đặt tên (Naming Conventions)

### 1.1. Python & Backend
* **Tên file & Thư mục**: `snake_case` (ví dụ: `service_service.py`, `activity_log.py`).
* **Tên Class**: `PascalCase` (ví dụ: `ServiceService`, `CustomerRepository`).
* **Tên biến & Hàm**: `snake_case` (ví dụ: `get_service_by_id`, `is_deleted`).
* **Routes / Blueprints**: `snake_case` cho tiền tố URL (ví dụ: `/recycle-bin/restore/<type>/<id>`).

### 1.2. JavaScript & Frontend
* **Tên file**: `kebab-case` hoặc `snake_case` (ví dụ: `shared-table.js`, `appointment.js`).
* **Tên Class**: `PascalCase` (ví dụ: `SharedTable`, `NotificationService`).
* **Tên biến & Hàm**: `camelCase` (ví dụ: `calculateTotals`, `formatCurrency`, `showEventPopover`).
* **DOM Selectors / IDs**: `kebab-case` (ví dụ: `#toast-container`, `#deleteConfirmModal`).

---

## 2. Quy chuẩn CSS (CSS Conventions)

* **Thiết kế đồng bộ**: Sử dụng các biến CSS toàn cục được định nghĩa trong [theme.css](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/static/css/theme.css) (như `--spa-primary`, `--spa-radius-md`, `--spa-shadow-normal`).
* **Module hóa CSS**: 
  * Định nghĩa các class chung tại `base-page.css`.
  * Các thiết kế riêng biệt của từng trang phải được lưu tại `static/css/pages/<page_name>.css`.
  * Các component tái sử dụng (như Toast, Modal, Loader) được lưu tại `static/css/components/`.
* **Quy tắc quan trọng**: Hạn chế lạm dụng `!important` trừ các trường hợp override đặc biệt của thư viện bên ngoài.

---

## 3. Quy chuẩn JavaScript (JS Conventions)

* **Tự đóng gói (Encapsulation)**: Sử dụng cấu trúc IIFE `(function() { ... })()` để cô lập phạm vi biến, tránh gây ô nhiễm không gian biến toàn cục (`window`).
* **Truy xuất toàn cục**: Chỉ các Service dùng chung (như `Notification`, `SharedTable`) mới được đăng ký trực tiếp vào `window`.
* **Không sử dụng JavaScript nội dòng (Inline JavaScript)**:
  * Không gán trực tiếp sự kiện trong HTML (ví dụ: tránh dùng `onclick="doSomething()"`).
  * Sử dụng `addEventListener` trong tệp JS tương ứng.
* **Xử lý bất đồng bộ (Async/Await)**: Ưu tiên sử dụng cú pháp `async/await` kết hợp với khối `try/catch` để kiểm soát lỗi kết nối API.

---

## 4. Hệ thống Thông báo & Tương tác Người dùng

* **Không sử dụng `alert()` hay `confirm()` nguyên bản của trình duyệt**: Tất cả thông báo/xác nhận phải đi qua hệ thống `Notification` hoặc các Modal/Toast được tùy biến của Bootstrap.
* **Không Reload trang không cần thiết**: Nếu dữ liệu được cập nhật thành công bằng AJAX, hãy thay đổi DOM động và gọi thông báo Toast tương ứng, tránh bắt người dùng phải đợi reload trang.
