# PostgreSQL Migration Audit

## Mục đích

Tài liệu này ghi nhận hiện trạng SQLite của SpaManager và các yêu cầu cần chuẩn bị trước khi chuyển sang PostgreSQL. Đây là tài liệu nền cho lộ trình v5.8 và v5.9, không phải tài liệu cutover.

## Trạng thái hiện tại

- Production hiện đang dùng SQLite trên Railway Volume.
- `DATABASE_URL` production hiện tại là `sqlite:////app/database/spa.db`.
- `PERSISTENT_ROOT` production hiện tại là `/app/database`.
- `BACKUP_FOLDER` hiện tại là `PERSISTENT_ROOT/backup`.
- Local/dev fallback vẫn là `database/spa.db` trong workspace.
- Test hiện dùng SQLite file tạm hoặc SQLite test database riêng.
- Ứng dụng không còn `db.create_all()` khi boot; schema hiện được quản qua custom migration baseline.

## Cấu hình database hiện tại

- `config.py` đang tách logic theo local/dev/test/production.
- Production bắt buộc phải có `DATABASE_URL`.
- `.env.example` hiện vẫn theo cách cấu hình SQLite.
- Tests hiện override `TEST_DATABASE_URL` sang SQLite.
- PostgreSQL driver readiness now starts with `psycopg2-binary` in `requirements.txt`.
- Chưa cutover sang PostgreSQL production, và chưa có test profile PostgreSQL thật.

## Models / schema summary

Các bảng chính hiện có:

- `users`
- `customers`
- `services`
- `appointments`
- `invoices`
- `invoice_details`
- `activity_logs`
- `settings`

Những rủi ro schema đáng chú ý:

- PK hiện chủ yếu là integer.
- FK và quan hệ xóa mềm đang phụ thuộc nhiều vào logic ứng dụng.
- `services.price`, `invoices.subtotal`, `invoices.discount`, `invoices.total_amount`, `invoice_details.price` đang dùng `Float`, nên cần đánh giá lại khi sang PostgreSQL vì tiền tệ không nên phụ thuộc float.
- Một số trường `DateTime` có nguy cơ lệch semantics nếu chưa chuẩn hóa timezone/naive-vs-aware.
- Phone/email duplicate prevention hiện chủ yếu ở tầng app, chưa dựa hoàn toàn vào unique constraint ở DB.
- Một số FK chưa thể hiện rõ `ondelete`/cascade ở mức schema, nên nguy cơ orphan phụ thuộc vào cleanup logic.

## SQLite-specific dependencies

Các điểm đang phụ thuộc SQLite rõ ràng:

- `services/backup_service.py` backup DB bằng copy file SQLite.
- `services/restore_service.py` dùng `sqlite3.connect(...).backup(...)` để restore.
- Validate backup đang dựa trên header `SQLite format 3`.
- Integrity check dùng `PRAGMA integrity_check`.
- Metadata scan dùng `sqlite_master`.
- `routes/setting.py` hiện chỉ chấp nhận backup `.db`, `.sqlite`, `.sqlite3`.
- `core/migration_cli.py` là custom migration CLI, không phải bộ migration diff tự động đầy đủ kiểu Alembic workflow cổ điển.
- `migrations/versions/0001_baseline.py` là baseline khởi tạo schema hiện tại.
- `requirements.txt` hiện đã có PostgreSQL driver `psycopg2-binary`.

## Backup / restore impact

Hiện tại:

- Backup = copy SQLite DB file + metadata JSON.
- Restore = thay thế / khôi phục lại SQLite DB file.
- Backup Center đang hiểu database như một file vật lý.

Khi chuyển sang PostgreSQL:

- Không thể backup database bằng cách copy `spa.db`.
- Không thể restore production PostgreSQL bằng cách replace một file SQLite.
- Cần tách rõ DB backup và file/uploads backup.
- Restore PostgreSQL production không nên là thao tác UI bấm tùy tiện.

### Đề xuất chiến lược

**Option 1: Managed backup từ Railway / provider**

- Ưu điểm: đơn giản, ít rủi ro vận hành.
- Nhược điểm: phụ thuộc provider, ít kiểm soát chi tiết.

**Option 2: `pg_dump` / `pg_restore`**

- Ưu điểm: chủ động, dễ script hóa, phù hợp rehearsal.
- Nhược điểm: cần quy trình shell/ops rõ ràng, phải quản lý secrets an toàn.

**Option 3: Hybrid**

- DB dùng managed backup hoặc `pg_dump`.
- File/uploads vẫn backup theo ứng dụng.
- Phù hợp nhất với SpaManager vì app có cả dữ liệu DB và file hệ thống.

### Kết luận sơ bộ

Backup/restore hiện tại đang gắn chặt với SQLite file, nên đây là blocker lớn trước khi production cutover sang PostgreSQL.

## Test và CI impact

- Bộ test hiện tại chủ yếu chạy trên SQLite.
- `tests/test_basic.py` và `tests/test_timezone.py` đang dùng SQLite temp/test database.
- Các test `db.drop_all()` / `db.create_all()` hiện chạy tốt trên SQLite.
- PostgreSQL sẽ cần một `TEST_DATABASE_URL` riêng.
- Nên giữ suite SQLite hiện tại để test nhanh và ổn định.
- Nên bổ sung profile/test PostgreSQL trước cutover.
- Có thể chạy PostgreSQL local bằng Docker hoặc service CI.

Nhóm test cần xác minh trên PostgreSQL:

- auth / user management
- customers / services
- appointments / invoices / statistics
- duplicate prevention
- import / export / PDF
- backup / restore theo chiến lược mới
- data audit / repair
- activity logs

## Yêu cầu data migration

Những bảng cần migrate:

1. `users`
2. `settings`
3. `customers`
4. `services`
5. `appointments`
6. `invoices`
7. `invoice_details`
8. `activity_logs`

Khuyến nghị:

- Dùng script Python đọc SQLite và ghi PostgreSQL qua SQLAlchemy.
- Không cutover production trực tiếp.
- Cần rehearsal local/staging trước.
- Metadata backup JSON nằm ngoài DB, xử lý riêng nếu cần.

Validation sau migrate:

- Count từng bảng.
- FK integrity.
- Duplicate phone/email.
- Invoice totals.
- Appointment status.
- Soft delete fields.
- `ActivityLog.user_id` / actor / `deleted_by`.
- Settings values.
- Data audit CLI pass.
- Route smoke pass.

Rollback / freeze:

- Tạo SQLite backup mới nhất trước cutover.
- Freeze writes trong cửa sổ chuyển đổi.
- Không xóa SQLite DB cũ ngay.
- Có thể rollback bằng cách trỏ `DATABASE_URL` về SQLite nếu PostgreSQL gặp lỗi.

## Docs / env / deploy changes cần chuẩn bị

Những file sẽ cần cập nhật ở các task sau:

- `.env.example`
- `README.md`
- `docs/RUNBOOK.md`
- `docs/ADMIN_GUIDE.md`
- `docs/QA_CHECKLIST.md`
- `docs/DEMO_DATA.md`
- `docs/POSTGRESQL_MIGRATION_AUDIT.md`
- Railway deploy notes

Environment cần chuẩn bị:

- `DATABASE_URL` PostgreSQL URI.
- `TEST_DATABASE_URL` cho profile PostgreSQL test.
- PostgreSQL driver dependency (`psycopg2-binary`).
- Backup strategy env nếu sau này cần tách cấu hình.

## Risk assessment

### Low risk

- Phần lớn CRUD ORM.
- Route/view logic không phụ thuộc trực tiếp vào file DB.

### Medium risk

- DateTime / timezone semantics.
- Boolean / default values.
- Search / filter / group theo ngày.
- Transaction ordering.

### High risk

- Float cho tiền tệ.
- FK / orphan / duplicate integrity.
- Test suite hiện SQLite-only.
- Custom migration baseline chưa phải full migration framework cho Postgres.

### Blockers

- Backup/restore hiện tại phụ thuộc SQLite file.
- Chưa có PostgreSQL driver/profile.
- Chưa có migration rehearsal/rollback tool.

## Recommended roadmap

### v5.8 — PostgreSQL Migration Readiness

- 5.8.1 PostgreSQL compatibility audit report
- 5.8.2 Database config and PostgreSQL dependency readiness
- 5.8.3 Local PostgreSQL development profile
- 5.8.4 PostgreSQL schema compatibility pass
- 5.8.5 Backup/restore strategy redesign for PostgreSQL
- 5.8.6 SQLite → PostgreSQL migration tool design
- 5.8.7 PostgreSQL test profile and CI plan
- 5.8.8 v5.8.0 readiness checkpoint

### v5.9 — PostgreSQL Production Migration

- 5.9.1 Railway PostgreSQL provisioning
- 5.9.2 Production SQLite backup and freeze plan
- 5.9.3 Data migration dry-run
- 5.9.4 Post-migration data validation
- 5.9.5 Production `DATABASE_URL` cutover
- 5.9.6 Post-cutover QA and rollback check
- 5.9.7 v5.9.0 PostgreSQL production checkpoint

## Final recommendation

- Không cutover production ngay.
- Làm PostgreSQL trước Workspace / Google Registration.
- Task tiếp theo sau audit doc nên là 5.8.2 Database config and PostgreSQL dependency readiness.
- Backup/restore phải được redesign trước production cutover.

## Local PostgreSQL development profile

Để developer có thể rehearsal PostgreSQL ở local mà không đụng production, repo hiện có profile Docker tối giản:

- File: `docker-compose.postgres.yml`
- Image: `postgres:16`
- Database: `spamanager_dev`
- User: `spamanager`
- Password: `spamanager_dev_password`
- Port: `5433:5432`

Khởi động local PostgreSQL:

```bash
docker compose -f docker-compose.postgres.yml up -d
```

Tạo database test local:

```bash
docker exec -it spamanager-postgres createdb -U spamanager spamanager_test
```

Set env trong PowerShell:

```powershell
$env:DATABASE_URL="postgresql://spamanager:spamanager_dev_password@localhost:5433/spamanager_dev"
$env:TEST_DATABASE_URL="postgresql://spamanager:spamanager_dev_password@localhost:5433/spamanager_test"
```

CLI migration hiện có trong repo là `flask --app app db` từ `core/migration_cli.py`:

```powershell
.\venv\Scripts\python.exe -m flask --app app db history
.\venv\Scripts\python.exe -m flask --app app db current
.\venv\Scripts\python.exe -m flask --app app db upgrade
.\venv\Scripts\python.exe -m flask --app app db stamp head
```

Với local PostgreSQL mới, lệnh init schema là:

```powershell
.\venv\Scripts\python.exe -m flask --app app db upgrade
```

Nếu DB đã có schema và chỉ cần đánh dấu revision, dùng:

```powershell
.\venv\Scripts\python.exe -m flask --app app db stamp head
```

## PostgreSQL schema compatibility follow-up

- Báo cáo chi tiết: `docs/POSTGRESQL_SCHEMA_COMPATIBILITY.md`
- Tài liệu này bổ sung cho audit hiện tại bằng một bảng schema/risk rõ ràng hơn.

## Backup/restore strategy follow-up

- Báo cáo chiến lược chi tiết: `docs/POSTGRESQL_BACKUP_RESTORE_STRATEGY.md`
- Chiến lược này là follow-up bắt buộc trước PostgreSQL production cutover.
