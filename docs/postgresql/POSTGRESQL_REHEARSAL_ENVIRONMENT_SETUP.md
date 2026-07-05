# PostgreSQL Rehearsal Environment Setup

## Purpose

This guide sets up a safe local PostgreSQL environment for rehearsal only.

It does **not** change production `DATABASE_URL`, production data, or Railway deploy behavior.

## Prerequisites

- Docker Desktop or another local Docker runtime
- The project virtual environment at `venv`
- The repository checked out locally

## Local Docker profile

Use the existing Compose profile:

```powershell
docker compose -f docker-compose.postgres.yml up -d
```

Default values in the Compose file:

- PostgreSQL image: `postgres:16`
- Database: `spamanager_dev`
- User: `spamanager`
- Password: `<password placeholder>`
- Host port: `5433`

## Create the test database

```powershell
docker exec -it spamanager-postgres createdb -U spamanager spamanager_test
```

## Set environment variables

```powershell
$env:DATABASE_URL="postgresql://<user>:<password>@localhost:5433/<db>"
$env:TEST_DATABASE_URL="postgresql://<user>:<password>@localhost:5433/<test_db>"
```

## Initialize schema

Run the migration CLI already present in the project:

```powershell
.\venv\Scripts\python.exe -m flask --app app db upgrade
.\venv\Scripts\python.exe -m flask --app app db current
```

## Run tests

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test*.py" -v
```

## Return to legacy SQLite fallback

```powershell
Remove-Item Env:DATABASE_URL
Remove-Item Env:TEST_DATABASE_URL
```

If you explicitly need the legacy SQLite fallback, set `SPA_ENABLE_SQLITE_LEGACY=1` and leave `DATABASE_URL` unset.

## Safety notes

- Do not point this profile at production credentials.
- Do not commit secrets into `.env.example` or docs.
- Do not use this profile to run production deploy commands.

## Current status

The repository already contains the setup pieces above, and the Docker Desktop local PostgreSQL rehearsal path has now been verified as working.

The local production-like rehearsal used:

- database: `spamanager_workspace_prodlike`
- baseline revision before migration: `0001_baseline`
- revision after local dry-run: `0002_workspace_foundation`

The temporary executable migration was created only for the local dry-run and then deleted from `migrations/versions/`.

See also: `docs/workspace/WORKSPACE_POSTGRESQL_REHEARSAL_TOOLCHAIN_DECISION.md` for the current toolchain decision.
