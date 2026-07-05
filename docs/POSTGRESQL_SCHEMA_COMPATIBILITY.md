# PostgreSQL Schema Compatibility

## Mục đích

Ghi nhận mức độ tương thích schema/model hiện tại của SpaManager với PostgreSQL ở mức readiness, trước khi bàn tới migration/cutover.

## Kết quả tổng quan

- SQLite suite hiện tại: pass.
- `flask --app app db upgrade` theo custom baseline: logic đơn giản, có thể dựng schema từ `db.create_all()`.
- PostgreSQL local smoke: chưa chạy được trên máy này vì không có Docker.
- Không có thay đổi schema/model/migration lớn trong task này.

## Models / schema summary

| Table | Key fields | PostgreSQL risk | Notes |
|---|---|---|---|
| `users` | `id`, `username`, `password_hash`, `role`, `is_active`, `email`, `oauth_id`, `created_at`, `updated_at` | Low/Medium | `username`, `email`, `oauth_id` unique; `Boolean` và `DateTime` cần consistent timezone semantics. |
| `customers` | `id`, `name`, `phone`, `email`, `address`, `created_at`, `deleted_at`, `deleted_by` | Low/Medium | Không có unique DB cho phone/email; duplicate prevention hiện ở app-layer. |
| `services` | `id`, `name`, `price`, `duration`, `description`, `category`, `deleted_at`, `deleted_by` | Medium | `price` dùng `Float`, có rủi ro precision cho tiền tệ. |
| `appointments` | `id`, `customer_id`, `service_id`, `appointment_time`, `status`, `notes`, `created_at`, `deleted_at`, `deleted_by` | Low/Medium | Có FK rõ ràng; `DateTime` và status query cần kiểm tra timezone/case semantics. |
| `invoices` | `id`, `customer_id`, `invoice_date`, `subtotal`, `discount`, `total_amount`, `payment_method`, `notes`, `created_at`, `deleted_at`, `deleted_by` | Medium | Các field tiền tệ đang dùng `Float`. |
| `invoice_details` | `id`, `invoice_id`, `service_id`, `price`, `quantity` | Medium | `price` dùng `Float`; FK rõ ràng. |
| `activity_logs` | `id`, `created_at`, `module`, `action`, `description`, `reference_id`, `user_id`, `severity` | Low/Medium | Có indexes trên `created_at`, `module`, `action`, `severity`; `user_id` nullable. |
| `settings` | `id`, `key`, `value` | Low | `key` unique; schema nhỏ và ổn. |

## Risk details

### Float / money fields

- Các field tiền tệ đang dùng `Float`: `services.price`, `invoices.subtotal`, `invoices.discount`, `invoices.total_amount`, `invoice_details.price`.
- PostgreSQL vẫn chạy được, nhưng precision cho tiền tệ là rủi ro dài hạn.
- Đây chưa phải blocker cho readiness, nhưng là follow-up quan trọng trước/đúng lúc migration/cutover.

### DateTime / timezone

- `users.created_at`, `users.updated_at`, `users.last_login`
- `customers.created_at`
- `appointments.appointment_time`, `appointments.created_at`
- `invoices.invoice_date`, `invoices.created_at`
- `activity_logs.created_at`
- `deleted_at` fields trên customer/service/appointment/invoice

App đã có timezone standardization, nhưng PostgreSQL vẫn cần kiểm tra kiểu timestamp và cách lưu/đọc datetime nhất quán.

### Boolean / defaults

- `users.is_active`
- `users.email_verified`

PostgreSQL strict hơn SQLite, nhưng schema hiện tại không có default phức tạp nào gây blocker rõ ràng.

### Foreign keys / orphan risk

- `appointments.customer_id -> customers.id`
- `appointments.service_id -> services.id`
- `invoices.customer_id -> customers.id`
- `invoice_details.invoice_id -> invoices.id`
- `invoice_details.service_id -> services.id`
- `activity_logs.user_id -> users.id`

Rủi ro chính là dữ liệu orphan có thể bị PostgreSQL chặn chặt hơn SQLite. Cần audit dữ liệu trước migration thật.

### Unique constraints

- `users.username`
- `users.email`
- `users.oauth_id`
- `settings.key`

Nếu production/local có duplicate thật, migrate/cutover sẽ fail hoặc cần dọn dữ liệu trước.

### Soft delete fields

- `deleted_at`
- `deleted_by`

Thiết kế soft delete không phải blocker riêng cho PostgreSQL, nhưng cần validate logic restore/permanent delete trên FK chặt hơn.

### Search / filter / statistics queries

- Có `ilike()` trong service layer cho search.
- Có `func.date()` trên `Appointment.appointment_time` cho report/statistics.
- Có query theo range ngày và sort/pagination.

Các query này nhìn chung tương thích PostgreSQL, nhưng vẫn nên test thực tế vì behavior index/collation có thể khác SQLite.

### Migration baseline

- `migrations/versions/0001_baseline.py` chỉ gọi `db.create_all()`.
- `core/migration_cli.py` dùng `alembic_version` để stamp/revision tracking.
- Đây là custom lightweight baseline, không phải full Alembic migration workflow.

## Migration baseline notes

- `flask --app app db upgrade` hiện có thể tạo schema từ baseline bằng `db.create_all()`.
- `alembic_version` được tạo và quản lý bởi custom CLI.
- Không có SQLite-only SQL rõ ràng trong baseline migration file.
- Với lộ trình PostgreSQL thật, khả năng cao sẽ cần task sau để nâng cấp strategy migration đầy đủ hơn.

## PostgreSQL local smoke result

- Docker không có trên máy hiện tại nên không thể start PostgreSQL container để smoke.
- Do đó chưa có `db upgrade` / `db current` / PostgreSQL test run thực tế trong phiên này.
- Local profile đã được chuẩn bị ở `docker-compose.postgres.yml` và docs.

## Required follow-up tasks

- Quyết định có giữ `Float` cho tiền tệ hay chuyển dần sang `Numeric/Decimal`.
- Audit dữ liệu orphan/duplicate trước migration thật.
- Thiết kế chiến lược migration đầy đủ hơn nếu baseline custom không còn đủ.
- Đánh giá backup/restore cho PostgreSQL.
- Có PostgreSQL CI/test profile thật.

## Recommendation

- Chưa cutover production sang PostgreSQL.
- Schema/model hiện tại ở mức readiness là khá ổn cho giai đoạn chuẩn bị, nhưng còn blocker dài hạn ở tiền tệ (`Float`) và dữ liệu orphan/duplicate.
- Task tiếp theo nên là hoàn thiện kế hoạch test/migration PostgreSQL hoặc bắt đầu data audit nếu chuẩn bị cutover.

## Backup/restore strategy follow-up

- Chi tiết redesign backup/restore: `docs/POSTGRESQL_BACKUP_RESTORE_STRATEGY.md`
