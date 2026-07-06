# PostgreSQL Backup and Restore Policy

## Scope

- Áp dụng cho SpaManager ở chế độ PostgreSQL-only product mode.
- Production dùng Railway PostgreSQL.
- Local development dùng Docker PostgreSQL.
- SQLite chỉ còn legacy/test fallback.

## Non-goals

- File này không phải migration executable.
- File này không cấp approval chạy production migration.
- File này không chứa secret hoặc database URL thật.
- File này không thay đổi Railway settings.

## Production policy

- Không backup/restore production bằng flow SQLite cũ.
- Không restore production từ app UI/admin route.
- Không chạy restore production trong pre-deploy command.
- Production pre-deploy chỉ giữ `python -m flask --app app db upgrade`.
- Production restore chỉ được thực hiện như một incident/runbook riêng và cần owner approval rõ ràng.
- Trước production restore phải có:
  - backup/export mới nhất
  - xác nhận target database
  - maintenance window nếu cần
  - rollback/verification plan
  - tuyệt đối không paste `DATABASE_URL` thật vào docs, logs, hoặc chat

## Local Docker PostgreSQL backup example

> Dùng placeholder hoặc thông tin local dev đã có trong repo. Không dùng production URL.

```powershell
$BackupDir = ".\local_backups"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupFile = "spamanager_dev_$Stamp.dump"

docker exec spamanager-postgres pg_dump `
  -U <LOCAL_POSTGRES_USER> `
  -d spamanager_dev `
  -Fc `
  -f "/tmp/$BackupFile"

docker cp "spamanager-postgres:/tmp/$BackupFile" "$BackupDir\$BackupFile"

docker exec spamanager-postgres rm "/tmp/$BackupFile"
```

- Nếu repo đã có user local rõ ràng thì thay `<LOCAL_POSTGRES_USER>` bằng user local dev đúng.
- Nếu chưa chắc, giữ placeholder và ghi chú “check local config”.

## Local restore rehearsal example

> Không restore trực tiếp vào `spamanager_dev` trước. Hãy restore vào DB tạm.

```powershell
$RestoreDb = "spamanager_restore_check"
$BackupFile = ".\local_backups\<BACKUP_FILE>.dump"

docker cp $BackupFile "spamanager-postgres:/tmp/restore_check.dump"

docker exec spamanager-postgres dropdb `
  -U <LOCAL_POSTGRES_USER> `
  --if-exists `
  $RestoreDb

docker exec spamanager-postgres createdb `
  -U <LOCAL_POSTGRES_USER> `
  $RestoreDb

docker exec spamanager-postgres pg_restore `
  -U <LOCAL_POSTGRES_USER> `
  -d $RestoreDb `
  --clean `
  --if-exists `
  "/tmp/restore_check.dump"

docker exec spamanager-postgres rm "/tmp/restore_check.dump"
```

## Verification checklist after restore rehearsal

- `flask db current` đúng revision mong đợi.
- App boot được với DB restore check nếu có cấu hình tạm.
- Route smoke không có `500`.
- Dữ liệu quan trọng có thể kiểm tra lại.
- Không có backup file nào bị Git track.

## Git hygiene

- Không commit `.env`.
- Không commit secret hoặc DB URL thật.
- Không commit backup dump.
- Không commit `.db`, `.sqlite`, `.zip`, `.dump`, `.backup`.
- Không commit import temp.
- Không commit PDF export artifact.
- Không commit `__pycache__` hoặc `*.pyc`.

## Notes

- PostgreSQL product mode phải dùng provider-managed backup/restore policy.
- SQLite backup/restore in-app chỉ còn legacy/test fallback.
- Nếu product mode là PostgreSQL, in-app SQLite restore flow phải bị chặn hoặc ghi rõ là không hỗ trợ.

