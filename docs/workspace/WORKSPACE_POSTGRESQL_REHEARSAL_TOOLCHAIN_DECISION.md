# Workspace PostgreSQL Rehearsal Toolchain Decision

## Scope

Decide which local toolchain can support a safe PostgreSQL rehearsal for the workspace migration path without touching production.

This document only covers rehearsal tooling and environment readiness. It does not run migrations or change deployment behavior.

## Current blocker

The prior blocker has been cleared by a working Docker Desktop local PostgreSQL rehearsal environment.

## Toolchain check result

### Commands run

- `docker --version` → Docker Desktop local toolchain available.
- `docker compose version` → Docker Compose available.
- `psql --version` → PostgreSQL client available.
- `where docker` → resolved to the local Docker installation.
- `where psql` → resolved to the local PostgreSQL client.

### Interpretation

- Docker Desktop is available and usable for rehearsal.
- Native PostgreSQL client tools are available and usable for validation.
- The local machine can support a production-like PostgreSQL rehearsal without touching production.

## Options considered

### Option A — Docker Desktop

Use Docker Compose with `postgres:16` and the existing `docker-compose.postgres.yml` profile.

### Option B — Native PostgreSQL

Install local PostgreSQL server/client tools and use `psql` plus the existing database URL flow.

### Option C — Railway staging PostgreSQL

Rehearse against a Railway staging PostgreSQL database with strict safety controls and no production credentials.

## Decision

**SELECTED: Option A — Docker Desktop local PostgreSQL**

## Why this decision

- Option A is now available and has already proven successful in the local production-like rehearsal.
- Option B is unnecessary for this rehearsal path because Docker Desktop already works.
- Option C remains useful later for staging validation, but it is not required to complete the local rehearsal toolchain setup.

## Required next action

- Keep the Docker Desktop local PostgreSQL toolchain as the standard rehearsal path.
- Use the same Mode A setup for future workspace rehearsal verification.
- Treat staging PostgreSQL as an optional later extension, not the primary blocker anymore.

## Safety rules

- Do not use production `DATABASE_URL`.
- Do not run `db upgrade` against production.
- Do not recreate `migrations/versions/0002_workspace_foundation.py` during normal repo state.
- Do not add approval markers or auto-deploy control files.
- Keep all rehearsal docs descriptive and truthful about whether the migration executable is temporary or deleted.

## Next task

**6.0.12 — PostgreSQL rehearsal toolchain setup verification**
