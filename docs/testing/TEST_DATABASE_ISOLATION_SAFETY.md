# Test Database Isolation Safety

Unit tests must set `APP_ENV=testing` and a unique SQLite `TEST_DATABASE_URL` before importing `app`. The central configuration guard detects unittest/pytest processes, forces TestingConfig, rejects missing test URLs and rejects PostgreSQL unless an explicit opt-in uses a clearly named `_test` database.

Development (`spamanager_dev`), production/remote databases and raw `DATABASE_URL` are forbidden for unit tests. If `psycopg2` appears during a unit test, stop immediately; recovery of local development data is a separate operation.

Use the canonical discovery command only after guard tests pass. New tests must create temp SQLite paths outside the repository and never rely on DevelopmentConfig fallback.
