# SpaManager Demo Data Plan

Tài liệu này dùng để chuẩn hóa dữ liệu demo sao cho mỗi lần trình bày, bàn giao, hoặc rehearsal đều có thể chuẩn bị giống nhau, an toàn, và không dùng dữ liệu thật.

## Mục đích

- Chuẩn hóa bộ dữ liệu demo theo cách dễ lặp lại.
- Giúp dashboard, statistics, PDF, activity log, recycle bin, settings, và backup center có dữ liệu đủ để trình bày.
- Tránh vô tình dùng dữ liệu khách hàng thật hoặc artifact runtime.

## Nguyên tắc an toàn

- Chỉ dùng dữ liệu giả, local-only, hoặc demo-only.
- Email demo dùng domain `example.test`.
- Không dùng số điện thoại, email, tên, hoặc nội dung thật của khách hàng.
- Không commit database local, backup file, PDF export, import tạm, hoặc file lỗi.
- Không restore production tùy tiện.
- Không ghi password demo thật vào repo.

## Chuẩn bị môi trường

- Local demo là lựa chọn ưu tiên.
- Staging/demo environment có thể dùng nếu được tách biệt rõ.
- Production chỉ nên dùng để smoke check, không seed dữ liệu demo bừa bãi.

## Bộ dữ liệu demo nên có

### 1) Tài khoản demo

Đề xuất có 3 tài khoản mẫu:

| Vai trò | Email mẫu | Ghi chú |
|---|---|---|
| OWNER | `owner_demo@example.test` | Tài khoản quản trị chính |
| ADMIN | `admin_demo@example.test` | Tài khoản quản trị hỗ trợ |
| STAFF | `staff_demo@example.test` | Tài khoản thao tác nghiệp vụ |

> Password: đặt cục bộ khi demo, không commit.

### 2) Khách hàng fake

Nên có khoảng 5–8 khách hàng để danh sách và tìm kiếm trông tự nhiên.

Ví dụ:

- Nguyễn An — `0900000001` — `nguyen.an@example.test`
- Trần Bình — `0900000002` — `tran.binh@example.test`
- Lê Chi — `0900000003` — `le.chi@example.test`
- Phạm Dung — `0900000004` — `pham.dung@example.test`
- Hoàng Em — `0900000005` — `hoang.em@example.test`

### 3) Dịch vụ fake

Nên có nhiều mức giá và thời lượng khác nhau:

| Tên dịch vụ | Giá | Thời lượng | Ghi chú |
|---|---:|---:|---|
| Chăm sóc da cơ bản | 450000 | 60 phút | Nhóm chăm sóc da |
| Massage thư giãn | 300000 | 45 phút | Dịch vụ phổ biến |
| Gội đầu dưỡng sinh | 180000 | 30 phút | Dịch vụ ngắn |
| Trị liệu cổ vai gáy | 550000 | 75 phút | Dịch vụ chuyên sâu |
| Combo chăm sóc da + massage | 650000 | 90 phút | Phục vụ demo upsell |

### 4) Lịch hẹn fake

Nên có đủ trạng thái để dashboard/statistics nhìn sống động:

- Chờ xác nhận
- Đã xác nhận
- Hoàn thành
- Đã hủy
- No-show nếu ứng dụng có hỗ trợ

Nên rải lịch:

- Hôm nay
- Trong tuần này
- Trong tháng này

để statistics và dashboard có dữ liệu tự nhiên.

### 5) Hóa đơn / thanh toán fake

Nên có:

- Hóa đơn đã thanh toán
- Hóa đơn chờ thanh toán nếu app hỗ trợ
- Nhiều phương thức thanh toán nếu app hỗ trợ
- Ít nhất một hóa đơn đủ để test PDF Unicode

### 6) Activity Log

Nên có log từ các thao tác thật trong app, ví dụ:

- Login
- Tạo / sửa khách hàng
- Tạo lịch hẹn
- Tạo hóa đơn
- Tạo backup test nếu an toàn

Không nên sửa DB trực tiếp chỉ để “làm đẹp” log nếu chưa cần.

### 7) Recycle Bin

Nên có 1 item fake đã xóa mềm để demo:

- restore
- cảnh báo xóa vĩnh viễn

Không xóa vĩnh viễn dữ liệu thật.

### 8) Backup Center

Nên có backup demo nếu an toàn:

- Ghi tên backup rõ ràng
- Metadata version rõ ràng
- Không commit backup file
- Restore chỉ local/demo

### 9) Import templates

Nên tận dụng template sẵn có:

- `static/templates/import/customers_template.xlsx`
- `static/templates/import/services_template.xlsx`

Nếu cần, có thể tạo bản copy local rồi điền dữ liệu demo để import thử.

## Thứ tự tạo dữ liệu

1. Tạo tài khoản demo.
2. Tạo dịch vụ.
3. Tạo khách hàng.
4. Tạo lịch hẹn.
5. Tạo hóa đơn / thanh toán.
6. Tạo vài thao tác để sinh Activity Log.
7. Tạo 1 item trong Recycle Bin.
8. Tạo backup demo nếu cần.
9. Kiểm tra dashboard và statistics.

## Checklist demo data sẵn sàng

- Dashboard có số liệu.
- Customers có dữ liệu.
- Services có dữ liệu.
- Appointments có nhiều trạng thái.
- Invoices có PDF test được.
- Statistics có dữ liệu theo ngày / tháng.
- Activity Log có log.
- Recycle Bin có item fake.
- Backup Center có thể tạo backup demo nếu cần.

## Dọn sau demo

- Xóa hoặc reset dữ liệu fake nếu không cần giữ.
- Không commit database/backup/import artifacts.
- Kiểm tra `git status`.
- Ghi chú rõ nếu đã tạo backup demo.

## Không làm

- Không dùng dữ liệu thật.
- Không commit file SQLite.
- Không commit backup.
- Không commit file import đã điền dữ liệu.
- Không restore production tùy tiện.
- Không ghi password vào docs.

## Có cần seed command không?

Hiện tại tài liệu này chỉ mô tả kế hoạch, chưa thêm seed command tự động.

Nếu sau này cần seed local-only:

- Command phải từ chối chạy trên production.
- Phải có flag xác nhận rõ ràng.
- Chỉ tạo dữ liệu fake.
- Không ghi password thật vào repo.
- Có thể reset local demo an toàn.

## Mẫu bảng dữ liệu

### Demo users

| Vai trò | Email mẫu | Ghi chú |
|---|---|---|
| OWNER | `owner_demo@example.test` | Quản trị chính |
| ADMIN | `admin_demo@example.test` | Quản trị phụ |
| STAFF | `staff_demo@example.test` | Nhân viên thao tác |

### Customers

| Tên | SĐT giả | Email giả | Ghi chú |
|---|---|---|---|
| Nguyễn An | 0900000001 | nguyen.an@example.test | Khách demo chính |
| Trần Bình | 0900000002 | tran.binh@example.test | Khách demo phụ |

### Services

| Tên dịch vụ | Giá | Thời lượng | Ghi chú |
|---|---:|---:|---|
| Massage thư giãn | 300000 | 45 phút | Dịch vụ phổ biến |
| Chăm sóc da cơ bản | 450000 | 60 phút | Dịch vụ phổ biến |

### Appointments

| Khách hàng | Dịch vụ | Thời gian | Trạng thái | Ghi chú |
|---|---|---|---|---|
| Nguyễn An | Massage thư giãn | Hôm nay 09:00 | Đã xác nhận | Demo dashboard |
| Trần Bình | Chăm sóc da cơ bản | Hôm nay 14:00 | Chờ xác nhận | Demo workflow |

### Invoices

| Khách hàng | Dịch vụ | Trạng thái thanh toán | Phương thức | Ghi chú |
|---|---|---|---|---|
| Nguyễn An | Massage thư giãn | Đã thanh toán | Tiền mặt | PDF test |
| Trần Bình | Chăm sóc da cơ bản | Chờ thanh toán | Chuyển khoản | Demo stats |

