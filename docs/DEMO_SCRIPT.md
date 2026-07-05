# SpaManager Demo Script

Xem thêm:

- [Demo Data Plan](DEMO_DATA.md)

Tài liệu này dùng cho demo, bàn giao, và thuyết trình. Chỉ sử dụng dữ liệu mẫu hoặc dữ liệu local do bạn tự chuẩn bị. Không dùng dữ liệu khách hàng thật.

## 1. Mục đích

- Dùng cho demo và bàn giao SpaManager.
- Chỉ trình bày với dữ liệu mẫu.
- Không chạy trên production nếu chưa được phép rõ ràng.

## 2. Chuẩn bị trước demo

- [ ] App đang chạy ổn ở local hoặc môi trường demo.
- [ ] Có tài khoản demo OWNER hoặc ADMIN.
- [ ] Không dùng mật khẩu thật khi trình chiếu.
- [ ] Health check hoạt động.
- [ ] UI hiển thị đúng version.
- [ ] Có sẵn một ít khách hàng, dịch vụ, lịch hẹn, và hóa đơn mẫu.
- [ ] Backup Center mở được nếu cần demo.
- [ ] PDF export hoạt động nếu muốn demo in ấn.
- [ ] Trình duyệt để zoom 90% hoặc 100% cho gọn màn hình.
- [ ] Xóa filter hoặc search trước khi bắt đầu nếu danh sách đang trống.

## 3. Tài khoản demo đề xuất

Không ghi mật khẩu thật vào repo.

- **OWNER demo**
  - username: `owner_demo`
  - password: tạo riêng khi demo
- **ADMIN demo**
  - username: `admin_demo`
  - password: tạo riêng khi demo
- **STAFF demo**
  - username: `staff_demo`
  - password: tạo riêng khi demo

Ghi nhớ:

- Không dùng tài khoản production thật.
- Không commit mật khẩu demo.
- Nếu demo trên Railway production, hãy xóa hoặc khóa tài khoản demo sau buổi trình bày nếu cần.

## 4. Dữ liệu mẫu đề xuất

Toàn bộ dữ liệu dưới đây chỉ là gợi ý để nhập thủ công hoặc import local:

### Khách hàng mẫu

- Nguyễn Demo A — 0900000001 — demo.a@example.test
- Trần Demo B — 0900000002 — demo.b@example.test
- Lê Demo C — 0900000003 — demo.c@example.test

### Dịch vụ mẫu

- Massage thư giãn — 300000
- Chăm sóc da cơ bản — 450000
- Gội đầu dưỡng sinh — 180000
- Combo thư giãn — 650000

### Lịch hẹn mẫu

- Nguyễn Demo A — Massage thư giãn — hôm nay 09:00 — Đã xác nhận
- Trần Demo B — Chăm sóc da cơ bản — hôm nay 14:00 — Chờ xác nhận
- Lê Demo C — Combo thư giãn — ngày mai 10:00 — Chờ xác nhận

### Hóa đơn mẫu

- Nguyễn Demo A — Massage thư giãn — Tiền mặt — Đã thanh toán
- Trần Demo B — Chăm sóc da cơ bản — Chuyển khoản — Đã thanh toán

Lưu ý:

- Đây chỉ là dữ liệu gợi ý nhập local hoặc manual.
- Không phải seed production tự động.

## 5. Cách chuẩn bị dữ liệu demo

### Option A — Nhập thủ công qua UI

- Tạo khách hàng.
- Tạo dịch vụ.
- Tạo lịch hẹn.
- Tạo hóa đơn.

### Option B — Dùng template import có sẵn

- Dùng file template trong:
  - `static/templates/import/customers_template.xlsx`
  - `static/templates/import/services_template.xlsx`
- Tạo bản copy local.
- Điền dữ liệu demo.
- Import qua UI.
- Không commit file đã điền dữ liệu.

### Option C — Script local-only nếu sau này cần

- Chỉ chạy local hoặc dev.
- Không tự chạy trên production.
- Không commit output cơ sở dữ liệu.
- Tài liệu này chỉ mô tả kế hoạch; chưa cần tạo script tự động.

## 6. Kịch bản demo 10–15 phút

### Bước 1 — Đăng nhập và giới thiệu Dashboard

- Đăng nhập bằng tài khoản OWNER hoặc ADMIN demo.
- Giới thiệu Dashboard:
  - số khách hàng
  - lịch hẹn
  - doanh thu
  - shortcut quản trị nếu có
- Nói ngắn: hệ thống có phân quyền OWNER / ADMIN / STAFF.

### Bước 2 — Quản lý khách hàng

- Mở danh sách khách hàng.
- Tìm kiếm khách hàng demo.
- Mở chi tiết khách hàng.
- Giới thiệu:
  - thông tin khách
  - lịch sử lịch hẹn
  - lịch sử hóa đơn
  - tạo lịch hẹn hoặc hóa đơn từ trang khách hàng nếu có

### Bước 3 — Quản lý dịch vụ

- Mở danh sách dịch vụ.
- Giới thiệu giá dịch vụ.
- Thêm hoặc sửa một dịch vụ mẫu nếu muốn.

### Bước 4 — Tạo lịch hẹn

- Tạo lịch hẹn cho khách demo.
- Chọn dịch vụ.
- Chọn thời gian.
- Cập nhật trạng thái nếu cần.
- Mở lịch hoặc calendar nếu có.

### Bước 5 — Tạo hóa đơn

- Tạo hóa đơn cho khách demo.
- Chọn dịch vụ.
- Kiểm tra tổng tiền.
- Chọn phương thức thanh toán.
- In hoặc xuất PDF nếu cần.

### Bước 6 — Thống kê / báo cáo

- Mở Statistics.
- Chọn khoảng ngày.
- Xem doanh thu, top khách hàng, top dịch vụ.
- Export Excel hoặc PDF nếu cần.

### Bước 7 — Quản trị nhanh

Dành cho OWNER hoặc ADMIN:

- Mở User Management.
- Giới thiệu role OWNER / ADMIN / STAFF.
- Mở Activity Log.
- Mở Recycle Bin nếu có dữ liệu xóa mềm.
- Mở Settings hoặc Backup Center.

### Bước 8 — Backup và vận hành

- Mở Backup Center.
- Giới thiệu backup metadata và version.
- Nếu cần demo kỹ thuật:
  - chạy `ops diagnostics`
  - chạy `data audit`
- Không chạy restore thật trong demo nếu không cần.

## 7. Kịch bản demo phân quyền STAFF

- Đăng nhập bằng tài khoản STAFF demo.
- Cho thấy STAFF dùng được các chức năng nghiệp vụ chính.
- STAFF không vào Users, Settings, Activity Log, Recycle Bin, hoặc Statistics nếu đúng quyền hiện tại.
- Đăng xuất.

## 8. Demo kỹ thuật cho người nghe chuyên sâu

- Giới thiệu health check.
- Giới thiệu backup/restore hardening.
- Giới thiệu `data audit`.
- Giới thiệu `data repair` ở chế độ dry-run.
- Giới thiệu `perf profile`.
- Giới thiệu `ops diagnostics --skip-performance`.

Cảnh báo:

- Không chạy `data repair --apply --yes` khi demo trên production.
- Không restore production DB trong lúc demo.

## 9. Checklist sau demo

- [ ] Đăng xuất tài khoản demo.
- [ ] Khóa hoặc xóa tài khoản demo nếu demo trên production.
- [ ] Xóa dữ liệu demo nếu không cần giữ lại.
- [ ] Tạo backup nếu có thay đổi dữ liệu quan trọng.
- [ ] Kiểm tra Activity Log.
- [ ] Không commit file import hoặc demo local.

## 10. Lỗi thường gặp khi demo

- Không thấy dữ liệu: kiểm tra filter ngày hoặc search.
- Không đăng nhập được: kiểm tra username/password demo hoặc rate limit.
- Không in PDF đúng: xuất file mới thay vì mở file cũ.
- Không thấy backup: kiểm tra persistent root và backup folder.
- STAFF bị chặn admin page: đây là phân quyền đúng.

## 11. Không làm trong demo

- Không dùng dữ liệu khách thật.
- Không hiển thị mật khẩu thật.
- Không restore DB thật khi đang trình chiếu.
- Không chạy repair apply.
- Không xóa vĩnh viễn dữ liệu nếu chưa backup.
- Không commit file temp, import, hoặc backup.
