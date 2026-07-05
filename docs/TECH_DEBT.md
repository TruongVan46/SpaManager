# SpaManager Technical Debt Log

Lưu ý: Đây là ghi chú technical debt lịch sử. Trạng thái release hiện hành được theo dõi trong `README.md`, `CHANGELOG.md`, `docs/RUNBOOK.md` và `docs/QA_CHECKLIST.md`.

Tài liệu này ghi nhận các phần mã nguồn mang tính chất tạm thời, các thiết kế chưa tối ưu, và kế hoạch tái cấu trúc nâng cấp trong các phiên bản **SpaManager v4.0** và các Sprint tiếp theo.

---

## 1. Cầu nối Tương thích Ngược (Compatibility Bridge)

* **Vị trí**: [flash.html](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/templates/layout/flash.html) & [base.html](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/templates/layout/base.html)
* **Vấn đề**: Hiện tại, chúng ta đang sử dụng cơ chế gom các thông điệp Flask `flash()` truyền thống vào mảng `window._flashMessages` trên client để hiển thị Toast mới.
* **Đề xuất v3.0**: Loại bỏ hoàn toàn Flask `flash()` ở Backend. Chuyển đổi tất cả các form lưu/cập nhật dữ liệu sang giao tiếp AJAX JSON API để trả về trạng thái trực tiếp cho client hiển thị `Notification`.

---

## 2. Các hàm `alert()` và `confirm()` nguyên bản còn sót lại

* **Vị trí**:
  * [invoice.js](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/static/js/invoice.js) (Các lời gọi `alert` khi kiểm tra dữ liệu dòng nhập hóa đơn).
  * [setting.js](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/static/js/setting.js) (Các cảnh báo `alert` và `confirm` khi xóa logo hoặc thực hiện backup/restore).
  * [customer/detail.html](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/templates/customer/detail.html) (Cảnh báo confirm trước khi thay đổi).
* **Vấn đề**: Vẫn sử dụng hộp thoại thô của trình duyệt, gây gián đoạn trải nghiệm người dùng và không đồng bộ giao diện.
* **Đề xuất v4.0**: Thay thế toàn bộ bằng `Notification.error` / `Notification.success` và xây dựng một API modal xác nhận dùng chung `Notification.confirm(...)` sử dụng Bootstrap Modal tùy biến.

---

## 3. Các khối CSS dư thừa hoặc trùng lặp

* **Vị trí**: `static/css/pages/`
* **Vấn đề**: Một số trang vẫn chứa các thuộc tính căn chỉnh lề (margin/padding) hoặc màu sắc nhỏ lẻ chưa được gom hoàn toàn vào hệ thống thiết kế CSS toàn cục.
* **Đề xuất v3.0**: Rà soát kỹ và đưa tất cả các style lặp lại này thành các class tiện ích (utility classes) trong `base-page.css`.

---

## 4. Chuyển đổi toàn diện sang AJAX APIs

* **Vấn đề**: Các trang Khách hàng (Customer), Hóa đơn (Invoice), Lịch hẹn (Appointment) khi thực hiện Xóa/Thêm mới/Cập nhật vẫn có chỗ tải lại toàn bộ trang (Full Page Reload).
* **Đề xuất v3.0**: Áp dụng cơ chế AJAX/Fetch toàn phần để cập nhật giao diện thời gian thực (Real-time DOM update) và hiển thị Toast mượt mà, tối ưu hiệu năng tải trang và trải nghiệm SPA (Single Page Application).

---

## 5. Các trường thông tin mở rộng của Owner (Sắp ra mắt)

* **Vị trí**: [profile.html](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/templates/auth/profile.html)
* **Vấn đề**: Các trường Email, Số điện thoại và Địa chỉ liên hệ của tài khoản Owner đang để dưới dạng readonly/disabled và hiển thị thông tin placeholder mẫu. Do hệ thống hiện tại mới chỉ có một tài khoản duy nhất (Owner), các thông tin này chưa được lưu trữ trong bảng `users` ở DB.
* **Đề xuất v4.0**: Khi triển khai tính năng Quản lý nhiều người dùng (Multi-user Management), cần bổ sung cột `email`, `phone`, và `address` vào bảng `users` và cho phép chỉnh sửa/cập nhật trực tiếp từ form Profile.

---

## 6. Lỗ hổng Bảo mật & Xác thực (Sprint 2.4 - Auth Audit)

* **Vấn đề**: Qua kiểm toán xác thực và phân quyền, phát hiện một số điểm yếu bảo mật cần khắc phục:
  1. **Thiếu CSRF Protection**: Chưa tích hợp `Flask-WTF` hoặc CSRF token, tăng nguy cơ tấn công giả mạo yêu cầu chéo trang.
  2. **Session Fixation**: ID phiên làm việc cũ không được làm sạch (`session.clear()`) trước khi gán ID người dùng mới sau đăng nhập thành công.
  3. **Hardcoded SECRET_KEY**: `SECRET_KEY` được cấu hình cứng trong `config.py` thay vì đọc từ file cấu hình môi trường `.env`.
  4. **Rate Limiting**: Chưa có giới hạn brute-force cho trang đăng nhập `/login`.
  5. **Bảng Phân quyền tĩnh**: Quyền hạn được so khớp chuỗi cứng `"OWNER"`. Chưa có các bảng dữ liệu `roles`, `permissions`, `role_permissions` phục vụ phân quyền động.
* **Đề xuất v4.0**:
  * Tích hợp `Flask-WTF` để tự động tạo và kiểm tra CSRF token cho tất cả các request POST/PUT/DELETE và AJAX.
  * Sửa hàm `AuthService.login()` để xóa bỏ dữ liệu session cũ trước khi đăng nhập.
  * Chuyển `SECRET_KEY` và các cấu hình nhạy cảm khác ra file `.env` và sử dụng `python-dotenv`.
  * Thiết lập giới hạn brute-force bằng `Flask-Limiter` trên route `/login`.
  * Xây dựng hệ cơ sở dữ liệu RBAC đầy đủ nếu nâng cấp lên hệ thống đa người dùng.
