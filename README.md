# SpaManager

[![Continuous Integration](https://github.com/truongvan46/SpaManager/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/truongvan46/SpaManager/actions/workflows/ci.yml)

SpaManager is a Flask-based web application for managing spa, nail, and makeup businesses. It uses PostgreSQL in production, Docker PostgreSQL for local development, and persistent application storage for uploaded media and backup artifacts.

## Current release

- Current version: `7.0`
- Version 7.0 status: **CLOSED / DONE**
- Current database revision: `0009_immediate_purge_eligibility`
- [Version 7.0 closure](docs/workspace/VERSION_7_0_CLOSURE.md)
- Previous release: [Version 6.6 closure](docs/workspace/VERSION_6_6_CLOSURE.md)

## Architecture overview

```text
Browser
   |
   v
SpaManager Flask service
   |-- DATABASE_URL --> PostgreSQL (Product DB)
   `-- /app/database --> persistent media and backup artifacts
```

PostgreSQL acts as the production database and is configured via `DATABASE_URL`. Persistent application storage (such as a Railway Volume mounted at `/app/database`) stores uploaded media files (logos, avatars) and backup artifacts, not PostgreSQL database files.

## Core features

### Core business management

- **Dashboard**: High-level KPI metrics and daily operational overview.
- **Customer management**: Customer directory, contact details, and history.
- **Service management**: Service catalog, pricing, and duration setup.
- **Appointment calendar**: Visual scheduling and appointment tracking.
- **Invoice management**: Billing, payment tracking, and invoice status tracking.
- **Statistics & Reports**: Revenue, appointment, and performance diagnostics.
- **Activity log**: Audited record of user actions and system events.

### Workspace & access control

- **Workspace tenant isolation**: Multi-tenant workspace data scoping.
- **Role hierarchy**: OWNER, ADMIN, STAFF, and APPROVAL_OWNER role permissions.
- **Google OAuth approval flow**: Optional Google authentication flow with domain filtering (Google OAuth is disabled by default until configured).
- **Soft delete & restore**: Reversible deletion for customer, user, and workspace records.
- **Approval Portal**: Dedicated review interface for workspace lifecycle actions.

### Operations & safety

- **PostgreSQL-first deployment**: Uses PostgreSQL as the production database.
- **CSRF & session security**: CSRF protection and hardened production cookies.
- **Persistent storage**: Uploaded media and backup artifacts are stored under the configured persistent root.
- **Audited workspace purge**: Multi-step workspace purge workflow with execution kill-switches.
- **Command Palette with `Ctrl+K`**: Quick keyboard navigation throughout the interface.

## Security and production hardening

- Mandatory `APP_ENV` environment variable validation with fail-closed startup behavior.
- CSRF protection for state-changing form and API requests.
- Secure production session cookie flags (`SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`).
- Production health check endpoint at `GET /health`.
- Graceful HTML and JSON error handlers for 404/500 responses.
- Audit tracking (`deleted_by_id`, `created_by_id`, `ActivityLog`) across key models.
- Standardized timezone handling set to `Asia/Ho_Chi_Minh`.

## Quick start

To run SpaManager locally on Windows using PowerShell:

```powershell
# 1. Clone repository & enter project folder
git clone https://github.com/truongvan46/SpaManager.git
cd SpaManager

# 2. Create virtual environment & activate
python -m venv venv
.\venv\Scripts\activate

# 3. Install requirements
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. Configure environment
copy .env.example .env

# 5. Start local PostgreSQL via Docker Compose & create test database
docker compose -f docker-compose.postgres.yml up -d
docker exec -it spamanager-postgres createdb -U spamanager spamanager_test

# 6. Set environment variables & run migrations
$env:APP_ENV="development"
$env:DATABASE_URL="postgresql://spamanager:spamanager_dev_password@localhost:5433/spamanager_dev"
$env:TEST_DATABASE_URL="postgresql://spamanager:spamanager_dev_password@localhost:5433/spamanager_test"
.\venv\Scripts\python.exe -m flask --app app db upgrade

# 7. Start local development server
.\venv\Scripts\python.exe run.py
```

> [!IMPORTANT]
> `APP_ENV` is mandatory. Accepted values are `development`, `testing`, and `production`. Missing, empty, or unsupported values cause startup to fail closed.

If you explicitly need the legacy SQLite fallback for offline development, set `SPA_ENABLE_SQLITE_LEGACY=1` and leave `DATABASE_URL` unset.

## Environment variables

### Required in production

- `APP_ENV`: Mandatory environment selection (`production`).
- `APP_VERSION`: Current application release version (`7.0`).
- `DATABASE_URL`: PostgreSQL connection string URL.
- `SECRET_KEY`: Cryptographic key for session signing.
- `PERSISTENT_ROOT`: Base directory for persistent media and backup artifacts (e.g. `/app/database`).

### Application identity & timezone

- `APP_NAME`: Application name (`SpaManager`).
- `APP_TIMEZONE`: Default timezone (`Asia/Ho_Chi_Minh`).

### Authentication & bootstrap

- `DEFAULT_OWNER_USERNAME`, `DEFAULT_OWNER_PASSWORD`, `DEFAULT_OWNER_EMAIL`: Bootstrap credentials for initial setup.
- `GOOGLE_AUTH_ENABLED`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `GOOGLE_ALLOWED_DOMAIN`: Optional Google OAuth configuration (`GOOGLE_AUTH_ENABLED`).

### Local development & testing

- `TEST_DATABASE_URL`: PostgreSQL connection URL for automated tests.
- `SPA_ENABLE_SQLITE_LEGACY`: Explicit flag to enable legacy SQLite fallback.

### Safety & feature flags

- `PERMANENT_PURGE_UI_ENABLED`: Enables UI controls for the Approval Portal.
- `PERMANENT_PURGE_EXECUTION_ENABLED`: Kill switch for permanent purge execution (defaults to `0` / disabled).

For the full list of supported environment options, refer to [.env.example](.env.example).

## Database migrations

SpaManager uses Alembic (via Flask-Migrate) for schema management.

Migration commands:

```powershell
# Show active stamped schema revision (safe read)
.\venv\Scripts\python.exe -m flask --app app db current

# List available schema migration history (safe read)
.\venv\Scripts\python.exe -m flask --app app db history

# Apply pending migrations through current head with flask db upgrade (schema-changing)
.\venv\Scripts\python.exe -m flask --app app db upgrade
```

> [!WARNING]
> `flask db stamp head` marks the database as current without executing migration SQL. Use it only for recovery or when the database schema has already been verified to match the migration head independently. Back up production data before running schema-changing operations such as upgrade, stamp, or downgrade.

Local PostgreSQL rehearsal guide: [`docs/postgresql/POSTGRESQL_REHEARSAL_ENVIRONMENT_SETUP.md`](docs/postgresql/POSTGRESQL_REHEARSAL_ENVIRONMENT_SETUP.md)

## Railway deployment

To deploy SpaManager on Railway:

1. Set `APP_ENV=production`.
2. Set `APP_VERSION=7.0`.
3. Set `DATABASE_URL` to the Railway PostgreSQL reference variable.
4. Set `SECRET_KEY` to a strong random string.
5. Set `PERSISTENT_ROOT` to `/app/database` and mount a Railway Volume at `/app/database`.
6. Configure Railway Pre-deploy Command: `python -m flask --app app db upgrade`.
7. Configure health check endpoint to `GET /health`.

Example production environment configuration:

```env
APP_ENV=production
APP_VERSION=7.0
DATABASE_URL=<Railway PostgreSQL reference variable>
SECRET_KEY=<strong-random-secret-key>
PERSISTENT_ROOT=/app/database
```

Media uploads (logos, avatars) and backup artifacts persist in `/app/database` across service redeployments. PostgreSQL table data is stored in the PostgreSQL database service, not in `/app/database`.

## Testing

Install development dependencies into your virtual environment:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Run the canonical automated test suite using `pytest`:

```powershell
$env:APP_ENV="testing"
.\venv\Scripts\python.exe -m pytest -q
```

To run additional code quality and static checks (such as `compileall .`):

```powershell
.\venv\Scripts\python.exe -m compileall .
.\venv\Scripts\python.exe -m pip check
```

`requirements.txt` specifies production runtime dependencies, while `requirements-dev.txt` includes test frameworks and tooling.

## Backup and operations

- **PostgreSQL backups**: Database backups are managed via Railway or your PostgreSQL cloud provider.
- **Persistent files**: Uploaded media (logos, avatars) and backup artifacts reside under `PERSISTENT_ROOT`.
- **Runbook**: Detailed operational procedures, backup policies, and production checklists are documented in [docs/RUNBOOK.md](docs/RUNBOOK.md) and [docs/postgresql/POSTGRESQL_BACKUP_RESTORE_POLICY.md](docs/postgresql/POSTGRESQL_BACKUP_RESTORE_POLICY.md).

## Documentation

### Operations & QA

- Docs index: [docs/README.md](docs/README.md)
- Runbook: [docs/RUNBOOK.md](docs/RUNBOOK.md)
- QA checklist: [docs/QA_CHECKLIST.md](docs/QA_CHECKLIST.md)

### User & admin guides

- User guide: [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- Admin guide: [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md)
- Demo script: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)
- Demo data plan: [docs/DEMO_DATA.md](docs/DEMO_DATA.md)

### Release & closure history

- Version 7.0 closure: [docs/workspace/VERSION_7_0_CLOSURE.md](docs/workspace/VERSION_7_0_CLOSURE.md)
- Version 6.6 closure: [docs/workspace/VERSION_6_6_CLOSURE.md](docs/workspace/VERSION_6_6_CLOSURE.md)
- Version 6.5 workspace isolation closure: [docs/workspace/WORKSPACE_ISOLATION_CLOSURE.md](docs/workspace/WORKSPACE_ISOLATION_CLOSURE.md)

## PostgreSQL migration & production docs

SpaManager production has been running on PostgreSQL since v5.9.0. Detailed migration, cutover, backup, and validation notes are grouped here:

- [PostgreSQL docs index](docs/postgresql/README.md)
- [PostgreSQL-only product mode audit](docs/postgresql/POSTGRESQL_ONLY_PRODUCT_MODE_AUDIT.md)
- [PostgreSQL backup/restore policy](docs/postgresql/POSTGRESQL_BACKUP_RESTORE_POLICY.md)

## Project structure

- `routes/` — Flask route handlers and blueprints
- `services/` — Core business logic and domain services
- `models/` — SQLAlchemy database models
- `validators/` — Form and data validation helpers
- `core/` — Application utilities and middleware
- `utils/` — Shared helper functions
- `templates/` — Jinja2 HTML templates
- `static/` — CSS, JavaScript, and static assets
- `tests/` — Automated test suite

## Author

**Văn Công Trường**
GitHub: [truongvan46](https://github.com/truongvan46)
