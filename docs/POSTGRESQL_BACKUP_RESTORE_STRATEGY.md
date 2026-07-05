# PostgreSQL Backup/Restore Strategy

## Mục đích

Tài liệu này mô tả hướng redesign backup/restore khi SpaManager chuyển sang PostgreSQL. Đây là tài liệu chiến lược và rehearsal plan, chưa thay đổi behavior hiện tại của production SQLite.

## Hiện trạng cần giữ nguyên cho production SQLite

- Production hiện vẫn dùng SQLite trên Railway Volume.
- Backup Center hiện tại vẫn là chiến lược SQLite:
  - backup DB bằng copy file `.db` / `.sqlite`
  - metadata lưu qua `metadata.json`
  - restore SQLite bằng flow hiện có
- Chiến lược SQLite này phải giữ nguyên cho tới khi PostgreSQL cutover thật sự được phép.

## Vì sao SQLite restore không dùng cho PostgreSQL

- PostgreSQL không phải một file `.db` đơn lẻ để copy/replace.
- Restore PostgreSQL cần cơ chế database-native như `pg_dump` / `pg_restore` hoặc backup do provider quản lý.
- File uploads vẫn cần backup riêng vì không nằm trong DB.
- Vì vậy, flow restore SQLite hiện tại không thể áp dụng trực tiếp cho PostgreSQL production.

## Strategy đề xuất

### 1) Hybrid backup strategy

Khuyến nghị kết hợp:

- **DB backup**: provider-managed backup hoặc `pg_dump`
- **File backup**: backup riêng cho uploads / media / logo / avatar / import artifacts cần thiết
- **Metadata**: app lưu thông tin backup để hiển thị trong Backup Center và audit

### 2) Engine-aware backup service

Thiết kế tương lai nên:

- Detect DB engine từ SQLAlchemy URL
- Tách strategy SQLite và PostgreSQL
- Giữ SQLite behavior như cũ trước cutover
- Khi ở PostgreSQL mode:
  - không cho dùng SQLite restore flow
  - không cố copy `spa.db`
  - hiển thị warning / runbook instruction rõ ràng

### 3) PostgreSQL mode guard

Khi `DATABASE_URL` là PostgreSQL:

- Ẩn hoặc vô hiệu hóa unsafe DB restore UI
- Hiển thị mô tả rõ: DB restore phải làm theo runbook PostgreSQL
- Giữ upload/file backup riêng nếu có

### 4) Metadata format proposal

Nên bổ sung metadata mới cho backup record, ví dụ:

```json
{
  "id": "uuid",
  "backup_scope": "database|files|hybrid",
  "db_engine": "sqlite|postgresql",
  "storage_mode": "local_copy|provider_backup|pg_dump",
  "filename": "example.sql.gz",
  "created_at": "2026-07-05T10:00:00+07:00",
  "app_version": "SpaManager v5.8.x",
  "database_version": "v5.8.x",
  "notes": "Backup tạo lúc ...",
  "status": "Valid"
}
```

Yêu cầu quan trọng:

- Không đưa secret thật / DB URL thật vào metadata.
- Metadata phải đủ để người vận hành biết backup này là của engine nào và scope nào.

## Backup Center behavior sau PostgreSQL

Khi PostgreSQL mode được bật:

- Backup Center không được ngầm dùng flow SQLite restore.
- Nếu backup DB không khả dụng, phải nói rõ lý do và trỏ sang runbook.
- Nếu file/uploads backup còn phù hợp, vẫn có thể hiển thị phần file backup riêng.
- UI nên ưu tiên giải thích hơn là “ẩn lỗi”.

## Restore safety policy

Quy tắc an toàn đề xuất:

- Chỉ cho phép DB restore theo engine tương ứng.
- Không cho dùng file SQLite `.db` để restore PostgreSQL production.
- Phải có ít nhất một restore rehearsal pass trên local/staging trước cutover.
- Restore production chỉ làm khi:
  - có backup trước đó
  - biết rõ engine
  - đã kiểm tra data / permission / smoke sau restore

## Implementation phases

1. Detect DB engine from SQLAlchemy URL.
2. Split backup service into SQLite strategy and PostgreSQL strategy.
3. Keep SQLite backup behavior unchanged before cutover.
4. Add PostgreSQL mode guard:
   - disable unsafe DB restore UI
   - show runbook instructions
5. Add file/uploads backup strategy if needed.
6. Add PostgreSQL backup metadata format.
7. Add tests for engine-specific backup behavior.
8. Update docs/runbook/admin guide.
9. Rehearse restore in local/staging.
10. Only then cutover production.

## Tests needed

- SQLite backup still works before cutover.
- PostgreSQL mode does not try to copy `spa.db`.
- PostgreSQL mode does not accept `.db` restore as DB restore.
- Backup Center displays correct engine.
- Metadata includes `db_engine` and `backup_scope`.
- File backup does not include secrets.
- Restore warning text is clear.
- Runbook links are visible.

## Risk assessment

### Low

- Docs-only strategy.

### Medium

- Backup Center wording / UX after implementation.
- File/uploads backup split.

### High

- PostgreSQL DB restore.
- `pg_dump` / `pg_restore` integration.
- Provider dependency.
- Production rollback.

### Blocker before PostgreSQL production cutover

- Backup/restore strategy must be implemented or replaced operationally.
- Runbook must clearly define DB backup/restore.
- At least one restore rehearsal must pass on local/staging.

## Final recommendation

- Không cutover PostgreSQL production cho tới khi backup/restore strategy được chốt và rehearsal.
- Giữ SQLite backup hiện tại cho production SQLite.
- Khi PostgreSQL mode được bật, không cho dùng SQLite restore flow.
- Khuyến nghị hybrid strategy: provider DB backup + app file backup/metadata.
