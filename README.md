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
python run.py
```

The first run seeds the default owner account from `.env`.

## Environment variables

Required or commonly used variables:

- `APP_ENV`
- `APP_NAME`
- `APP_VERSION`
- `APP_TIMEZONE`
- `DATABASE_URL`
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
- Set `DATABASE_URL` to the Railway SQLite volume path
- Set `PERSISTENT_ROOT` to the Railway persistent volume root
- Keep uploaded media under the persistent root so redeploys do not remove files
- Point Railway health checks to `GET /health`

Example production values:

```env
DATABASE_URL=sqlite:////app/database/spa.db
PERSISTENT_ROOT=/app/database
```

## Backup and restore

- Back up the SQLite database file regularly
- Restore with care because it overwrites live data
- Logo and avatar files live under the persistent media folder

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

## Notes

- Google OAuth is not implemented.
- Advanced user management is not included.
- PostgreSQL migration is not the current deployment path.
- SpaManager remains a local-first application with Railway production support.
