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
