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
