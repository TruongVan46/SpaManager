# PostgreSQL Local Dev Smoke Test

## Scope

- Verifies local development can run on Docker PostgreSQL.
- Does not use production database.
- Does not run workspace production migration.
- Does not create executable workspace migration.
- Does not create approval marker.

## Environment

- Docker version: `Docker version 29.6.1, build 8900f1d`
- Docker Compose version: `Docker Compose version v5.3.0`
- Container: `spamanager-postgres`
- Database: `spamanager_dev`
- DATABASE_URL source: DevelopmentConfig default / explicit local env
- DATABASE_URL is production: no
- SQLite legacy enabled: no

## Results

| Check | Status | Notes |
|---|---|---|
| Docker PostgreSQL started | FAIL | Docker Desktop engine was not reachable from the current shell session. `docker compose up -d` could not connect to `dockerDesktopLinuxEngine`. |
| `spamanager_dev` DB created | NOT RUN | Could not reach the Docker engine to create or recreate the local database. |
| DevelopmentConfig dialect | PASS | DevelopmentConfig is configured to prefer PostgreSQL local development. |
| DevelopmentConfig database | PASS | Default local URI points to `postgresql://spamanager:spamanager_dev_password@localhost:5433/spamanager_dev`. |
| `db upgrade` | NOT RUN | Blocked by unavailable Docker PostgreSQL engine. |
| `db current` | NOT RUN | Blocked by unavailable Docker PostgreSQL engine. |
| Core tables exist | NOT RUN | Blocked by unavailable Docker PostgreSQL engine. |
| App import/boot | FAIL | Importing `app` attempted to connect to PostgreSQL on `localhost:5433` and received connection refused. |
| Route smoke | NOT RUN | Blocked because the app could not boot against the unavailable local database. |
| Manual browser smoke | NOT RUN | Not run. |
| `unittest` | PASS | `151` tests passed. |
| `compileall` | PASS | `python -m compileall .` passed. |

## Notes

- This smoke test is for local dev PostgreSQL readiness.
- It is not the workspace production migration.
- It does not approve production migration.
- Fresh dev DB may include workspace tables because current metadata includes workspace models.
- In this session, Docker Desktop was installed but the engine was not reachable, so the PostgreSQL smoke path was blocked.

## Final result

PARTIAL
