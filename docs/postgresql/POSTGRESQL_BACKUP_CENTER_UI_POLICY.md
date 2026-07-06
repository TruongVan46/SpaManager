# PostgreSQL Backup Center UI Policy

## 1. Scope
- Tài liệu này định nghĩa chính sách giao diện người dùng (UI Policy) mới cho Trung tâm sao lưu (Backup Center) của SpaManager khi vận hành dưới chế độ cơ sở dữ liệu PostgreSQL.
- **Phạm vi hạn chế:** 
  - Chỉ định nghĩa chính sách và cấu trúc thông tin (Information Architecture) cho giao diện.
  - Không mở lại bất kỳ chức năng sao lưu (backup) hoặc phục hồi (restore) nào trong task này.
  - Không thực hiện bất kỳ hành động sao lưu/phục hồi thực tế nào.
  - Không xóa các đoạn code di sản (legacy SQLite backup/restore flow).

---

## 2. Product Principles
- **PostgreSQL là Cơ sở dữ liệu chính:** Khi ứng dụng chạy trên PostgreSQL, hệ thống in-app SQLite backup/restore flow cũ sẽ không hoạt động.
- **Nghiêm cấm Khôi phục dữ liệu từ Web UI trên Production:** Quy trình khôi phục dữ liệu sản phẩm (Production) chứa nhiều rủi ro lớn (treo ứng dụng, timeout mạng, mất dữ liệu bán phần) và bắt buộc phải được điều phối thông qua CLI / Docker / Railway Management Console theo runbook có sự kiểm duyệt chặt chẽ.
- **Trung tâm sao lưu an toàn (Ops-Safe):** Backup Center phải chuyển hướng từ việc cung cấp các nút thao tác nóng (SQLite-centric buttons) sang việc cung cấp thông tin giám sát, chẩn đoán, cảnh báo an toàn và hướng dẫn thực thi chuẩn hóa (Runbook links).
- **Không cho phép tạo hoặc khôi phục SQLite backup mới:** Chặn hoàn toàn tất cả các yêu cầu tải lên hoặc ghi tệp SQLite trong PostgreSQL mode.

---

## 3. Access Policy
Ma trận quyền hạn truy cập trang Backup Center (`/settings` tab Sao lưu):

| Vai trò / Trạng thái | Quyền truy cập | Hành vi hệ thống |
| :--- | :--- | :--- |
| **Chưa đăng nhập** | Chặn | Chuyển hướng về `/login` |
| **Pending Google user** | Chặn | Chuyển hướng về trang chờ duyệt `/auth/pending` |
| **Rejected / Disabled** | Chặn | Chuyển hướng về `/login` kèm thông báo chặn |
| **STAFF** | Chặn | Trả về lỗi 403 Forbidden |
| **APPROVAL_OWNER** | Chặn | Chuyển hướng về trang duyệt `/approval/pending` |
| **ADMIN** | Cho phép | Cho phép xem ở chế độ Read-Only / Ops-safe |
| **OWNER** | Cho phép | Cho phép xem ở chế độ Read-Only / Ops-safe |

---

## 4. UI Information Architecture
Giao diện Backup Center trong chế độ PostgreSQL sẽ được cấu trúc lại thành 4 khối thông tin chính:

### Khối A: Trạng thái hệ thống (System Status)
Hiển thị tổng quan các tham số cấu hình cơ sở dữ liệu hiện tại của SpaManager để người vận hành nắm rõ:
- **Database Engine:** PostgreSQL
- **Environment:** Local Development (Docker) / Production (Railway)
- **Backup Strategy:** Provider-managed / Runbook-controlled
- **Restore Status:** Restricted (Bị vô hiệu hóa từ Web UI)
- **Tài liệu tham chiếu:** Link trực tiếp đến runbook và chính sách khôi phục `POSTGRESQL_BACKUP_RESTORE_POLICY.md`.

### Khối B: Hướng dẫn Sao lưu (Backup Guidance)
- **Trên Production:**
  - Hiển thị thông báo giải thích rõ ràng rằng sao lưu tự động hàng ngày được quản lý bằng hạ tầng Railway.
  - Không cung cấp nút kích hoạt tạo bản sao lưu vật lý trực tiếp trên giao diện để tránh quá tải tài nguyên mạng/I/O.
- **Dưới Local Development:**
  - Hiển thị hướng dẫn lệnh CLI nhanh để nhà phát triển thực hiện sao lưu thủ công qua Docker PostgreSQL:
    `docker exec -t spamanager-postgres pg_dump -U spamanager -d spamanager_dev -Fc -f /tmp/backup.dump`
- **SQLite:** Hiển thị thông báo cấm tạo mới bản sao lưu SQLite.

### Khối C: Hướng dẫn Khôi phục (Restore Guidance)
- **Production Restore:** Hoàn toàn bị vô hiệu hóa. 
- **Nút bấm Khôi phục (Restore button):** Phải bị ẩn đi hoặc vô hiệu hóa kèm nhãn cảnh báo rõ ràng:
  > *"Khôi phục dữ liệu sản phẩm bị vô hiệu hóa từ giao diện Web. Vui lòng tham khảo quy trình xử lý sự cố đã phê duyệt trong Runbook của hệ thống."*
- **Local Restore Rehearsal:** Hiển thị liên kết hướng dẫn khôi phục diễn tập cục bộ vào DB độc lập để phục vụ kiểm thử.

### Khối D: Quản lý bản sao lưu di sản (Legacy SQLite Artifacts)
Trong trường hợp hệ thống đã được chuyển đổi nhưng trên đĩa vật lý của máy chủ/hộp lưu trữ vẫn tồn tại các file backup SQLite cũ (`.sqlite` hoặc `.db`):
- **Hiển thị danh sách riêng:** Đưa vào khu vực "Bản sao lưu SQLite cũ (Legacy)".
- **Tải xuống / Xóa:** Cho phép tải xuống (`download`) để phục vụ lưu trữ tham khảo hoặc xóa (`delete`) để dọn dẹp dung lượng đĩa.
- **Khôi phục:** Vô hiệu hóa cứng nút khôi phục của các bản ghi này. Hiển thị nhãn cảnh báo: *"File sao lưu SQLite cũ không tương thích với PostgreSQL"*.

---

## 5. Action Policy Matrix

| Hành động | Chế độ SQLite | PostgreSQL (Local Dev) | PostgreSQL (Production) | Trạng thái UI | Ghi chú |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Xem danh sách sao lưu** | Cho phép | Cho phép | Cho phép | Hiển thị bảng | Chỉ hiện metadata hoặc file SQLite cũ nếu còn trên đĩa. |
| **Tạo sao lưu PostgreSQL** | N/A | Cho phép (Chỉ hướng dẫn CLI) | Chặn | Nút Disabled | Production dùng Railway backup. |
| **Tạo sao lưu SQLite** | Cho phép | Chặn | Chặn | Ẩn / Chặn | Không hỗ trợ trên PostgreSQL engine. |
| **Upload file (.db/.sqlite)** | Cho phép | Chặn | Chặn | Ẩn / Chặn | Chặn ngay tại route xử lý upload. |
| **Restore Production DB** | Cho phép | Chặn | Chặn | Ẩn / Vô hiệu hóa | Phải thực hiện thủ công qua CLI Railway. |
| **Restore Local Rehearsal** | Cho phép | Cho phép (Chỉ hướng dẫn CLI) | Chặn | Vô hiệu hóa | Phục hồi qua Docker vào DB độc lập. |
| **Tải xuống SQLite cũ** | Cho phép | Cho phép | Cho phép | Hoạt động | Hỗ trợ tải về máy để lấy dữ liệu lịch sử. |
| **Xóa SQLite cũ** | Cho phép | Cho phép | Cho phép | Hoạt động | Hỗ trợ dọn dẹp file rác trên đĩa. |
| **Restore SQLite cũ** | Cho phép | Chặn | Chặn | Vô hiệu hóa | Chặn cứng để tránh xung đột định dạng dữ liệu. |

---

## 6. UI Text Recommendations
Các đoạn văn bản mẫu (Tiếng Việt) khuyến nghị áp dụng trên giao diện:
- **Cảnh báo động PostgreSQL:**
  > *"Hệ thống đang chạy trên cơ sở dữ liệu PostgreSQL. Các tính năng quản lý cơ sở dữ liệu SQLite in-app đã được chuyển sang chế độ di sản (Legacy) và bị khóa ghi."*
- **Hướng dẫn khôi phục:**
  > *"Khôi phục cơ sở dữ liệu trực tiếp trên Production bị vô hiệu hóa từ giao diện Web để bảo mật. Mọi hành động phục hồi khẩn cấp phải tuân theo tài liệu hướng dẫn vận hành hệ thống (Runbook) thông qua các công cụ hạ tầng."*
- **Danh sách cũ:**
  > *"Bản sao lưu di sản (SQLite). Chỉ cho phép tải xuống hoặc xóa."*

---

## 7. Future Implementation Plan (Sprint Tasks tiếp theo)
1. **Task 6.4.3: Route guard & reopen safe read-only page:** Cập nhật route `/settings` để điều chỉnh luồng nạp dữ liệu bản sao lưu, mở lại giao diện an toàn cho PostgreSQL mode mà không ném ra lỗi ngoại lệ.
2. **Task 6.4.4: PostgreSQL-aware UI cleanup:** Thay đổi nhãn "Cơ sở dữ liệu: SQLite" trong Card thông tin phần mềm thành động dựa trên `backup_engine`. Thiết kế lại khối giao diện tab Sao lưu & Khôi phục theo đúng các nguyên tắc thông tin đã mô tả.
3. **Task 6.4.5: Optional local backup action:** Cân nhắc tích hợp một nút hành động tạo nhanh PostgreSQL dump trên localhost (development environment) bằng cách gọi an toàn lệnh `pg_dump` cục bộ (nếu hệ thống phát hiện chạy trên Docker dev).
4. **Task 6.4.6: Verification & Integration tests:** Viết thêm các ca kiểm thử tích hợp để đảm bảo các cảnh báo hiển thị đúng, các nút bấm bị chặn đúng và không có bất kỳ rò rỉ bảo mật nào xảy ra.
