# SpaManager QA Checklist

Checklist này dùng để kiểm tra nhanh sau deploy, sau demo, và trước khi chốt release.

## Mục đích

- Xác nhận app còn sống sau deploy.
- Xác nhận version hiển thị đúng.
- Xác nhận login/logout và các workflow chính vẫn ổn.
- Xác nhận các trang danh sách, search, filter, backup, export, PDF, mobile không vỡ.
- Xác nhận git status sạch, không có runtime artifact bị commit nhầm.

## Khi nào dùng

- Sau Railway deploy.
- Trước demo hoặc bàn giao.
- Sau khi sửa UI, workflow, backup/restore, export, hoặc quyền truy cập.
- Trước khi chốt checkpoint hoặc tag release.

## Nguyên tắc an toàn

- Không dùng dữ liệu khách hàng thật.
- Không restore production nếu chưa có backup và chưa được xác nhận.
- Không chạy thao tác phá hủy trên production nếu chưa kiểm tra kỹ.
- Không commit artifact runtime như backup, import tạm, PDF xuất thử.
- Không ghi secret, password, token, hoặc database URL vào tài liệu hay log.

## Checklist nhanh 10 phút

### Pre-check

- [ ] GitHub Actions đang xanh.
- [ ] Railway deploy thành công.
- [ ] `GET /health` trả về 200.
- [ ] Railway logs không có lỗi 500 mới.
- [ ] `APP_VERSION` production hiển thị đúng.
- [ ] `git status --short` sạch, không có artifact runtime.
- [ ] Đã có backup mới trước khi kiểm tra thao tác nguy hiểm.
- [ ] Sau rehearsal import/export/PDF/backup, đã kiểm `git status --short` để chắc không staged artifact.
- [ ] Nếu phát hiện lỗi, đã ghi lại ngắn gọn trong issue/incident note.

### Auth / account

- [ ] Login OWNER thành công.
- [ ] Logout thành công.
- [ ] Sai mật khẩu báo lỗi đúng, không lộ thông tin nhạy cảm.
- [ ] Rate limit hoạt động đúng.
- [ ] Đổi mật khẩu hoạt động.
- [ ] Profile mở được.
- [ ] STAFF không vào được trang admin.

### Dashboard

- [ ] Dashboard mở được.
- [ ] Không lỗi khi dữ liệu ít hoặc rỗng.
- [ ] Card số liệu hiển thị hợp lý.
- [ ] Link nhanh nếu có hoạt động đúng.

### Customers / Services / Appointments

- [ ] Danh sách mở được.
- [ ] Search / filter / live search hoạt động.
- [ ] Page size và pagination không vỡ layout.
- [ ] Tạo / sửa dữ liệu test chạy bình thường.
- [ ] Customer detail/history mở được nếu có.
- [ ] Empty state hiển thị rõ.

### Invoices / Payments / PDF

- [ ] Danh sách hóa đơn mở được.
- [ ] Chi tiết hóa đơn mở được.
- [ ] Trạng thái thanh toán hiển thị đúng.
- [ ] PDF Unicode xuất được.
- [ ] Export hoạt động nếu có.
- [ ] Không commit file PDF sinh ra.

### Statistics / Reports

- [ ] Trang thống kê mở được.
- [ ] Filter ngày hoạt động.
- [ ] Không lỗi khi không có dữ liệu.
- [ ] Bảng / biểu đồ không vỡ layout.
- [ ] Export hoạt động nếu có.

### User Management / Admin

- [ ] OWNER vào được User Management.
- [ ] ADMIN đúng quyền theo thiết kế.
- [ ] STAFF bị chặn.
- [ ] Reset password không lộ password.
- [ ] Disable user hoạt động nếu test local.
- [ ] Không tự khóa OWNER cuối cùng.

### Activity Log

- [ ] Danh sách mở được.
- [ ] Filter / search hoạt động nếu có.
- [ ] Log có ghi cho thao tác chính.
- [ ] Không lộ password, secret, token.

### Recycle Bin

- [ ] Mở được thùng rác.
- [ ] Empty state hiển thị rõ.
- [ ] Restore hoạt động trên dữ liệu demo/local.
- [ ] Permanent delete hiện cảnh báo rõ.
- [ ] Không test permanent delete trên dữ liệu thật.

### Settings / Backup Center

- [ ] Settings mở được.
- [ ] Version hiển thị đúng.
- [ ] Backup Center mở được.
- [ ] Tạo backup test an toàn nếu cần.
- [ ] Metadata backup ghi version đúng.
- [ ] Restore chỉ rehearsal local/demo.
- [ ] Cảnh báo nguy hiểm hiển thị rõ.

### Import / templates

- [ ] Template import tải được.
- [ ] Import file hợp lệ chạy được nếu có.
- [ ] Import lỗi sinh báo cáo lỗi nếu có.
- [ ] Không commit file tạm.

### Error pages

- [ ] 404 hiển thị thân thiện.
- [ ] 500 không lộ stack trace ở production.
- [ ] Permission denied hiển thị rõ.

### Mobile / tablet

- [ ] Login page không vỡ.
- [ ] Sidebar / navigation ổn.
- [ ] Customers list đọc được.
- [ ] Appointment list / calendar không vỡ.
- [ ] Invoice detail / PDF action dùng được.
- [ ] Settings / Backup Center gọn.
- [ ] Toolbar / search / filter không chồng quá rối.

### Post-check

- [ ] `git status` sạch.
- [ ] Không có `database/backup`, `static/uploads/import`, PDF export artifact bị add nhầm.
- [ ] Railway logs không tăng lỗi mới.
- [ ] Nếu có dữ liệu fake, đã dọn hoặc ghi chú rõ.
- [ ] Nếu có backup test, đã ghi tên / version rõ.
- [ ] Nếu vừa rehearsal import/export/PDF/backup, đã dọn file tạm và kiểm `git status --short`.
- [ ] Nếu có issue/incident note, đã lưu link hoặc mô tả đủ để truy lại sau này.

## Checklist đầy đủ 20 phút

Thực hiện toàn bộ nhóm A đến P bên dưới:

### A. Pre-check

- GitHub Actions xanh.
- Railway deploy thành công.
- `/health` trả 200.
- Logs không có lỗi 500 mới.
- `APP_VERSION` production đúng.
- `git status --short` sạch.
- Có backup mới trước khi test thao tác nguy hiểm.

### B. Auth / account

- Login OWNER thành công.
- Logout thành công.
- Sai mật khẩu báo lỗi đúng.
- Rate limit không lộ thông tin nhạy cảm.
- Đổi mật khẩu hoạt động.
- Profile mở được.
- Inactive user không login được nếu có user test.
- STAFF không vào được trang admin.

### C. Dashboard

- Dashboard mở được.
- Không lỗi khi dữ liệu ít / rỗng.
- Card số liệu hiển thị hợp lý.
- Quick links hoạt động nếu có.

### D. Customers

- Danh sách mở được.
- Search / filter / live search hoạt động.
- Page size / pagination không vỡ.
- Tạo customer fake.
- Edit customer.
- Duplicate phone / email bị chặn nếu rule có.
- Customer detail / history mở được.
- Soft delete / restore hoạt động nếu phù hợp.

### E. Services

- Danh sách mở được.
- Search / filter hoạt động.
- Tạo / sửa service fake.
- Giá / thời lượng validate đúng.
- Empty state ổn.

### F. Appointments

- Danh sách / lịch hẹn mở được.
- Tạo lịch hẹn fake.
- Đổi trạng thái nếu có.
- Filter ngày / trạng thái hoạt động.
- Không lỗi khi ngày không có lịch.
- Mobile / tablet không vỡ quá rõ.

### G. Invoices / payments / PDF

- Danh sách hóa đơn mở được.
- Tạo hóa đơn test nếu workflow cho phép.
- Chi tiết hóa đơn mở được.
- Trạng thái thanh toán hiển thị đúng.
- PDF Unicode xuất được.
- Export hoạt động nếu có.
- Không commit file PDF sinh ra.

### H. Statistics / reports

- Trang thống kê mở được.
- Filter ngày hoạt động.
- Không lỗi khi không có dữ liệu.
- Biểu đồ / bảng không vỡ layout.
- Export hoạt động nếu có.

### I. User Management / Admin

- OWNER vào được User Management.
- ADMIN đúng quyền theo thiết kế.
- STAFF bị chặn.
- Tạo / sửa user test nếu cần.
- Reset password không lộ password.
- Disable user hoạt động nếu test local.
- Không tự khóa OWNER cuối cùng.

### J. Activity Log

- Danh sách mở được.
- Filter / search hoạt động nếu có.
- Có log cho thao tác chính.
- Không lộ password / secret / token.

### K. Recycle Bin

- Mở được thùng rác.
- Empty state hiển thị rõ.
- Restore hoạt động trên demo/local.
- Permanent delete có cảnh báo rõ.
- Không test permanent delete trên dữ liệu thật.

### L. Settings / Backup Center

- Settings mở được.
- Version hiển thị đúng.
- Backup Center mở được.
- Tạo backup test an toàn nếu cần.
- Backup metadata ghi version đúng.
- Restore chỉ rehearsal local/demo.
- Cảnh báo nguy hiểm hiển thị rõ.

### M. Import / templates

- Template import tải được.
- Import file hợp lệ chạy được nếu có.
- Import lỗi sinh báo cáo lỗi nếu có.
- Không commit file tạm.

### N. Error pages

- 404 thân thiện.
- 500 không lộ stack trace ở production.
- Permission denied rõ ràng.

### O. Mobile / tablet

- Login page ổn.
- Sidebar / navigation ổn.
- Customers list đọc được.
- Appointment list / calendar ổn.
- Invoice detail / PDF action ổn.
- Settings / Backup Center ổn.
- Toolbar / search / filter không chồng quá rối.

### P. Post-check

- `git status` sạch.
- Không có `database/backup`, `static/uploads/import`, PDF export artifact bị add nhầm.
- Logs không tăng lỗi mới.
- Nếu có dữ liệu fake, đã dọn hoặc ghi chú rõ.
- Nếu có backup test, ghi rõ tên / version.

## Mẫu ghi kết quả QA

| Ngày | Môi trường | Version | Người test | Kết quả | Ghi chú |
|---|---|---|---|---|---|

## Mẫu issue / bug report

- Màn hình:
- Vai trò:
- Bước lặp lại:
- Kết quả mong đợi:
- Kết quả thực tế:
- Screenshot / log:
- Mức độ: P0 / P1 / P2

## PostgreSQL backup/restore rehearsal note

- Trước release hay rehearsal nguy hiểm, tham chiếu `docs/POSTGRESQL_BACKUP_RESTORE_STRATEGY.md`.
- Không restore production nếu chưa có backup và chưa có plan engine-specific rõ ràng.

## PostgreSQL clean cutover rehearsal note

- Trước rehearsal hoặc release lớn, đọc `docs/POSTGRESQL_CLEAN_CUTOVER_PLAN.md` nếu đang chuẩn bị chuyển sang PostgreSQL.

## PostgreSQL test profile and CI plan note

- Trước rehearsal hoặc release lớn, đọc `docs/POSTGRESQL_TEST_CI_PLAN.md` nếu đang chuẩn bị PostgreSQL CI.
