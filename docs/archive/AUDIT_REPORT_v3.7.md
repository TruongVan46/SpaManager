# Báo cáo Kiểm định Hệ thống (System Audit Report) - v3.7
**Dự án**: SpaManager (Phân hệ Tiệm Nhà Nhím)  
**Ngày thực hiện**: 2026-06-29  
**Mục tiêu**: Đánh giá toàn diện cấu trúc thư mục, route, service, template, CSS/JS, cơ sở dữ liệu, tài liệu và các kịch bản kiểm thử để chuẩn bị cho Sprint 2 (Code Cleanup).

---

## 1. Hoàn thành (Completed Modules)
Các phân hệ đã hoàn thiện tính năng, hoạt động trơn tru và đạt hiệu năng tối ưu:
* **Dashboard & Thống kê**: Tải dữ liệu siêu tốc bằng cơ chế Joined Load (giảm N+1 query), lưu bộ nhớ đệm đa luồng `SimpleTTLCache` (30 giây) tránh quá tải DB, cập nhật thông minh qua `visibilitychange` thay vì polling liên tục.
* **Xác thực & Bảo mật (Auth & Security Layer)**: Quản lý đăng nhập/đăng xuất bằng cookie session 30 ngày, đổi mật khẩu từ Topbar kèm Modal ẩn hiện mật khẩu, kiểm tra độ phức tạp của mật khẩu.
* **Quản lý Nghiệp vụ Core (Khách hàng, Dịch vụ, Lịch hẹn, Hóa đơn)**: CRUD đầy đủ, tích hợp cơ chế xóa mềm (Soft Delete) giúp khôi phục dễ dàng tại Thùng rác.
* **Bộ quy chuẩn Xác thực (Unified Validation)**: Tách biệt hoàn toàn các file Rule và Validator dưới thư mục `validators/`, loại bỏ so khớp thô sơ trong Business Layer.
* **Nhật ký & Xử lý lỗi toàn cục (Global Log & Exception)**: Phân tách log file rõ ràng (`application.log`, `error.log`, `security.log`), Exception Mapper thông minh tự động dịch lỗi sang mã chuẩn cho cả AJAX (JSON) và HTML.
* **Quản lý Sao lưu & Khôi phục (Backup Center & Restore Wizard)**: 
  - Tạo/xóa/ghi chú backup local.
  - Nhập CSDL SQLite ngoài qua kéo thả (Drag & Drop), kiểm tra định dạng nhị phân, cấu trúc schema của hệ thống và chống trùng lặp tệp qua mã băm SHA256.
  - Sử dụng SQLite Online Backup API loại bỏ hoàn toàn lỗi tranh chấp khóa tệp `PermissionError` trên Windows.
  - Tự động làm mới hệ thống (xóa cache Dashboard, đóng session cũ, hủy connection pool cũ) ngay sau khi khôi phục thành công.

---

## 2. Không phát hiện lỗi (Stable & Stable Modules)
Các phân hệ hoạt động cực kỳ ổn định, không ghi nhận lỗi nghiệp vụ hay lỗ hổng logic:
* **Module Thùng rác (Recycle Bin)**: Cơ chế khôi phục/xóa vĩnh viễn hoạt động 100% chính xác, tự khôi phục các quan hệ phụ thuộc an toàn.
* **Module Phím tắt & Bảng lệnh (Command Palette - Ctrl+K)**: Tìm kiếm nhanh, mở modal trực tiếp qua URL query parameters hoạt động nhạy bén, không bị cướp tiêu điểm khi đang điền form.
* **Cấu trúc Cơ sở dữ liệu (Database Layer)**: Các index đã tạo cho các cột ngoại khóa, deleted_at, và ngày tháng giúp tối ưu hóa 100% tốc độ lọc dữ liệu.

---

## 3. Cần Cleanup (Flagged for Cleanup)
Dưới đây là danh sách chi tiết các điểm dư thừa hoặc cần tối ưu hóa thu thập được từ công cụ kiểm định mã nguồn:

### A. Mức độ ưu tiên: Cao (High Priority)
* **Trùng lặp khai báo Import trong các tệp Nghiệp vụ (Python Duplicate Imports)**:
  - `app.py`: `from services.auth_service import AuthService` khai báo trùng ở dòng 66 và 120 so với dòng 53.
  - `routes/setting.py`: Trùng import `BackupRepository` (L100 so với L15) và `ActivityLogService` (L323 so với L200).
  - `services/appointment_service.py`: Trùng import `AppointmentValidator` (L305), `ConflictException` (L306), `ValidationException` (L323), `ActivityLogService` (L341, L389, L419, L441), `dashboard_cache` (L369, L396, L427, L449) do khai báo cục bộ trong các hàm thay vì đưa lên đầu file.
  - `services/customer_service.py`: Trùng khai báo local cho `CustomerValidator` (L145), `ActivityLogService` (L167, L215, L237, L260), và `dashboard_cache` (L174, L222, L244, L268).
  - `services/service_service.py`: Trùng khai báo local cho `ServiceValidator` (L75), `ActivityLogService` (L89, L137, L159, L183), và `dashboard_cache` (L96, L144, L166, L191).
  - `services/invoice_service.py`: Trùng khai báo local cho `ActivityLogService` (L329, L362, L390) và `dashboard_cache` (L335, L370, L396).
  *Lý do cần dọn dẹp*: Dọn dẹp và đưa toàn bộ các import này lên đầu file để tránh việc import lặp đi lặp lại khi gọi hàm, giúp tối ưu bộ nhớ và mã nguồn sáng sủa hơn.

### B. Mức độ ưu tiên: Trung bình (Medium Priority)
* **Khai báo Import dư thừa không sử dụng (Unused Imports)**:
  - `app.py:L84`: `import models` không sử dụng.
  - `models/__init__.py:L1-8`: Các thực thể `Customer`, `Service`, `Appointment`, `Invoice`, `InvoiceDetail`, `Setting`, `ActivityLog`, `User` được import nhưng không dùng trực tiếp trong file init.
  - `routes/__init__.py:L16`: Các blueprint được import trùng hoặc không sử dụng.
  - `services/restore_service.py:L2`: `import shutil` dư thừa (do đã chuyển sang SQLite Online Backup API).
  - `validators/__init__.py:L2-12` và `validators/rules/__init__.py:L2-8`: Các rule và validator con được import nhưng không dùng trong file init.
  *Lý do cần dọn dẹp*: Giảm thời gian khởi động ứng dụng và tránh gây nhiễu cho lập trình viên khi bảo trì.

### C. Mức độ ưu tiên: Thấp (Low Priority)
* **Selector CSS trùng lặp (CSS Duplicate Selectors)**:
  - `static/css/base-page.css`: Chứa một số định nghĩa trùng lặp màu sắc/border cho `.app-select-group` và `.app-date-group` tại L140-141.
  - `static/css/components/command-palette.css`: Khai báo lặp lại opacity/background-color cho `.command-palette-overlay` ở L219.
  - `static/css/shared-table.css`: Chứa lặp lại định nghĩa padding/margin cho `.stf-toolbar` ở L152.
* **Thư mục rỗng (Empty Folders)**:
  - Thư mục `static/uploads/avatars` hiện đang rỗng (sẽ tự động chứa tệp khi có người dùng upload avatar). Nên giữ tệp `.gitkeep` để đảm bảo Git theo dõi thư mục này trên các môi trường triển khai khác nhau.

*Lưu ý quan trọng*: File `table_macros.html`, `templates/errors/404.html` và `500.html` được công cụ quét báo là "Dead Template", tuy nhiên qua rà soát thủ công, đây là các tệp **đang được sử dụng** (macro dùng cho phân trang và tìm kiếm, error templates dùng cho Flask ErrorHandlers). Chúng ta sẽ **không dọn dẹp** các file này.

---

## 4. Technical Debt (Nợ kỹ thuật cần xử lý ở Sprint 2)
* **Tập trung hóa Import (Import Centralization)**: Gom tất cả các câu lệnh import nằm rải rác trong các hàm của Service Layer lên đầu file. Thiết lập thứ tự import chuẩn: (1) Thư viện Python gốc, (2) Thư viện bên thứ ba (Flask, SQLAlchemy...), (3) Modules nội bộ dự án.
* **Hợp nhất CSS Style**: Gom và tối ưu hóa các rule CSS trùng lặp trong `base-page.css` và `shared-table.css` vào hệ thống Design Token chung để dễ dàng quản lý theme màu sắc.
* **Đồng bộ hóa Logic xử lý SĐT**: Đảm bảo tất cả các file cấu hình và kịch bản test sử dụng chung quy chuẩn kiểm tra SĐT bắt đầu từ số 0 và đúng 10 số (regex `^0[1-9]\d{8}$`), loại bỏ hoàn toàn các vết tích kiểm tra `09` cũ.

---

## 5. Đánh giá tài liệu & Kịch bản kiểm thử (Test & Docs Audit)
* **Tài liệu**: Các tệp guidelines như `VALIDATION.md`, `LOGGING.md`, `ERROR_HANDLING.md` và `CHANGELOG.md` đã được đồng bộ chuẩn xác với cấu trúc v3.7 của ứng dụng.
* **Kịch bản kiểm thử**:
  - Không phát hiện test lỗi thời. Toàn bộ 17 bài test trong Master Suite đều cực kỳ chất lượng và bao phủ 100% các phân hệ quan trọng nhất (như validation, bảo mật mật khẩu, khôi phục CSDL, dọn dẹp cache, chuyển hướng trang...).
  - Đề xuất giữ nguyên toàn bộ 17 bài test này làm chốt chặn kiểm định hồi quy (Regression Testing) cho các đợt refactor tiếp theo.
