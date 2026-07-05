# Tài liệu SpaManager

## Tài liệu gốc

- `README.md`
- `CHANGELOG.md`

## Tài liệu bàn giao hiện hành

- `RUNBOOK.md`
- `QA_CHECKLIST.md`
- `DEMO_DATA.md`
- `USER_GUIDE.md`
- `ADMIN_GUIDE.md`
- `DEMO_SCRIPT.md`

## Tài liệu kỹ thuật

- `CODE_GUIDELINES.md`
- `CSS_ARCHITECTURE.md`
- `JAVASCRIPT_ARCHITECTURE.md`
- `ERROR_HANDLING.md`
- `LOGGING.md`
- `VALIDATION.md`
- `TECH_DEBT.md`
- `POSTGRESQL_MIGRATION_AUDIT.md`

## Ghi chú PostgreSQL

- SpaManager hiện vẫn chạy production SQLite trên Railway Volume.
- PostgreSQL driver đã được chuẩn bị cho giai đoạn readiness.
- `DATABASE_URL` production chưa cutover sang PostgreSQL.
- `TEST_DATABASE_URL` sẽ được dùng cho profile PostgreSQL test ở các task tiếp theo.

## Tài liệu lưu trữ / lịch sử

- `archive/AUDIT_REPORT_v3.7.md`
- `archive/AUTH_AUDIT_v3.9.md`

## Ghi chú

- Nhóm tài liệu bàn giao và vận hành dùng tiếng Việt để đồng bộ với giao diện ứng dụng.
- Các tài liệu kỹ thuật cũ được giữ lại để tham khảo lịch sử.
- Lịch sử release chính thức nằm trong `CHANGELOG.md`.
- Không cần tạo audit report riêng cho từng version mới.
## Ghi chú Local PostgreSQL

- Local PostgreSQL development profile hiện có thể chạy bằng `docker-compose.postgres.yml` ở thư mục gốc.
- Hướng dẫn khởi động, tạo test DB, đặt env và init schema nằm trong `docs/RUNBOOK.md`.

## PostgreSQL schema compatibility

- Xem báo cáo: `POSTGRESQL_SCHEMA_COMPATIBILITY.md`
- Báo cáo này tóm tắt mức độ tương thích schema/model hiện tại với PostgreSQL ở mức readiness.

## PostgreSQL backup/restore strategy

- Báo cáo chiến lược: `POSTGRESQL_BACKUP_RESTORE_STRATEGY.md`
- Đây là tài liệu roadmap cho PostgreSQL backup/restore, không đổi behavior hiện tại.

## PostgreSQL clean cutover plan

- Kế hoạch chuyển sang PostgreSQL mới sạch: `docs/POSTGRESQL_CLEAN_CUTOVER_PLAN.md`
- Current project decision: fresh PostgreSQL clean cutover, không migrate dữ liệu test SQLite cũ.

## PostgreSQL test profile and CI plan

- Kế hoạch test local/CI cho PostgreSQL: `POSTGRESQL_TEST_CI_PLAN.md`
- SQLite test suite vẫn là default; PostgreSQL CI nên bắt đầu ở mức optional/manual.

## v5.8.0 readiness checkpoint

- Chốt trạng thái readiness cho PostgreSQL migration: `V5_8_0_READINESS_CHECKPOINT.md`
- Tài liệu này tóm tắt phạm vi v5.8 và nhấn mạnh rằng production vẫn chưa cutover.

## v5.9.1 Railway PostgreSQL provisioning

- Ghi nhận provision Railway PostgreSQL service: `V5_9_1_RAILWAY_POSTGRESQL_PROVISIONING.md`
- Tài liệu này chỉ mô tả provisioning/readiness, chưa cutover app `DATABASE_URL`.

## v5.9.2 Production SQLite backup and freeze plan

- Kế hoạch backup và freeze writes trước PostgreSQL cutover: `V5_9_2_SQLITE_BACKUP_FREEZE_PLAN.md`
- Tài liệu này chỉ mô tả rollback safety cho SQLite production hiện tại.

## v5.9.3 Fresh PostgreSQL schema initialization plan

- Kế hoạch init schema sạch cho PostgreSQL: `V5_9_3_FRESH_POSTGRESQL_SCHEMA_INIT_PLAN.md`
- Tài liệu này mô tả schema init, owner bootstrap, smoke check, và rollback.
