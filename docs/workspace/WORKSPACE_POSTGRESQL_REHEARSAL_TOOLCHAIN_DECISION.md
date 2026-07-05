# Workspace PostgreSQL Rehearsal Toolchain Decision

## Scope

Decide which local toolchain can support a safe PostgreSQL rehearsal for the workspace migration path without touching production.

This document only covers rehearsal tooling and environment readiness. It does not run migrations or change deployment behavior.

## Current blocker

The rehearsal is blocked because this machine does not currently have a usable PostgreSQL rehearsal toolchain available.

## Toolchain check result

### Commands run

- `docker --version` → Docker is not recognized on this machine.
- `docker compose version` → Docker is not recognized on this machine.
- `psql --version` → `psql` is not recognized on this machine.
- `where docker` → no result.
- `where psql` → no result.

### Interpretation

- Docker Desktop is not installed or not available in PATH.
- Native PostgreSQL client tools are not installed or not available in PATH.
- A Railway staging PostgreSQL rehearsal cannot be performed from this machine until a supported toolchain is available.

## Options considered

### Option A — Docker Desktop

Use Docker Compose with `postgres:16` and the existing `docker-compose.postgres.yml` profile.

### Option B — Native PostgreSQL

Install local PostgreSQL server/client tools and use `psql` plus the existing database URL flow.

### Option C — Railway staging PostgreSQL

Rehearse against a Railway staging PostgreSQL database with strict safety controls and no production credentials.

## Decision

**BLOCKED**

## Why this decision

- Option A is not available on this machine because Docker is missing.
- Option B is not available on this machine because `psql` is missing.
- Option C is not available from this local workspace alone because it would require a staging PostgreSQL environment that has not been provisioned or connected for rehearsal.

## Required next action

- Prepare the local toolchain by installing Docker Desktop or native PostgreSQL client/server tooling.
- Re-run the rehearsal setup verification after the toolchain is available.
- Only then run the PostgreSQL rehearsal commands in a controlled local or staging environment.

## Safety rules

- Do not use production `DATABASE_URL`.
- Do not run `db upgrade` against production.
- Do not create `migrations/versions/0002_workspace_foundation.py` during toolchain setup.
- Do not add approval markers or auto-deploy control files.
- Keep all rehearsal docs descriptive until the environment can be verified for real.

## Next task

**6.0.12 — PostgreSQL rehearsal toolchain setup verification**

