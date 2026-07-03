# Changelog

Tất cả các thay đổi lớn đối với dự án SpaManager sẽ được ghi nhận tại đây.

## [v4.0] - 2026-06-29

### Added
* **Chuẩn hóa Giao diện & Trạng thái Tối (Sprint D3.2 - UI/UX Polish)**:
  - Khắc phục hoàn toàn hiện tượng nền trắng, chữ sáng màu của `.modal-footer` ở các tệp tin cấu hình.
  - Sửa lỗi tương phản chữ nhỏ trên các lớp nền phụ của `.text-muted` và `.text-secondary` ở chế độ tối.
  - Loại bỏ hoàn toàn nền trắng cứng ở Dropdown Menu Hồ sơ cá nhân (topbar) và hộp chọn Select2 (Tạo hóa đơn), thay thế bằng các biến CSS thiết kế của SpaManager.
* **Tương thích Thiết bị di động hoàn chỉnh (Sprint D3.3 & D3.5.1 - Mobile Navigation)**:
  - Thiết lập ngăn chứa trình đơn di động Sidebar Drawer hỗ trợ kích thước màn hình máy tính bảng (280px) và điện thoại (100vw).
  - Triển khai nút bấm Hamburger menu ☰ kích hoạt lớp phủ overlay cùng hiệu ứng đóng vuốt chạm (Swipe close), phím tắt ESC và khóa cuộn trang (Scroll lock) mượt mà.
  - Tối ưu hóa độ rộng co dãn tự động của hộp tìm kiếm nhanh Command Palette (`width: 90%; max-width: 650px;`) và card lưu trữ Backup Center.
* **Chuẩn hóa Tiếp cận WCAG 2.1 AA (Sprint D3.4 - Accessibility)**:
  - Thêm thuộc tính `scope="col"` vào toàn bộ các tiêu đề cột `<th>` trên 11 bảng dữ liệu.
  - Bổ sung nhãn thay thế `aria-label` cho các ô input lọc nhanh không có nhãn hiển thị trực quan.
  - Cải thiện hiển thị tiêu điểm viền nổi bật `:focus-visible` phục vụ điều hướng bàn phím.
* **Chuẩn hóa Chuyển động Cao cấp (Sprint D3.5 - Motion & Animation)**:
  - Thiết kế lại hiệu ứng Skeleton loading dạng **Shimmer gradient** trượt xiên ánh sáng tinh tế thay cho nhấp nháy Pulse đơn điệu cũ.
* **Đồng bộ hóa Phân trang cho Trung tâm Sao lưu**:
  - Tích hợp lớp phân trang `SimplePagination` và macro `pagination_widget` đồng bộ giao diện phân trang, số bản ghi hiển thị, và số trang cho danh sách Backup Center trong cài đặt.

### Changed
* **Tối ưu hóa tài nguyên & Dọn dẹp mã nguồn (Code Hygiene)**:
  - Gỡ bỏ hoàn toàn 3 tệp CSS trống rác (`customer.css`, `service.css`, `report.css`) và các liên kết tương ứng trong `base.html` giúp tối ưu hóa dung lượng nạp trang.
  - Loại bỏ triệt để Blueprint Report cũ (`routes/report.py` và `templates/report/`) đã được thay thế bằng Statistics.
  - Cấu hình tiêu đề phản hồi `SEND_FILE_MAX_AGE_DEFAULT` (1 năm) cho các tài nguyên tĩnh trong `config.py` để tăng tốc độ tải trang từ phía trình duyệt.

---

## [v3.9] - 2026-06-29

### Added
* **Tài liệu Kiến trúc CSS**: Lập tài liệu kiến trúc giao diện chi tiết tại [docs/CSS_ARCHITECTURE.md](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/docs/CSS_ARCHITECTURE.md) mô tả cấu trúc thư mục, hệ thống Z-Index Layer chuẩn hóa, cách consume biến CSS và Responsive Breakpoints.
* **Tài liệu Kiến trúc JavaScript**: Lập tài liệu kiến trúc JavaScript chi tiết tại [docs/JAVASCRIPT_ARCHITECTURE.md](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/docs/JAVASCRIPT_ARCHITECTURE.md) mô tả cấu trúc thư mục, hệ thống singletons, vòng đời phím tắt, chống rò rỉ bộ nhớ, AJAX và loading indicator.
* **Kiểm toán Xác thực & Phân quyền (Sprint 2.4 - Auth & Security Audit)**: Tiến hành rà soát bảo mật hệ thống đăng nhập, đăng xuất, đổi mật khẩu và quản lý hồ sơ cá nhân. Ghi nhận báo cáo tại [docs/AUTH_AUDIT_v3.9.md](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/docs/AUTH_AUDIT_v3.9.md).
* **Kịch bản kiểm thử Đổi mật khẩu**: Tạo mới tệp kiểm thử tự động [verify_change_password.py](file:///C:/Users/ADMIN/.gemini/antigravity/brain/bf67f160-279d-4d29-a40f-9141c8b12f29/scratch/verify_change_password.py) kiểm định tất cả các trường hợp chặn mật khẩu yếu, trùng mật khẩu cũ, mật khẩu hiện tại không hợp lệ, ghi log và đăng nhập lại thành công.
* **Semantic Tints & Borders**: Bổ sung các biến giao diện phụ (`--spa-info-light`, `--spa-info-border`, `--spa-success-border`...) trong `theme.css` cho các trạng thái của thẻ, bảng và huy hiệu trạng thái.

### Changed
* **Chuẩn hóa Z-Index Layer (Sprint 2.2 - CSS Cleanup)**:
  - Khai báo hệ thống phân lớp z-index toàn cục trong `:root` của `theme.css`.
  - Thay thế các giá trị z-index hardcoded thành biến: `.page-loader` (`var(--z-index-loader)`), `.command-palette-overlay` (`var(--z-index-command-palette)`), `.toast-container` (`var(--z-index-toast)`), `.select2-dropdown` / `.cal-popover` (`var(--z-index-popover)`), `.dropdown-menu` (`var(--z-index-dropdown)`).
* **Chuẩn hóa Màu sắc toàn hệ thống**:
  - Loại bỏ hoàn toàn 51 khai báo mã màu HEX/RGB hardcoded (ví dụ các mã màu của SbAdmin2 cũ như `#4e73df`, `#1cc88a`, `#e74a3b`, `#f6c23e`...) trên 11 tệp tin CSS và chuyển dịch sang consume toàn bộ các biến CSS trong `theme.css`.
  - Giữ lại 3 tệp tin CSS rỗng (`customer.css`, `service.css`, `report.css`) trên ổ đĩa để tránh gãy các thẻ `<link>` trong layout nhưng đánh dấu là Dead CSS (Ứng viên chờ gỡ bỏ).
* **Chuẩn hóa JavaScript (Sprint 2.3 - JavaScript Cleanup)**:
  - Loại bỏ khối khởi tạo `toastContainer` cục bộ bị thừa trong `appointment.js` để tránh xung đột CSS z-index/vị trí.
  - Loại bỏ hoàn toàn thuộc tính HTML inline `onclick` và sự kiện toàn cục `window.dispatchEvent('updateInvoiceTotals')` trong `invoice.js`. Thay thế bằng việc gắn event listener bản địa trực tiếp (`addEventListener('click')`) khi khởi tạo các dòng dịch vụ mới.
  - Đồng bộ hóa hoàn toàn màu sắc biểu đồ doanh thu dạng đường từ màu xanh mặc định `#0d6efd` sang màu nâu thương hiệu `#a67c52` trên cả Dashboard và Statistics.
  - Bổ sung chú thích JSDoc chi tiết giải thích vòng đời và vai trò của các Singletons (`NotificationService`, `ShortcutManager`, `CommandPaletteService`).

## [v3.8] - 2026-06-29

### Added
* **Kiểm định Hệ thống toàn diện (Sprint 1 - System Audit)**:
  - Tiến hành rà soát tất cả các thư mục, route, dịch vụ, giao diện template, CSS, JS, CSDL và các kịch bản kiểm thử.
  - Lập báo cáo kiểm định chi tiết tại [AUDIT_REPORT_v3.7.md](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/docs/AUDIT_REPORT_v3.7.md) phân loại rõ ràng các module đã hoàn thiện, module ổn định (Stable) và các phần cần dọn dẹp (Cleanup) theo mức độ ưu tiên.

### Changed
* **Chuẩn hóa & Dọn dẹp Imports toàn hệ thống (Sprint 2.1 - Import Cleanup)**:
  - Quy hoạch và đưa toàn bộ các câu lệnh import nằm rải rác bên trong các hàm nghiệp vụ của Service Layer (`appointment_service`, `customer_service`, `service_service`, `invoice_service`, `auth_service`, `backup_service`, `restore_service`, `import_service`) lên đầu file theo chuẩn PEP 8.
  - Loại bỏ hoàn toàn 89 dòng khai báo import trùng lặp cục bộ (như `ActivityLogService`, `dashboard_cache`, `uuid`, `datetime`...) gây lãng phí bộ nhớ và clutter code.
  - Thay thế kết nối `from app import db` sang `from extensions import db` trong các Service và Core (`error_handler.py`) giúp giải quyết hoàn toàn nợ kỹ thuật về Circular Imports (nhập vòng).
  - Loại bỏ import `shutil` không dùng trong `services/restore_service.py` sau khi đã nâng cấp lên SQLite Online Backup API.
  - Tối ưu kịch bản test `verify_import_backup.py` để loại bỏ flakiness bằng cách đợi Toast thông báo hiển thị hoàn tất (`wait_for` locator visible) thay vì kiểm tra tức thì.

## [v3.7] - 2026-06-29

### Added
* **Tải lên & Khôi phục bản sao lưu ngoài (Upload & Restore External Backup)**:
  - Thêm nút "Nhập Backup" trong card Backup Center mở Modal chọn tệp `.db`, `.sqlite`, `.sqlite3`.
  - Hỗ trợ Kéo thả (Drag & Drop) tệp tin trực tiếp với hiệu ứng chuyển đổi trạng thái khi kéo đè (dragover).
  - Tự động kiểm tra định dạng SQLite vật lý bằng Signature header (`b'SQLite format 3\x00'`) và giới hạn dung lượng tối đa 100MB ở cả phía Client và Server.
  - Kiểm tra tính toàn vẹn và hợp lệ cấu trúc bảng (schema) SpaManager (yêu cầu đầy đủ các bảng `users`, `customers`, `services`, `appointments`, `invoices`, `activity_logs`, `settings`).
  - Đọc thông tin phiên bản CSDL, phiên bản phần mềm, ngày tạo gốc và kích thước tệp hiển thị trong Restore Wizard.
  - Ngăn chặn tải trùng lặp tệp bằng mã băm SHA256, hiển thị cảnh báo: *"Backup này đã tồn tại trong hệ thống."*.
  - Lưu trữ tệp tin khôi phục dạng `SpaManager_Imported_{timestamp}_v{version}` và đánh dấu thuộc tính nguồn `source = 'Imported'`.
  - Tự động kích hoạt Restore Wizard cho tệp vừa tải lên thành công để người dùng không phải thực hiện thủ công.
  - Nhật ký ghi nhận: Ghi nhận sự kiện `IMPORT_BACKUP` và `RESTORE_BACKUP` trong activity log, `application.log` ghi `"Imported Backup"`, và `security.log` ghi `"RESTORE_IMPORTED_BACKUP"`.
* **Dịch vụ làm mới hệ thống dùng chung (`services/system_refresh_service.py`)**:
  - Triển khai lớp `SystemRefreshService.after_restore()` giúp dọn dẹp bộ nhớ đệm cache và giải phóng các session / connection pool cũ của SQLAlchemy (`db.session.remove()`, `db.session.close()`, `db.engine.dispose()`).
  - Hỗ trợ đồng bộ hóa dữ liệu Dashboard và Statistics tức thì ngay sau khi Restore cơ sở dữ liệu.
* **Kịch bản kiểm thử tích hợp tự động**:
  - [verify_import_backup.py](file:///C:/Users/ADMIN/.gemini/antigravity/brain/bf67f160-279d-4d29-a40f-9141c8b12f29/scratch/verify_import_backup.py): Kiểm định luồng tải lên hợp lệ/không hợp lệ, so khớp SHA256 trùng lặp, tự động nhảy wizard, ghi log nghiệp vụ và nhật ký bảo mật.
  - [verify_dashboard_after_restore.py](file:///C:/Users/ADMIN/.gemini/antigravity/brain/bf67f160-279d-4d29-a40f-9141c8b12f29/scratch/verify_dashboard_after_restore.py): Kiểm tra tính đồng bộ tức thì của bộ đếm Dashboard ngay sau khi khôi phục cơ sở dữ liệu.

### Changed
- Cấu hình thêm cột "Nguồn" (Source) hiển thị các badge nguồn gốc `LOCAL` và `IMPORTED` trong bảng danh sách bản sao lưu.
- Khôi phục hoạt động đồng bộ của Master Test Suite với tổng cộng 17/17 bài test đạt trạng thái **100% SUCCESS**.

---

## [v3.6] - 2026-06-29

### Added
* **SQLite Online Backup Integration (`services/restore_service.py`)**: Tích hợp SQLite Online Backup API (`sqlite3.Connection.backup`) thay thế cho `shutil.copy2` thô sơ. Điều này loại bỏ hoàn toàn lỗi tranh chấp khóa tệp (`PermissionError: [WinError 32]`) trên nền tảng Windows khi tiến trình Flask đang giữ kết nối database mở.
* **Loading Overlay & UI Lock (`templates/setting/index.html`)**: Thêm lớp phủ loading overlay `#restore-loading-overlay` che kín màn hình wizard modal trong suốt quá trình khôi phục dữ liệu, đồng thời vô hiệu hóa phím Escape và click chuột ra ngoài (`data-bs-backdrop="static" data-bs-keyboard="false"`) để ngăn người dùng ngắt tiến trình khôi phục dữ liệu giữa chừng.
* **Hậu Khôi phục & Tải lại ứng dụng**: Tích hợp nút "Tải lại ngay" (`window.location.reload()`) và ẩn nút đóng thông thường sau khi khôi phục thành công, ép ứng dụng phải nạp lại CSDL mới một cách đồng bộ.
* **Hệ thống Ghi nhật ký phục hồi**: Ghi chi tiết sự kiện vào `application.log`, log bảo mật hệ thống vào `security.log` (`app_logger.security(...)`), và log hành động `RESTORE_BACKUP` (hoặc `ERROR` nếu thất bại) vào bảng nhật ký hoạt động `activity_logs`.
* **Kịch bản kiểm thử Restore tự động (`scratch/verify_backup_restore.py`)**: Tạo mới kịch bản test Playwright kiểm định tự động toàn bộ quy trình các bước của wizard khôi phục dữ liệu, kiểm tra hiển thị overlay, nút reload, các file log vật lý và log CSDL.

### Changed
* **Settings Page AJAX & Toast Notifications (`static/js/setting.js`)**:
  - Chuyển đổi toàn bộ các hành động Xóa Logo, Cập nhật Ghi chú bản sao lưu, và Xóa bản sao lưu vĩnh viễn sang giao tiếp AJAX mượt mà. Hệ thống sẽ cập nhật DOM trực tiếp và hiển thị Toast thông báo mà không cần reload trang.
  - Sửa lỗi import thiếu thư viện `sqlite3` trong `services/backup_service.py` khiến việc kiểm tra tính toàn vẹn của tệp SQLite (`check_file_integrity`) bị lỗi âm thầm và luôn đánh dấu bản sao lưu là `Invalid` (nút Khôi phục bị vô hiệu hóa).
  - Tắt sự kiện click chồng chéo của modal xác nhận khôi phục cũ (`#restoreBackupModal`), hợp nhất hoàn toàn vào luồng xử lý của Restore Wizard Modal (`#restoreWizardModal`).
  - Hỗ trợ client-side HTML5 validation với Toast cảnh báo cho Form thông tin Spa tại trang cài đặt (cấu hình Spa name bắt buộc, Spa phone đúng 10 số đầu 0, email hợp lệ).

---

## [v3.5] - 2026-06-29

### Added
* **Simple In-Memory Cache (`core/cache.py`)**: Triển khai bộ nhớ đệm cache trong RAM an toàn đa luồng (`SimpleTTLCache`) lưu trữ kết quả truy vấn Dashboard trong 30 giây để tránh đọc DB liên tục.
* **SQLite Database Indexes**: Tạo các index cho các cột quan trọng phục vụ tìm kiếm, so khớp khóa ngoại, và lọc ngày tháng:
  * `idx_customers_deleted_at` trên `customers (deleted_at)`
  * `idx_services_deleted_at` trên `services (deleted_at)`
  * `idx_appointments_deleted_at` trên `appointments (deleted_at)`
  * `idx_invoices_deleted_at` trên `invoices (deleted_at)`
  * `idx_appointments_appointment_time` trên `appointments (appointment_time)`
  * `idx_invoices_invoice_date` trên `invoices (invoice_date)`
  * `idx_appointments_customer_id` trên `appointments (customer_id)`
  * `idx_invoices_customer_id` trên `invoices (customer_id)`
* **Active Cache Invalidation Hook**: Tự động xóa (invalidate) cache thống kê dashboard bất cứ khi nào có thay đổi dữ liệu (tạo mới/sửa/xóa khách hàng, dịch vụ, lịch hẹn, hóa đơn).
* **Lazy Loading in HTML Templates**: Thêm thuộc tính `loading="lazy"` cho các thẻ `<img>` avatar người dùng ở topbar, profile page, và logo spa ở trang cấu hình.

### Changed
* **Loại bỏ Dashboard Polling**: Xóa bỏ hoàn toàn cơ chế gọi `setInterval` fetch dữ liệu sau mỗi 5 giây ở client-side trong `dashboard.js`. Dữ liệu chỉ làm mới khi tải trang hoặc qua sự kiện `visibilitychange` (khi người dùng active lại tab).
* **Query Optimization (N+1 Query Prevention)**: Refactor các truy vấn CSDL trong `DashboardStatisticsService`, `AppointmentService` và `InvoiceService` sử dụng `.options(db.joinedload(...))` và `.options(db.contains_eager(...))` để tải trước các thực thể quan hệ bằng phép JOIN duy nhất.

---

## [v3.4] - 2026-06-29

### Added
* **Công cụ Kiểm Định Dự Án (`scripts/project_audit.py`)**: Tự động phân tích toàn bộ dự án để phát hiện unused imports, duplicate selectors/functions, TODOs/FIXMEs, và empty directories.
* **Tài liệu Báo Cáo Dọn Dẹp (`docs/CLEANUP_REPORT.md`)**: Ghi chép chi tiết kết quả quét dọn để phục vụ rà soát chất lượng.

### Changed
* **Python Cleanups**: Dọn sạch hoàn toàn các import không sử dụng và gom các import sqlalchemy `func` / flask `send_file` lên đầu file để tối ưu hóa hiệu năng.
* **CSS Cleanups**: Xóa bỏ tệp `style.css` trống rỗng không sử dụng để tiết kiệm network requests của trình duyệt.
* **Templates Cleanups**: Loại bỏ các comment TODO trong `profile.html` và gom các ghi nhận nợ kỹ thuật vào [TECH_DEBT.md](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/docs/TECH_DEBT.md).
* **Folders Cleanups**: Loại bỏ các thư mục rác `static/icons`, `static/img/background`.

---

## [v3.3] - 2026-06-29

### Added
* **Khung Xác Thực Dữ Liệu Nhất Quán (Unified Validation Framework)**: Xây dựng cấu trúc thư mục `validators/` và `validators/rules/` giúp tập trung hóa toàn bộ logic kiểm tra đầu vào.
* **Quy tắc xác thực độc lập (Rules)**: Triển khai các rule độc lập có thể tái sử dụng:
  * `required.py`: Kiểm tra sự hiện diện của dữ liệu.
  * `email.py`: Kiểm tra định dạng email bằng regex.
  * `phone.py`: Kiểm tra định dạng số điện thoại Việt Nam (10 chữ số, đầu số hợp lệ).
  * `number.py`: Kiểm tra kiểu số và khoảng giá trị (min/max).
  * `length.py`: Kiểm tra độ dài chuỗi (min/max).
  * `regex.py`: Kiểm tra so khớp mẫu tùy chỉnh.
  * `date.py`: Kiểm tra định dạng ngày tháng theo định dạng bất kỳ (e.g. `%Y-%m-%d`).
* **Lớp Validators chuyên biệt**:
  * `CustomerValidator`: Xác thực thông tin khách hàng (Họ tên, SĐT, Email).
  * `ServiceValidator`: Xác thực thông tin dịch vụ (Tên, Giá không âm, Thời lượng).
  * `AppointmentValidator`: Xác thực thông tin lịch hẹn (Khách hàng tồn tại, Dịch vụ tồn tại, Ngày giờ hợp lệ).
  * `InvoiceValidator`: Xác thực thông tin hóa đơn (Khách hàng hợp lệ, có ít nhất một dịch vụ, Tổng tiền không âm).
  * `AuthValidator`: Xác thực đăng nhập và đổi mật khẩu phức tạp.
  * `ProfileValidator`: Xác thực thông tin cá nhân và định dạng/dung lượng file ảnh đại diện.
  * `BackupValidator`: Xác thực ghi chú sao lưu.
  * `ImportValidator`: Xác thực loại và hành động nhập khẩu Excel.
* **Developer Guidelines (`docs/VALIDATION.md`)**: Soạn thảo tài liệu chuẩn hóa quy tắc viết Validator và tích hợp vào Service Layer.
* **Test Suite Validation**: Xây dựng kịch bản kiểm thử tự động [verify_validation.py](file:///C:/Users/ADMIN/.gemini/antigravity/brain/bf67f160-279d-4d29-a40f-9141c8b12f29/scratch/verify_validation.py) xác thực 100% các validator con.

### Changed
* **Tái cấu trúc Service Layer**: Refactor `CustomerService`, `ServiceService`, `AppointmentService`, `InvoiceService`, `AuthService`, `BackupService`, và `ImportService` để sử dụng trực tiếp các lớp Validator tương ứng. Loại bỏ hoàn toàn các kiểm tra chuỗi rỗng thô sơ trong code.
* **Xử lý Exception nhất quán**: Chuyển đổi toàn bộ lỗi validation thành `ValidationException` mang theo mapping chi tiết `field_errors`, giúp Exception Handler toàn cục tự động bắt lỗi và phản hồi JSON thích hợp cho AJAX hoặc flash message cho HTML page.

---

## [v3.2] - 2026-06-29

### Added
* **Logging Framework Core (`core/logger.py`)**: Xây dựng singleton `AppLogger` quản lý hoạt động ghi nhật ký hệ thống.
  * Tự động khởi tạo thư mục `logs/` khi bắt đầu ứng dụng.
  * Định dạng ghi file chuyên nghiệp `FileLogFormatter` (định dạng đa dòng chứa timestamp, level, module và message/traceback).
  * Hỗ trợ log console nhiều màu sắc (ANSI escape colors) cho môi trường Development nhằm nâng cao trải nghiệm debug.
  * Sử dụng `RotatingFileHandler` tự động quay vòng dung lượng tối đa 5MB và giữ tối đa 5 file backup cũ.
* **Tách biệt log file nghiệp vụ**:
  * `logs/application.log`: Lưu trữ vòng đời khởi tạo, quá trình Excel Import/Export, và sao lưu/phục hồi cơ sở dữ liệu.
  * `logs/error.log`: Chỉ thu thập các lỗi hệ thống nghiêm trọng, lỗi cơ sở dữ liệu, lỗi IO kèm đầy đủ traceback.
  * `logs/security.log`: Ghi nhận nhật ký bảo mật/kiểm toán tài khoản (login success/failed, logout, đổi mật khẩu).
* **Developer Guidelines (`docs/LOGGING.md`)**: Soạn thảo tài liệu chuẩn hóa quy tắc viết log và bảo mật (cấm ghi password, session id, token).
* **Test Suite Logging**: Xây dựng tệp [verify_logging.py](file:///C:/Users/ADMIN/.gemini/antigravity/brain/bf67f160-279d-4d29-a40f-9141c8b12f29/scratch/verify_logging.py) xác thực tự động tính năng ghi log và cơ chế xoay vòng.

### Changed
* **Loại bỏ print debug**: Quét sạch toàn bộ các câu lệnh `print(...)` thô trong các module Python nghiệp vụ, thay thế bằng các lệnh gọi logger thích hợp.
* **Tích hợp ErrorHandler**: Cấu hình `ErrorHandler` toàn cục ghi lỗi qua `AppLogger`.

---

## [v3.1] - 2026-06-29

### Added
* **Unified Exception Framework (`core/exceptions.py`)**: Chuẩn hóa hệ thống phân cấp ngoại lệ với `SpaManagerException` làm base, cùng các lớp ngoại lệ con chuyên biệt: `ValidationException`, `NotFoundException`, `ConflictException`, `PermissionDeniedException`, `AuthenticationException`, và `SystemException`.
* **Exception Mapper & Global Error Handler (`core/error_handler.py`)**:
  * Tự động chuyển đổi ngoại lệ sang mã lỗi chuẩn, HTTP status code và mức độ nghiêm trọng (severity).
  * Lọc thông minh: tự động bỏ qua các lỗi xác thực dữ liệu thông thường khỏi ActivityLog để tránh tràn DB log.
  * Phản hồi thông minh: tự động trả về payload JSON có cấu trúc nếu là AJAX/JSON request, ngược lại flash thông báo và redirect an toàn (Referer) nếu là HTML page.
* **Developer Guidelines (`docs/ERROR_HANDLING.md`)**: Hướng dẫn nguyên tắc ném ngoại lệ ở tầng Service, loại bỏ hoàn toàn việc dùng `return False` báo lỗi.
* **Test Suite Exception handling**: Xây dựng tệp [verify_error_handling.py](file:///C:/Users/ADMIN/.gemini/antigravity/brain/bf67f160-279d-4d29-a40f-9141c8b12f29/scratch/verify_error_handling.py) tự động xác minh toàn bộ luồng lỗi.

---

## [v2.4.4] - 2026-06-29

### Added
* **UserDTO Layer (`core/auth/dto.py`)**: Thiết lập đối tượng truyền dữ liệu (DTO) độc lập để ngăn chặn View đọc trực tiếp đối tượng SQLAlchemy ORM.
* **Hồ sơ cá nhân (`/profile`)**:
  * Trang quản lý thông tin [profile.html](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/templates/auth/profile.html) cho phép thay đổi Họ tên và tải lên ảnh đại diện cá nhân.
  * Hỗ trợ chuẩn bị sẵn các trường thông tin mở rộng (Email, Phone, Address) phục vụ việc mở rộng trong tương lai.
* **Local Avatar Storage & Auto-cleanup**:
  * Lưu trữ file ảnh đại diện tại thư mục `static/uploads/avatars/` (giới hạn đuôi file JPG/JPEG/PNG và kích thước tối đa 2MB).
  * Cơ chế tự động dọn dẹp (xóa file cũ khỏi đĩa cứng) khi người dùng cập nhật ảnh đại diện mới.
* **Activity Log hooks**: Ghi nhận hoạt động `PROFILE_UPDATE` (SUCCESS).

---

## [v2.4.3] - 2026-06-29

### Added
* **Security Decoupling (`core/auth/security.py`)**: 
  * `PasswordHasher` bọc thư viện Werkzeug hashing cho phép dễ dàng chuyển đổi thuật toán mã hóa sau này.
  * `PasswordPolicy` quản lý các quy tắc về độ dài mật khẩu (tối thiểu 8 ký tự).
* **Change Password Modal (`change_password_modal.html`)**:
  * Tích hợp Modal Bootstrap cho phép thay đổi mật khẩu từ Topbar.
  * Thêm nút ẩn/hiện mật khẩu `👁` riêng biệt cho từng trường.
  * Client-side validation đầy đủ cùng phản hồi trạng thái chờ lưu (spinner loading/disabled).
* **Activity Log hooks**: Ghi nhận hoạt động `CHANGE_PASSWORD` (SUCCESS) và `CHANGE_PASSWORD_FAILED` (WARNING) trong nhật ký hoạt động.

---

## [v2.4.2] - 2026-06-29

### Added
* **Login & Logout Routes**: Thiết lập endpoint `/login` và `/logout` hỗ trợ xác thực tài khoản.
* **Global Route Protection**: Tự động chuyển hướng các lượt truy cập chưa đăng nhập về trang `/login`, lưu trữ tham số đường dẫn trước đó `?next=` để tự chuyển hướng thông minh sau đăng nhập thành công.
* **Login Interface**: Giao diện đăng nhập bóng bẩy [login.html](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/templates/auth/login.html) thiết kế theo quy chuẩn glassmorphism.
* **Session Persistence**: Tích hợp checkbox "Ghi nhớ đăng nhập" duy trì phiên đăng nhập 30 ngày.
* **Activity Log hooks**: Ghi nhận hoạt động `LOGIN` và `LOGOUT` kèm `user_id` tương ứng.

---

## [v2.4.1] - 2026-06-29

### Added
* **Authentication Core (`core/auth`)**:
  * Định nghĩa `UserRole` enum với vai trò `OWNER`.
  * Khai báo các hằng số phiên làm việc bảo mật `AUTH_SESSION_KEY` và `USER_ROLE_OWNER`.
  * Xây dựng decorator `@login_required` và placeholder `@permission_required`.
* **User Database Model (`models/user.py`)**:
  * Tạo thực thể `User` ánh xạ bảng `users`.
  * Tích hợp mã hóa mật khẩu Werkzeug an toàn (`set_password`, `check_password`).
* **Auth Service Layer (`services/auth_service.py`)**:
  * Cung cấp logic đăng nhập, đăng xuất, truy xuất session và tự động khởi tạo dữ liệu Owner (`owner`/`owner123`) khi database rỗng.
* **Auto-Migration hỗ trợ ActivityLog**:
  * Tự động thêm cột khóa ngoại `user_id` vào bảng `activity_logs` thông qua migration SQLite của ứng dụng.
* **Test Suite Authentication**: Xây dựng tệp [verify_auth_foundation.py](file:///C:/Users/ADMIN/.gemini/antigravity/brain/bf67f160-279d-4d29-a40f-9141c8b12f29/scratch/verify_auth_foundation.py) để xác thực toàn diện Nền tảng xác thực.

---

## [v2.3] - 2026-06-29

### Added
* **Global Shortcut Manager**: Lắng nghe phím tắt điều hướng nhanh (`Ctrl+Shift+D/C/S/A/I/T/R/O/P`) và focus ô tìm kiếm (`Ctrl+/`).
* **Focus Bypass**: Cơ chế tự động bỏ qua phím tắt khi người dùng đang nhập liệu trong input, textarea, select hoặc contenteditable.
* **VS Code-like Command Palette**:
  * Tích hợp bảng điều khiển tìm kiếm và thực thi lệnh mở qua `Ctrl + K`.
  * Hỗ trợ tìm kiếm, highlight từ khóa, điều khiển bàn phím (`ArrowUp`/`ArrowDown`/`Enter`/`Escape`).
  * Phân biệt lệnh hành động với tiền tố `>` (Ví dụ: `> Backup`, `> New Customer`).
  * Tự động mở Modal tương ứng khi di chuyển giữa các trang nhờ URL search params.
* **Command Palette Stylesheet**: Styling responsive dạng glassmorphism, tương thích thiết bị di động (Fullscreen) và máy tính bảng (90% width).
* **Test Suite Command Palette**: Xây dựng tệp kiểm thử tự động [verify_command_palette.py](file:///C:/Users/ADMIN/.gemini/antigravity/brain/bf67f160-279d-4d29-a40f-9141c8b12f29/scratch/verify_command_palette.py) để xác minh 100% các hành vi phím tắt toàn cục và hoạt động Command Palette.

---

## [v2.2] - 2026-06-28

### Added
* **Universal Design Tokens (`theme.css`)**: Thiết lập bảng màu, bo góc, bóng đổ đồng nhất cho thương hiệu **Tiệm Nhà Nhím**.
* **Hiệu ứng chuyển trang mượt mà (`.app-fade`)**: Chuyển cảnh mượt mà kiểu Single-page-app khi người dùng click menu đổi phân hệ.
* **Trạng thái nạp Khung xương (`Skeleton UI`)**: Tạo animation nhấp nháy chuyển động (`@keyframes skeleton-pulse`) cho bảng dữ liệu và biểu đồ doanh thu trang chủ.
* **Bộ lọc và Nút xóa nhanh**: Thêm nút xóa nhanh `✕` và phím tắt `ESC` cho tất cả ô tìm kiếm. Tự động highlight từ khóa tìm kiếm trực quan.
* **Bảo hiểm kép BFCache**: Tích hợp trình xử lý `pageshow` (`event.persisted`) để tự động triệt tiêu vòng xoay Loader khi nhấn Back trở lại trang trước từ trang in hóa đơn.
* **Block Modals độc lập**: Thiết lập block `{% block modals %}` toàn cục ngoài container Stacking Context trong [base.html](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/templates/layout/base.html) giải quyết lỗi xám và treo màn hình khi mở Modal trên tất cả các trang.

### Changed
* **Local Offline Chart.js**: Tải và lưu trữ thư viện Chart.js cục bộ ngoại tuyến tại [chart.js](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/static/js/libs/chart.js) để phòng tránh sự cố nghẽn mạng từ CDN jsdelivr tại Việt Nam.
* **Hợp nhất phân trang Backend**: Chuyển đổi toàn bộ route sang helper `get_pagination_params` dùng chung, nâng số dòng hiển thị mặc định lên **25 dòng/trang**.
* **Đồng bộ vị trí thông tin phần mềm**: Điều chỉnh vị trí hiển thị Thông tin phần mềm trong trang cài đặt nằm gọn gàng bên dưới Trung tâm sao lưu trong cùng một luồng cuộn.

### Fixed
* **Lỗi Javascript ReferenceError**: Loại bỏ các lệnh khởi tạo import wizard cũ (`setupImportWizard`) không còn tồn tại trong [setting.js](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/static/js/setting.js).
* **Lỗi lặp tài nguyên scripts trong template**: Gộp các block scripts trùng lặp trong [customer/index.html](file:///C:/Users/ADMIN/VS%20CODE/Project/SpaManager/templates/customer/index.html).

### Verification
* **Master Test Suite & Mobile Responsive**: Xây dựng bộ test suite tự động kiểm thử 100% thành công trên cả hai chế độ màn hình máy tính và giả lập di động iPhone X (viewport 375x812), bảo đảm 0 lỗi runtime và 0 lỗi tràn viền ngang (Horizontal Overflow).

---

## [v2.1] - 2026-06-28

### Added
* **Unified Notification System**: Xây dựng module thông báo hợp nhất toàn cục `Notification` (`success`, `error`, `warning`, `info`) dạng stackable Toast với thanh tiến trình trực quan 5 giây và hiệu ứng animation mượt mà.
* **Tài nguyên Tiện ích dùng chung (`utils.js`)**: Tạo tệp tiện ích [utils.js](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/static/js/utils.js) toàn cục, hỗ trợ hàm `formatCurrency` hợp nhất cho toàn bộ hệ thống.
* **Tài liệu Dự án mới**:
  * [CODE_GUIDELINES.md](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/docs/CODE_GUIDELINES.md): Quy định tiêu chuẩn đặt tên, quy ước CSS/JS và thiết kế.
  * [TECH_DEBT.md](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/docs/TECH_DEBT.md): Nhật ký các phần kỹ thuật nợ và hướng xử lý trong v3.0.

### Changed
* **Cầu nối Tương thích Ngược (Compatibility Bridge)**: Cấu hình lại [flash.html](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/templates/layout/flash.html) để chuyển các thông điệp Flask `flash()` truyền thống sang hàng đợi JS client, tự động chuyển đổi sang định dạng Toast mới mà không làm vỡ các module cũ.
* **AJAX API Dịch vụ**: Cập nhật route `/services/delete/<id>` trong [routes/service.py](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/routes/service.py) để trả về phản hồi JSON nếu nhận yêu cầu AJAX.
* **AJAX Client-side Xóa Dịch vụ**: Refactor trang Danh sách Dịch vụ ([templates/service/index.html](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/templates/service/index.html)) để thực hiện thao tác xóa qua AJAX Fetch, làm mờ và xóa dòng dữ liệu khỏi bảng trực quan mà không cần reload trang.
* **Thay thế các hộp thoại thô của trình duyệt**: Thay thế các hàm `alert()` trong module Khách hàng ([templates/customer/index.html](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/templates/customer/index.html)) bằng dịch vụ `Notification.error()`.

### Removed
* **showToast() trùng lặp**: Loại bỏ toàn bộ các hàm `showToast` cục bộ dư thừa trong [appointment.js](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/static/js/appointment.js) và [appointment-calendar.js](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/static/js/appointment-calendar.js).
* **CSS dư thừa**: Xóa bỏ các định nghĩa Toast cục bộ và Toast container z-index trùng lặp trong [appointment.css](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/static/css/pages/appointment.css).
* **formatCurrency() trùng lặp**: Xóa bỏ các hàm định dạng tiền tệ cục bộ trong [invoice.js](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/static/js/invoice.js) và [statistics.js](file:///C:/Users/ADMIN/VS CODE/Project/SpaManager/static/js/statistics.js).
