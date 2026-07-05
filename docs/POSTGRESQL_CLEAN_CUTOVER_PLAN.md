# PostgreSQL Clean Cutover Plan

## Mục đích

Tài liệu này mô tả quy trình chuyển SpaManager sang PostgreSQL fresh database, không migrate dữ liệu test SQLite cũ.

## Assumption

- SQLite hiện tại chỉ chứa dữ liệu test app.
- Không cần preserve customers/services/appointments/invoices cũ.
- Được phép khởi tạo PostgreSQL sạch.
- Trước khi xóa/cutover vẫn cần backup SQLite để rollback kỹ thuật.

## Current state

- Production hiện vẫn SQLite trên Railway Volume.
- `DATABASE_URL` production hiện vẫn trỏ SQLite.
- PostgreSQL chưa production cutover.
- Backup/restore SQLite vẫn giữ nguyên cho tới khi cutover.
- Local PostgreSQL profile đã có từ 5.8.3.
- Schema compatibility report đã có từ 5.8.4.
- Backup/restore strategy đã có từ 5.8.5.

## Clean cutover strategy

Luồng đề xuất:

1. Freeze writes / tạm dừng thao tác dữ liệu.
2. Backup SQLite hiện tại.
3. Provision PostgreSQL database mới.
4. Set `DATABASE_URL` PostgreSQL ở môi trường target.
5. Init schema bằng migration CLI hiện có.
6. Bootstrap owner ban đầu.
7. Verify app health.
8. Run route smoke / QA checklist.
9. Confirm login, user management, customers, services, appointments, invoices, settings.
10. Keep SQLite backup trong rollback window.
11. Khi ổn định mới bỏ dữ liệu SQLite cũ.

## What will NOT be migrated

Không migrate dữ liệu cũ sau:

- `users`
- `customers`
- `services`
- `appointments`
- `invoices`
- `invoice_details`
- `activity_logs`
- `settings`

Nếu cần dữ liệu mẫu, tạo mới sau cutover.

## Owner/admin bootstrap

Audit source hiện tại cho thấy:

- `app.py` gọi `AuthService.seed_owner_if_empty()` khi baseline schema đã sẵn sàng.
- `services/auth_service.py` chỉ seed **owner** mặc định nếu chưa tồn tại.
- `config.py` có các biến:
  - `DEFAULT_OWNER_USERNAME`
  - `DEFAULT_OWNER_PASSWORD`
  - `DEFAULT_OWNER_EMAIL`
- Không thấy flow bootstrap admin riêng trong source hiện tại.
- Admin tạo bằng luồng quản trị user sau khi owner đăng nhập, không phải bootstrap tự động khi boot.

Kết luận:

- Owner bootstrap: có, tự seed lúc boot nếu DB schema đã sẵn sàng.
- Admin bootstrap: không có flow riêng; đây là follow-up nếu production cần preset admin đầu tiên.

## Schema initialization

Lệnh hiện có:

```powershell
.\venv\Scripts\python.exe -m flask --app app db upgrade
```

Nếu cần đánh dấu baseline:

```powershell
.\venv\Scripts\python.exe -m flask --app app db stamp head
```

Ghi nhớ:

- Chạy với `DATABASE_URL` PostgreSQL của môi trường target.
- Kiểm tra `db current` sau đó.
- Không chạy destructive command trên production cho tới khi v5.9/owner xác nhận.

## Environment variables

Checklist env cần có cho production PostgreSQL sau này:

- `DATABASE_URL`
- `SECRET_KEY`
- `DEFAULT_OWNER_PASSWORD`
- `PERSISTENT_ROOT`
- `APP_VERSION`
- `APP_ENV`
- các key bắt buộc khác trong `ProductionConfig`

Chỉ dùng placeholder trong tài liệu, không ghi secret thật.

## Validation checklist

Sau khi init PostgreSQL fresh:

- App boot được.
- DB current đúng revision.
- Login owner/admin được.
- Tạo user staff/admin được.
- Tạo customer được.
- Tạo service được.
- Tạo appointment được.
- Tạo invoice được.
- Export/PDF nếu có.
- Import nếu có.
- Settings hoạt động.
- Activity log ghi được.
- Data audit không báo orphan.
- Route smoke pass.
- QA checklist pass.

## Rollback plan

Nếu PostgreSQL cutover fail:

1. Không xóa SQLite backup.
2. Đổi `DATABASE_URL` về SQLite cũ.
3. Restart app.
4. Kiểm login/app health.
5. Ghi lại lỗi PostgreSQL để xử lý.
6. Không retry cutover khi chưa fix nguyên nhân.

## Destructive action policy

- Không xóa SQLite DB trước khi PostgreSQL boot/login/smoke pass.
- Không xóa backup trong rollback window.
- Mọi lệnh xóa DB cần owner xác nhận rõ.
- Dữ liệu test có thể clean, nhưng vẫn phải thao tác an toàn.

## Impact on old migration-tool plan

- Không cần build full SQLite → PostgreSQL migration tool cho dữ liệu test hiện tại.
- Thay vào đó cần clean cutover runbook.
- Nếu tương lai có dữ liệu thật cần giữ, sẽ quay lại migration strategy riêng.

## Follow-up implementation tasks

1. Provision Railway PostgreSQL.
2. Take final SQLite backup.
3. Configure PostgreSQL `DATABASE_URL`.
4. Run schema init.
5. Bootstrap owner.
6. Run post-cutover QA.
7. Keep rollback SQLite backup.
8. Update backup center PostgreSQL behavior later.
9. Tag v5.9.0 after successful production cutover.

## Final recommendation

- PostgreSQL production cutover chưa làm trong v5.8.6.
- Được phép bỏ qua data migration vì SQLite hiện chỉ là test data.
- Task v5.9 nên đi theo hướng clean PostgreSQL cutover.
- Không được xóa gì cho tới khi có lệnh rõ ở v5.9.

## PostgreSQL test profile and CI plan note

- Tham chiếu: `docs/POSTGRESQL_TEST_CI_PLAN.md`
- Sau clean cutover plan, đây là bước chốt cách test PostgreSQL trước v5.9.
