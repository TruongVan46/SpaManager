# Kiến trúc JavaScript – SpaManager v3.9

Tài liệu này mô tả chi tiết kiến trúc, vòng đời, cách phân chia mô-đun và các nguyên tắc lập trình JavaScript trong dự án SpaManager.

---

## 1. Cấu trúc thư mục (`static/js/`)

Hệ thống mã nguồn client-side được phân bổ như sau:

*   **`utils.js`**: Thư viện chứa các hàm tiện ích dùng chung toàn hệ thống (ví dụ: `formatCurrency`). Tránh trùng lặp code.
*   **`app.js`**: Quản lý các hiệu ứng chuyển trang (transitions), loading states toàn cục và tự động vô hiệu hóa nhấn đúp (double-click prevention) cho các nút hành động (Excel, PDF, Submit).
*   **`notification.js`**: Unified Notification Service. Triển khai toast xếp chồng (stackable toasts) với thanh tiến trình thời gian thực.
*   **`command-palette.js`**: Omnibar / Bảng lệnh điều khiển toàn hệ thống bằng phím tắt `Ctrl + K`.
*   **`shared-table.js`**: Khung bảng dùng chung hỗ trợ debounce ô tìm kiếm (300ms) và tự động lọc dữ liệu.
*   **`dashboard.js`, `appointment-calendar.js`, `setting.js`, `statistics.js`**: Mã nguồn JavaScript riêng của từng trang/phân hệ.

---

## 2. Hệ thống Singletons & Vòng đời (Lifecycle)

Các Singletons quan trọng được bảo vệ trong IIFE để tránh xung đột không gian tên toàn cục (global scope pollution):

### a. `NotificationService` (`window.Notification`)
*   **Vai trò**: Quản lý duy nhất việc hiển thị, xếp chồng và tự động xóa bỏ các thông báo Toast.
*   **Vòng đời**: Được đăng ký trực tiếp vào `window.Notification`. Khởi tạo container `.toast-container` động trên DOM khi gọi lần đầu tiên.
*   **Dọn dẹp**: Tự động xóa event listener `transitionend` và xóa phần tử HTML khỏi DOM sau khi hoàn tất hiệu ứng mờ dần (fade out).

### b. `ShortcutManager` & `CommandPaletteService`
*   **Vai trò**: Lắng nghe và điều phối các tổ hợp phím toàn cục như `Ctrl + K` (Mở bảng lệnh), `Ctrl + /` (Focus tìm kiếm), `Escape` (Đóng modal/bảng lệnh).
*   **Vòng đời**: Được khởi tạo trên sự kiện `DOMContentLoaded` bên trong IIFE của `command-palette.js`.
*   **Dọn dẹp**: Ràng buộc listener trực tiếp vào sự kiện `keydown` của `window`. Các phần tử DOM được đóng gói kín trong container để dọn dẹp dễ dàng.

---

## 3. Quản lý Event Listeners & Chống rò rỉ bộ nhớ (Memory Leak Prevention)

*   **Tránh dùng Inline Event Listeners**: Không sử dụng thuộc tính HTML `onclick`, `onchange`. Tất cả sự kiện của các phần tử động (ví dụ như nút xóa dòng trong Hóa đơn - `invoice.js`) đều được gắn trực tiếp bằng phương thức `addEventListener` khi tạo phần tử.
*   **Timer & Timeout Cleanups**:
    *   Các sự kiện Debounce (`shared-table.js`) luôn thực hiện `clearTimeout` trước khi đặt lịch mới.
    *   Các Toast notification tự động dọn dẹp cả `setTimeout` và `setInterval` của thanh tiến trình khi tắt.

---

## 4. AJAX & Giao tiếp API

*   **Async / Await**: Ưu tiên sử dụng cú pháp `async/await` thay vì chuỗi `.then()` dài dòng để tăng tính dễ đọc.
*   **Đồng bộ Indicator & Lỗi**:
    *   Mọi yêu cầu gửi dữ liệu lên máy chủ đều phải khóa nút bấm tương ứng (`btn.disabled = true`), hiển thị Spinner loading và phục hồi trạng thái cũ sau khi phản hồi hoặc sau tối đa 2.5 giây.
    *   Tất cả các khối AJAX đều được bọc trong `try/catch` hoặc `.catch()`, chuyển đổi mã lỗi JSON và hiển thị thông báo thân thiện thông qua `Notification.error`.
