# SpaManager Production Runbook

This document is for production handover, post-deploy smoke checks, backup/restore safety, and internal CLI usage. It is intentionally concise so it can be followed during an incident or release.

## 1. Production overview

- SpaManager runs as a Flask application on Railway.
- Production uses PostgreSQL on Railway.
- The expected production database is the Railway PostgreSQL service referenced by `DATABASE_URL`.
- Persistent files live under `/app/database`.
- Uploaded media, export files, and backups must stay on persistent storage.
- Do not place real secrets or passwords in this document.

## 2. Required environment variables

Check these values before and after deploy:

- `APP_ENV`
- `APP_NAME`
- `APP_VERSION`
- `DATABASE_URL`
- `TEST_DATABASE_URL` for the PostgreSQL test profile
- `PERSISTENT_ROOT`
- `SECRET_KEY`
- `DEFAULT_OWNER_USERNAME`
- `DEFAULT_OWNER_EMAIL`
- `DEFAULT_OWNER_PASSWORD`
- `LOG_LEVEL`
- Login rate-limit settings if enabled in the current release

Notes:

- Keep production secrets out of source control.
- Do not paste the real database URL, password, or secret key into notes or tickets.
- When preparing PostgreSQL later, use a placeholder `DATABASE_URL` in `.env.example` and a matching `TEST_DATABASE_URL` for the test profile.

## 3. Post-deploy smoke checklist

Use this after every deploy:

- [ ] GitHub Actions is green.
- [ ] Railway deployment completed successfully.
- [ ] Railway logs do not show a traceback or repeated 500 errors.
- [ ] `GET /health` returns `200` with a JSON payload.
- [ ] The UI shows the expected version in the footer/sidebar/settings area.
- [ ] OWNER or ADMIN can log in successfully.
- [ ] STAFF users are blocked from admin-only pages.
- [ ] Customer list opens correctly.
- [ ] Appointment list or calendar opens correctly.
- [ ] Invoice list and detail pages open correctly.
- [ ] Statistics pages load correctly.
- [ ] PDF export renders Vietnamese correctly when tested.
- [ ] Backup Center shows existing backups.
- [ ] A fresh backup can be created if the release needs one.
- [ ] After any import / export / PDF / backup rehearsal, run a quick `git status` check to confirm no runtime artifact is staged.
- [ ] Backup metadata includes the expected app version.
- [ ] `ops diagnostics` runs when shell access is available.
- [ ] `data audit` runs when shell access is available.

### 3.1 Quick 5-minute smoke

Use this when you only have a very small window after deploy:

- [ ] `GET /health` returns `200`.
- [ ] OWNER or ADMIN can log in.
- [ ] The footer/sidebar shows the expected `APP_VERSION`.
- [ ] Backup Center opens and lists backups.
- [ ] PDF export works on a fresh file, not a cached old one.
- [ ] After any rehearsal, `git status --short` is still clean.

## 4. Health check

- Primary check: `GET /health`
- Expected result: `200`
- Expected payload: JSON basics proving the app and database are reachable
- Do not use `POST /health` as a health signal; it is not the intended method.

## 5. Internal CLI commands

### Data audit

Command:

```bash
flask --app app data audit
```

Purpose:

- Read-only diagnostics.
- Detect orphaned records, missing relations, duplicate issues, and soft-delete mismatches.
- Does not change the database.

### Data repair

Commands:

```bash
flask --app app data repair
flask --app app data repair --dry-run
flask --app app data repair --apply --yes
```

Guidance:

- Default mode should be treated as dry-run unless explicitly documented otherwise.
- Review the dry-run output before applying changes.
- Do not run `--apply --yes` on production unless you have reviewed the impact and taken a backup.
- Do not use repair to auto-fix risky duplicate or orphan scenarios without verification.

### Performance profile

Command:

```bash
flask --app app perf profile
```

Purpose:

- Performance profiling only; does not change the database.

## 6. Local PostgreSQL development profile

Use this for local development and rehearsal. PostgreSQL is the product path; SQLite is legacy fallback only.

### 6.1 Start PostgreSQL locally

```bash
docker compose -f docker-compose.postgres.yml up -d
```

The local container uses:

- database: `spamanager_dev`
- user: `spamanager`
- password: `spamanager_dev_password`
- port: `5433`

### 6.2 Create the local test database

```bash
docker exec -it spamanager-postgres createdb -U spamanager spamanager_test
```

### 6.3 Set environment variables in PowerShell

```powershell
$env:DATABASE_URL="postgresql://<local_user>:<local_password>@localhost:5433/spamanager_dev"
$env:TEST_DATABASE_URL="postgresql://<local_user>:<local_password>@localhost:5433/spamanager_test"
```

### 6.4 Initialize schema with the repo migration CLI

The current migration CLI in `core/migration_cli.py` is exposed through `flask --app app db`.

Useful commands:

```powershell
.\venv\Scripts\python.exe -m flask --app app db history
.\venv\Scripts\python.exe -m flask --app app db current
.\venv\Scripts\python.exe -m flask --app app db upgrade
.\venv\Scripts\python.exe -m flask --app app db stamp head
```

For a fresh local PostgreSQL database, run:

```powershell
.\venv\Scripts\python.exe -m flask --app app db upgrade
```

If you need to mark an already initialized database, use:

```powershell
.\venv\Scripts\python.exe -m flask --app app db stamp head
```

### 6.5 Run tests against the PostgreSQL profile

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test*.py" -v
```

### 6.6 Return to legacy SQLite fallback

```powershell
Remove-Item Env:DATABASE_URL
Remove-Item Env:TEST_DATABASE_URL
```

Or explicitly enable legacy SQLite fallback with `SPA_ENABLE_SQLITE_LEGACY=1` if you need a quick non-product test path.

- Lightweight timing and query-count profiling.
- Not a stress test.
- Do not run in a production loop.

### Operational diagnostics

Commands:

```bash
flask --app app ops diagnostics
flask --app app ops diagnostics --skip-performance
flask --app app ops report
```

Purpose:

- Read-only summary of app, database, backup, audit, repair, performance, and security status.
- Does not create backups.
- Does not apply repairs.
- Does not write to the database.

## 6. Backup procedure

- Prefer the Backup Center in Settings for normal backups.
- Backups should live under the persistent backup folder.
- Confirm the backup file appears in the list after creation.
- Confirm metadata can be read successfully.
- Confirm the backup size and version look reasonable.

Do not invent a destructive backup command if the codebase does not provide one.

## 7. Restore procedure

Restores are high-risk operations:

- Create a fresh backup before restoring anything.
- Verify the backup metadata first.
- Do not restore from an old or local file by mistake.
- After restore, verify:
  - `/health`
  - login
  - key record counts
  - `data audit`
  - `ops diagnostics`

If the application exposes a read-only restore validation step, use it before the actual restore.

## 8. Rollback / recovery guidance

If production is broken after a deploy:

1. Check Railway logs.
2. Check GitHub Actions.
3. Check `/health`.
4. Roll back code to the last stable tag or commit if the issue is code-related.
5. Do not restore the database if the issue is only in application code.
6. Restore the database only when data corruption is confirmed.
7. Back up the current state before any restore.

Current stable checkpoint: `v5.9.0`.

## 9. Security checks

- `SECRET_KEY` must not use a default placeholder in production.
- `APP_ENV` should be `production` on Railway.
- Session cookies should be secure in production.
- OWNER / ADMIN / STAFF role behavior should match expectations.
- Failed login attempts should be rate limited if the feature is enabled.
- Activity log entries must not expose plaintext passwords.
- No real `.env` file should be committed.

## 10. Data integrity checks

- Run `data audit` after restore or before major releases.
- If the audit fails, investigate the issue before applying any repair.
- Use `data repair --dry-run` to review safe repair candidates first.
- Do not merge duplicates automatically without review.

## 11. Common troubleshooting

### `/health` returns 500

- Check Railway logs.
- Verify `DATABASE_URL` and `SECRET_KEY`.
- Confirm the Railway volume is mounted.

### Images or uploads disappear

- Check `PERSISTENT_ROOT`.
- Check the upload/media folders under `/app/database`.
- Check the media routes if available.

### Backup list is empty

- Check the persistent backup folder.
- Check backup metadata.
- Confirm the UI is not filtering out legacy backups.

### PDF Vietnamese text is broken

- Confirm the bundled NotoSans fonts are present in the source tree.
- Export a new file instead of reusing an old cached PDF.

### Login is rate limited

- Wait for the configured window to expire.
- Check the rate-limit environment settings.

## 12. Release checklist

- [ ] Full tests pass.
- [ ] `compileall` passes.
- [ ] `CHANGELOG.md` is updated.
- [ ] `APP_VERSION` is updated where required.
- [ ] `.env.example` is updated if new env vars were added.
- [ ] Backup metadata version is updated if needed.
- [ ] README/docs are updated if needed.
- [ ] `git status` is clean except intended files.
- [ ] No database backup files are committed.
- [ ] No real `.env` secrets are committed.
- [ ] Release tag is created.
- [ ] Railway environment variables are updated.
- [ ] Post-deploy smoke checklist passes.

## 13. Do not run on production

- Do not run `data repair --apply --yes` without a dry-run and backup.
- Do not restore a backup without backing up the current state first.
- Do not delete the SQLite file manually.
- Do not commit `database/backup/`.
- Do not commit temporary import files under `static/uploads/import/`.
- Do not leave rehearsal PDFs, backup copies, or import error reports staged after smoke tests.
- Do not expose `SECRET_KEY`, `DATABASE_URL`, or passwords.
- Do not run stress or performance loops on production.

## PostgreSQL backup/restore strategy note

- Tham chiếu: `postgresql/POSTGRESQL_BACKUP_RESTORE_STRATEGY.md`
- Tài liệu này mô tả hướng redesign backup/restore khi PostgreSQL được bật.

## PostgreSQL clean cutover note

- Tham chiếu: `postgresql/POSTGRESQL_CLEAN_CUTOVER_PLAN.md`
- Dùng khi cần chuyển từ SQLite test data sang PostgreSQL fresh database.

## PostgreSQL test profile and CI plan note

- Tham chiếu: `postgresql/POSTGRESQL_TEST_CI_PLAN.md`
- Tài liệu này nêu rõ SQLite test suite vẫn là default và PostgreSQL CI chưa cần bắt buộc ngay.

## v5.9.0 PostgreSQL production checkpoint note

- Tham chiếu: `postgresql/V5_9_0_POSTGRESQL_PRODUCTION_CHECKPOINT.md`
- Đây là checkpoint chốt production PostgreSQL sau khi cutover thành công và QA pass.

## v5.9.1 Railway PostgreSQL provisioning note

- Tham chiếu: `postgresql/V5_9_1_RAILWAY_POSTGRESQL_PROVISIONING.md`
- Dùng khi owner xác nhận tạo PostgreSQL service trên Railway nhưng chưa cutover app `DATABASE_URL`.

## v5.9.2 Production SQLite backup and freeze plan note

- Tham chiếu: `postgresql/V5_9_2_SQLITE_BACKUP_FREEZE_PLAN.md`
- Dùng trước cutover để backup SQLite, freeze writes, và giữ rollback window an toàn.

## v5.9.3 Fresh PostgreSQL schema initialization plan note

- Tham chiếu: `postgresql/V5_9_3_FRESH_POSTGRESQL_SCHEMA_INIT_PLAN.md`
- Dùng sau freeze/backup để init schema PostgreSQL sạch, bootstrap owner, rồi smoke trước cutover.

## v5.9.4 PostgreSQL cutover rehearsal and validation plan note

- Tham chiếu: `postgresql/V5_9_4_POSTGRESQL_CUTOVER_REHEARSAL_VALIDATION_PLAN.md`
- Dùng để rehearsal/validate mọi bước trước khi owner cho phép đổi production `DATABASE_URL`.

## v5.9.5 Production DATABASE_URL cutover note

- Tham chiếu: `postgresql/V5_9_5_PRODUCTION_DATABASE_URL_CUTOVER.md`
- Dùng khi owner Railway thực hiện cutover production thật và xác nhận xong.

## v5.9.6 Post-cutover QA and PostgreSQL Backup Center guard note

- Tham chiếu: `postgresql/V5_9_6_POST_CUTOVER_QA_AND_POSTGRESQL_BACKUP_CENTER_GUARD.md`
- Dùng sau cutover PostgreSQL để nhắc rằng Backup Center SQLite chỉ còn ở chế độ tham khảo và không được dùng cho DB restore PostgreSQL.
