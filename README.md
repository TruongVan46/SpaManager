# SpaManager

[![Continuous Integration](https://github.com/truongvan46/SpaManager/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/truongvan46/SpaManager/actions/workflows/ci.yml)

SpaManager is a Flask-based web app for managing a spa, nail, and makeup business. It runs with SQLite, Bootstrap, and Railway-friendly persistent storage for media, backups, and the database file.

## Features

- Dashboard
- Customer management
- Service management
- Appointment calendar
- Invoice management
- Statistics and reports
- Activity log
- Settings
- Backup and restore
- Recycle bin
- Logo and avatar uploads
- Command Palette with `Ctrl+K`

## Security and production hardening

- CSRF protection for state-changing form and API requests
- Secure session cookie settings in production
- `GET /health` for health checks
- HTML and JSON 404/500 error handling
- `deleted_by` audit tracking
- Timezone standardization to `Asia/Ho_Chi_Minh`

## Local setup

```bash
git clone https://github.com/<your-username>/SpaManager.git
cd SpaManager

python -m venv venv
# Windows
venv\Scripts\activate

pip install -r requirements.txt
copy .env.example .env
.\venv\Scripts\python.exe -m flask --app app db upgrade
python run.py
```

The first run should apply the baseline schema with `flask db upgrade` before starting the app.

## Database migrations

SpaManager ships a lightweight SQLite-safe `flask db` workflow for the current production baseline.

Useful commands:

```bash
.\venv\Scripts\python.exe -m flask --app app db current
.\venv\Scripts\python.exe -m flask --app app db history
.\venv\Scripts\python.exe -m flask --app app db upgrade
.\venv\Scripts\python.exe -m flask --app app db stamp head
```

If you already activated the virtual environment, the shorter form also works:

```bash
flask db current
flask db history
flask db upgrade
flask db stamp head
```

- `current` shows the active stamped revision.
- `history` lists the available schema revisions.
- `upgrade` applies the baseline schema to a fresh database.
- `stamp head` marks an existing production database as already aligned with the baseline.

Always back up the SQLite file before stamping or upgrading a live environment.

### Local PostgreSQL development profile

For local PostgreSQL rehearsal without affecting production, use the Docker profile in `docker-compose.postgres.yml`.

Quick flow:

```powershell
docker compose -f docker-compose.postgres.yml up -d
docker exec -it spamanager-postgres createdb -U spamanager spamanager_test
$env:DATABASE_URL="postgresql://spamanager:spamanager_dev_password@localhost:5433/spamanager_dev"
$env:TEST_DATABASE_URL="postgresql://spamanager:spamanager_dev_password@localhost:5433/spamanager_test"
.\venv\Scripts\python.exe -m flask --app app db upgrade
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test*.py" -v
```

To return to the default SQLite local setup:

```powershell
Remove-Item Env:DATABASE_URL
Remove-Item Env:TEST_DATABASE_URL
```

## Environment variables

Required or commonly used variables:

- `APP_ENV`
- `APP_NAME`
- `APP_VERSION`
- `APP_TIMEZONE`
- `DATABASE_URL`
- `TEST_DATABASE_URL` for the future PostgreSQL test profile
- `LOGIN_MAX_FAILED_ATTEMPTS`
- `LOGIN_FAILURE_WINDOW_SECONDS`
- `LOGIN_LOCKOUT_SECONDS`
- `DEFAULT_OWNER_USERNAME`
- `DEFAULT_OWNER_PASSWORD`
- `DEFAULT_OWNER_EMAIL`
- `LOG_LEVEL`
- `PERSISTENT_ROOT`
- `SECRET_KEY`

Other supported values:

- `CSRF_ENABLED`
- `CSRF_TIME_LIMIT`
- `SESSION_LIFETIME_DAYS`
- `SEND_FILE_MAX_AGE_DAYS`
- `MAX_UPLOAD_SIZE`
- `LOG_DIR`
- `LOG_ROTATION_SIZE`
- `LOG_BACKUP_COUNT`
- `UPLOAD_ROOT`
- `LOGO_UPLOAD_FOLDER`
- `AVATAR_UPLOAD_FOLDER`
- `EXPORT_FOLDER`
- `BACKUP_FOLDER`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `GOOGLE_DISCOVERY_URL`
- `GOOGLE_SCOPES`

## Railway deployment

- Use `APP_ENV=production`
- Set `DATABASE_URL` to the Railway PostgreSQL reference variable
- Keep `TEST_DATABASE_URL` reserved for the PostgreSQL test profile
- Set `PERSISTENT_ROOT` to the Railway persistent volume root
- Keep uploaded media under the persistent root so redeploys do not remove files
- Point Railway health checks to `GET /health`

Example production values:

```env
DATABASE_URL=<Railway PostgreSQL reference variable>
PERSISTENT_ROOT=/app/database
```

## Backup and restore

- Back up the PostgreSQL database using Railway / provider-managed backups
- Restore with care because it overwrites live data
- Logo and avatar files live under the persistent media folder

## Operations / Runbook

For the production smoke checklist, backup and restore safety, internal CLI commands, and release checklist, see:

[docs/RUNBOOK.md](docs/RUNBOOK.md)

## Documentation

- Docs index: [docs/README.md](docs/README.md)
- QA checklist: [docs/QA_CHECKLIST.md](docs/QA_CHECKLIST.md)
- Demo data plan: [docs/DEMO_DATA.md](docs/DEMO_DATA.md)
- User guide: [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- Admin guide: [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md)
- Demo script: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)

## Testing

```bash
.\\venv\\Scripts\\python.exe -m unittest discover -s tests -p "test*.py" -v
.\\venv\\Scripts\\python.exe -m compileall .
```

## Project structure

- `routes/` - Flask route modules
- `services/` - business logic
- `models/` - database models
- `validators/` - validation helpers
- `core/` - app utilities and middleware
- `utils/` - shared helpers
- `templates/` - Jinja templates
- `static/` - CSS, JavaScript, and assets
- `tests/` - automated tests

## Author

**Văn Công Trường**  
GitHub: [truongvan46](https://github.com/truongvan46)

## Notes

- Google OAuth is not implemented.
- User management is available with OWNER / ADMIN / STAFF permissions.
- PostgreSQL production cutover is now the deployment path.
- SpaManager remains a local-first application with Railway production support.

## PostgreSQL migration & production docs

SpaManager production is now running on PostgreSQL as of v5.9.0. Detailed migration, cutover, backup, and validation notes are grouped here:

- [PostgreSQL docs index](docs/postgresql/README.md)

## Workspace docs

- [Workspace architecture audit](docs/workspace/WORKSPACE_ARCHITECTURE_AUDIT.md)
