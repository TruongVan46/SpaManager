# PostgreSQL Test Profile and CI Plan

## Mục đích

Tài liệu này mô tả cách test PostgreSQL local và CI để xác nhận SpaManager chạy ổn trên PostgreSQL trước v5.9 clean cutover.

## Test profile hiện tại

- SQLite test suite vẫn là mặc định.
- `TEST_DATABASE_URL` đã có từ 5.8.2.
- `docker-compose.postgres.yml` đã có từ 5.8.3.
- PostgreSQL local smoke chưa chạy được trước đó vì máy không có Docker.
- PostgreSQL production chưa cutover.

## PostgreSQL local test profile

Flow dự kiến:

1. Start PostgreSQL local:

```bash
docker compose -f docker-compose.postgres.yml up -d
```

2. Create test database:

```bash
docker exec -it spamanager-postgres createdb -U spamanager spamanager_test
```

3. Set `TEST_DATABASE_URL`:

```powershell
$env:TEST_DATABASE_URL="postgresql://spamanager:spamanager_dev_password@localhost:5433/spamanager_test"
```

4. Optional set `DATABASE_URL` for app smoke:

```powershell
$env:DATABASE_URL="postgresql://spamanager:spamanager_dev_password@localhost:5433/spamanager_dev"
```

5. Init schema:

```powershell
.\venv\Scripts\python.exe -m flask --app app db upgrade
```

6. Check current revision:

```powershell
.\venv\Scripts\python.exe -m flask --app app db current
```

7. Run tests:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test*.py" -v
```

8. Return to SQLite:

```powershell
Remove-Item Env:DATABASE_URL
Remove-Item Env:TEST_DATABASE_URL
```

## CI plan

Đề xuất GitHub Actions tương lai:

- Giữ SQLite test job hiện tại.
- Thêm PostgreSQL test job tùy chọn.
- PostgreSQL job dùng service container `postgres:16`.
- Set `TEST_DATABASE_URL` trỏ tới PostgreSQL service trong CI.
- Chạy `db upgrade`.
- Chạy test suite.
- Ban đầu để job PostgreSQL là optional/manual nếu còn blocker.
- Chỉ làm required sau khi blocker được xử lý.

## What PostgreSQL CI must catch

- Auth/login/owner bootstrap
- User management
- Customer CRUD
- Service CRUD
- Appointment CRUD
- Invoice creation/statistics
- Settings
- Activity logs
- Import/export/PDF routes
- Backup Center guard behavior sau này
- Data audit / orphan checks
- Date/time filters
- Unique/FK constraints
- Route smoke

## Known likely failures/blockers

- SQLite-specific backup/restore flow
- Date query differences
- `func.date`, `strftime`, raw sqlite usage nếu còn
- FK/orphan stricter behavior
- Boolean/default strictness
- Float precision edge cases
- tests đang assume SQLite in-memory behavior

## Phased adoption

### Phase 1

- SQLite CI vẫn required.
- PostgreSQL local smoke được tài liệu hóa.

### Phase 2

- Add PostgreSQL CI job as optional/manual or non-blocking.

### Phase 3

- Fix PostgreSQL-specific failures.

### Phase 4

- Make PostgreSQL CI required before v5.9 production cutover.

## Environment variables

Checklist:

- `TEST_DATABASE_URL`
- `DATABASE_URL` nếu chạy app smoke
- `SECRET_KEY`
- `DEFAULT_OWNER_PASSWORD`
- `DEFAULT_OWNER_USERNAME`
- `DEFAULT_OWNER_EMAIL`
- `APP_VERSION`
- `PERSISTENT_ROOT`

Chỉ dùng placeholder trong docs, không ghi secret thật.

## CI YAML example

Ví dụ placeholder cho job PostgreSQL trong GitHub Actions:

```yaml
jobs:
  test-postgres:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: spamanager_test
          POSTGRES_USER: spamanager
          POSTGRES_PASSWORD: spamanager_test_password
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      APP_ENV: testing
      TEST_DATABASE_URL: postgresql://spamanager:spamanager_test_password@localhost:5432/spamanager_test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: python -m pip install --upgrade pip
      - run: pip install -r requirements.txt
      - run: python -m flask --app app db upgrade
      - run: python -m unittest discover -s tests -p "test*.py" -v
```

Lưu ý: đây chỉ là ví dụ placeholder, chưa phải workflow thật.

## Recommendation

- SQLite test suite vẫn phải giữ là baseline mặc định.
- PostgreSQL local smoke nên có trước khi mở rộng CI.
- PostgreSQL CI chưa nên bắt buộc ngay nếu còn blocker.
- Trước v5.9, PostgreSQL CI nên là optional/manual, sau đó mới tăng mức bắt buộc.
