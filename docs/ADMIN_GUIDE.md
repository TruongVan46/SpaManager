# SpaManager Admin Guide

Tài liệu này dành cho OWNER và ADMIN khi vận hành hệ thống. Nội dung tập trung vào phân quyền, người dùng, settings, backup/restore, diagnostics, và xử lý sự cố.

## 1. Mục đích

- Hướng dẫn vận hành hệ thống ở mức quản trị.
- Dùng cho phân quyền, sao lưu, khôi phục, giám sát, và xử lý sự cố.

## 2. Phân quyền

- **OWNER**: quyền cao nhất; thường quản lý users, settings, backup/restore, activity log, recycle bin, statistics.
- **ADMIN**: quản trị phần lớn chức năng hệ thống theo quyền hiện có.
- **STAFF**: chỉ dùng các chức năng nghiệp vụ; không truy cập admin pages.

Hãy tuân theo đúng quyền đang được code trong ứng dụng, không suy diễn thêm.

## 3. Quản lý người dùng

- Xem danh sách user.
- Tạo user mới.
- Chọn role phù hợp.
- Sửa thông tin user.
- Khóa hoặc mở khóa tài khoản nếu hệ thống có hỗ trợ.
- Reset mật khẩu khi cần.
- Không tự làm mất OWNER cuối cùng của hệ thống nếu app đang có quy tắc bảo vệ điều này.

## 4. Chính sách mật khẩu

- Mật khẩu nên có tối thiểu 8 ký tự.
- Không để trống.
- Xác nhận mật khẩu phải khớp.
- Khi tự đổi mật khẩu, người dùng nên nhập mật khẩu hiện tại.
- Không chia sẻ mật khẩu trong ghi chú, log, hoặc tài liệu.

## 5. Login protection

- Đăng nhập sai nhiều lần có thể bị giới hạn tạm thời.
- Đây là cơ chế hỗ trợ, không thay thế cho các biện pháp bảo mật khác.
- Nếu hệ thống có cấu hình giới hạn đăng nhập, không đặt ngưỡng quá thấp trên production.

## 6. Activity Log

- Dùng để xem các hoạt động quan trọng của hệ thống.
- Có thể lọc hoặc tìm nếu giao diện hỗ trợ.
- Một số sự kiện thường cần chú ý:
  - đăng nhập thất bại
  - bị rate-limit
  - đổi hoặc reset mật khẩu
  - tạo / cập nhật / bật tắt user
  - backup / restore nếu hệ thống ghi nhận
- Không được chứa mật khẩu dạng plaintext.

## 7. Settings

- Cập nhật thông tin cơ bản của spa.
- Logo hoặc avatar nếu hệ thống hỗ trợ.
- Backup Center nếu được tích hợp trong Settings.
- Không đưa secret hoặc env thật vào giao diện quản trị.

## 8. Backup

- Nên tạo backup trước khi restore hoặc trước release lớn.
- Kiểm tra backup sau khi tạo:
  - file xuất hiện trong danh sách
  - metadata đọc được
  - app_version đúng
  - dung lượng hợp lý

## 9. Restore

Lưu ý:

- Restore là thao tác nguy hiểm.
- Chỉ thực hiện khi đã backup hiện trạng trước đó.
- Kiểm tra metadata backup trước khi restore.
- Sau restore, nên kiểm tra:
  - `/health`
  - login
  - `data audit`
  - `ops diagnostics`
  - một vài màn hình chính

## 10. Recycle Bin

- Dữ liệu xóa mềm có thể khôi phục nếu còn trong Thùng rác.
- Permanent delete là thao tác không an toàn nếu làm nhầm.
- Nên xác nhận kỹ trước khi xóa vĩnh viễn.

## 11. Operational CLI

Các lệnh nội bộ quan trọng:

- `data audit`
- `data repair` ở chế độ dry-run
- `perf profile`
- `ops diagnostics`

Cảnh báo:

- Không chạy `data repair --apply --yes` trên production nếu chưa xem dry-run và chưa có backup.
- Không dùng các lệnh profiling như stress test sản xuất.

## 12. Security / Accounts diagnostics

- `ops diagnostics` có phần kiểm tra security / accounts.
- Theo dõi số lượng OWNER / ADMIN / STAFF.
- Cảnh báo nếu chỉ còn rất ít tài khoản quản trị.
- Không lộ password, hash, token, hoặc secret trong report.

## 13. Release / deployment checklist

- Kiểm tra README và RUNBOOK trước khi release.
- Đảm bảo tests pass.
- Đảm bảo `compileall` pass nếu có thay đổi code.
- Cập nhật `CHANGELOG.md` và `APP_VERSION` khi tới checkpoint phát hành.
- Kiểm tra smoke checklist sau deploy.

## 14. Troubleshooting cho admin

- STAFF không vào được admin page: kiểm tra quyền là đúng.
- User quên mật khẩu: admin reset theo quy trình hiện có.
- User bị inactive: bật lại nếu chính sách cho phép.
- Login bị rate-limit: chờ hết window hoặc kiểm tra cấu hình.
- Backup list trống: kiểm tra persistent storage.
- PDF lỗi font: kiểm tra bundled fonts và xuất file mới.


## PostgreSQL backup/restore roadmap

- OWNER/ADMIN nên đọc thêm `docs/POSTGRESQL_BACKUP_RESTORE_STRATEGY.md` trước khi lên kế hoạch cutover.
- Không restore production PostgreSQL bằng flow SQLite hiện tại.
