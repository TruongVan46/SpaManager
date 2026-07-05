# PostgreSQL-only Product Mode Audit

## Scope

- Audit current SQLite/PostgreSQL usage.
- Prepare SpaManager for PostgreSQL-first / PostgreSQL-only product direction.
- Does not remove SQLite yet.
- Does not change production database.
- Does not run migrations.

## Product decision

- Production database: PostgreSQL on Railway.
- Local development target: Docker PostgreSQL.
- SQLite is no longer the main product database.
- SQLite may remain temporarily for legacy/unit-test fallback only.
- Google registration will be owner-approved, not open access.

## Current database state

- Production PostgreSQL cutover done.
- Backup Center PostgreSQL guard exists.
- Local Docker PostgreSQL works.
- Workspace migration production not run.
- No executable workspace migration exists.
- No approval marker exists.

## Audit findings

### 1. Config/database findings

| File/path | Current behavior | Risk | Recommendation | Priority |
|---|---|---|---|---|
| `config.py` | Development still defaults to `sqlite:///database/spa.db` when `DATABASE_URL` is unset. Testing defaults to in-memory SQLite, and Production requires `DATABASE_URL`. | Product docs and local flow still read as SQLite-first. | Make PostgreSQL the documented local/dev default in the next cleanup, while keeping SQLite only as explicit fallback. | P1 |
| `config.py` | `_normalize_database_url()` still normalizes `postgres://` to `postgresql://`. | Good compatibility, but it is still a transitional helper, not a product-mode decision. | Keep it for compatibility until all env references are cleaned. | P2 |
| `config.py` | `TEST_DATABASE_URL` is supported and falls back to SQLite memory when absent. | Fine for unit tests, but it keeps SQLite as the default test path. | Keep as fast unit-test fallback; add PostgreSQL integration profile later. | P2 |
| `.env.example` | Local development example still points `DATABASE_URL` to `sqlite:///database/spa.db`. | Strongly suggests SQLite is still the main local path. | Update docs/env in 6.1.2 so PostgreSQL local profile is the primary documented path. | P1 |
| `requirements.txt` | `psycopg2-binary` is already present. | No blocker for PostgreSQL-first runtime. | Keep. | P2 |
| `docker-compose.postgres.yml` | Local PostgreSQL profile exists with `postgres:16`, port `5433`, and local placeholders. | Good; it already supports PostgreSQL-first local dev. | Keep and document as the preferred local dev path. | P2 |
| `app.py` | If schema tables are missing, the app only logs a warning to run `flask db upgrade`; it does not auto-create schema. | Fresh databases must be initialized explicitly before use. | Keep the explicit migration flow and document the required init step more prominently. | P1 |

### 2. Runtime artifact findings

| File/path | Current behavior | Risk | Recommendation | Priority |
|---|---|---|---|---|
| `.gitignore` | Ignores `database/*.db`, `*.db`, `*.sqlite`, `*.sqlite3`, `backup/*`, `static/uploads/*`, `exports/*`, and `instance/*`. | Good baseline hygiene. | Keep. | P2 |
| Repo root | No `.dockerignore` is present. | Docker build contexts may still need manual care if added later. | Add `.dockerignore` only if a Docker build pipeline is introduced. | P2 |

### 3. Backup/restore findings

| File/path | Current behavior | Risk | Recommendation | Priority |
|---|---|---|---|---|
| `services/backup_service.py` | Backup creation is SQLite-only; PostgreSQL mode returns immediately and tells the user to use the PostgreSQL backup runbook. | Correct for current guard, but the main product message still needs to be PostgreSQL-first everywhere. | Keep the guard; rewrite product-facing docs so SQLite backup is clearly legacy-only. | P1 |
| `services/backup_service.py` | Backup directory supports a primary folder plus a read-only legacy folder fallback. | Safe for listing old files, but can be confusing if docs imply SQLite backups are still the main path. | Keep legacy read-only compatibility; document it as compatibility only. | P2 |
| `services/restore_service.py` | PostgreSQL restore is blocked; SQLite restore remains the implementation path. | Good safety for PostgreSQL mode, but the old SQLite flow is still the default implementation for SQLite mode. | Keep for legacy fallback only until a new PostgreSQL backup strategy is finalized. | P1 |
| `routes/setting.py` + `templates/setting/index.html` + `static/js/setting.js` | Backup Center disables create/upload/restore in PostgreSQL mode, but UI text still contains SQLite-oriented language in multiple places. | Confusing product positioning; admin may still think SQLite is the normal path. | Update wording in 6.1.4 to say PostgreSQL/provider backup is the production path and SQLite is legacy/test only. | P1 |
| `README.md` and `docs/postgresql/*` | Documentation now acknowledges PostgreSQL production, but several docs still explain SQLite backup/restore as a first-class workflow. | Mixed messaging. | Keep SQLite references only where they are explicitly labeled legacy/test fallback. | P1 |

### 4. Import/export/report/PDF findings

| File/path | Current behavior | Risk | Recommendation | Priority |
|---|---|---|---|---|
| Import/export/report/PDF code | No hard product dependency on SQLite for core reporting/PDF paths was found in this audit. | Low direct risk. | Keep as-is for now; only revisit if a future PostgreSQL-specific issue appears. | P2 |
| Temporary import/export files | Repo ignores the usual temporary upload/export artifacts. | Low risk if the ignore rules stay intact. | Keep artifact hygiene checks in CI/release checklist. | P2 |

### 5. Test findings

| File/path | Current behavior | Risk | Recommendation | Priority |
|---|---|---|---|---|
| `tests/test_basic.py` | Test suite still uses SQLite in-memory/temp DB for fast unit coverage. | This is still the main fast test path, so the repo is not yet PostgreSQL-only in test strategy. | Keep SQLite for fast unit tests, but add a PostgreSQL integration smoke plan in the next cleanup task. | P2 |
| `tests/test_basic.py` | Existing tests already cover PostgreSQL config handling, database engine helpers, and Backup Center guards. | Good safety coverage. | Keep and extend only when adding PostgreSQL integration smoke. | P2 |

### 6. Docs findings

| File/path | Current behavior | Risk | Recommendation | Priority |
|---|---|---|---|---|
| `README.md` | Intro still says the app runs with SQLite, even though production is now PostgreSQL. | Top-level positioning is still mixed. | Update the intro in 6.1.2 to state PostgreSQL is production and SQLite is legacy/fallback. | P1 |
| `docs/postgresql/README.md` | Current index is already PostgreSQL-focused and contains the rehearsal / cutover docs. | Good base, but missing a dedicated product-mode audit link. | Add this audit doc to the index. | P2 |
| `docs/RUNBOOK.md`, `docs/ADMIN_GUIDE.md`, `docs/postgresql/*` | Many docs still describe SQLite backup/restore as the main flow. | Product wording is not yet PostgreSQL-only. | Clean the language in the next docs pass; keep SQLite only where explicitly marked legacy/test. | P1 |

### 7. Migration findings

| File/path | Current behavior | Risk | Recommendation | Priority |
|---|---|---|---|---|
| `migrations/versions/0001_baseline.py` | Baseline migration calls `db.create_all()` after importing all models. | Fresh DB initialization depends on the current model set and remains a broad bootstrap step. | Keep it as the current baseline for now, but document that fresh DBs must run `flask db upgrade` explicitly. | P1 |
| `migrations/versions/` | No `0002_workspace_foundation.py` executable exists. | Good: no accidental workspace deploy file is present. | Keep approval controls intact. | P2 |
| `docs/workspace/migration_candidates/` | Docs-only candidate and approval-gate docs exist; no approval marker exists. | Safe. | Leave as-is until an explicit approval workflow is triggered. | P2 |

### 8. Google approval readiness findings

| File/path | Current behavior | Risk | Recommendation | Priority |
|---|---|---|---|---|
| `models/user.py` | Has `role`, `is_active`, `email`, `email_verified`, `auth_provider`, and `oauth_id`. | The model is partially prepared for Google identity, but there is no account status lifecycle yet. | Add `user.status` later with `pending/active/rejected/disabled` semantics. | P1 |
| `routes/auth.py` + `templates/auth/login.html` | Login/logout/change-password/profile exist; no Google registration or OAuth flow. | Google registration is not ready and should not auto-approve. | Keep Google auth out until the PostgreSQL-only cleanup is finished. | P1 |
| `routes/user.py` / admin tooling | User management focuses on current local roles and activation. | No owner-approval workflow for external signups. | Build owner approval UI in a separate v6.2 task. | P1 |

## Recommended cleanup plan

### 6.1.2 PostgreSQL-only configuration and docs cleanup

- Make PostgreSQL the documented default.
- Keep SQLite only as explicit legacy/test fallback.
- Update `.env.example`.
- Update README local dev flow.
- Update docs language.

### 6.1.3 PostgreSQL local dev smoke test

- Use Docker PostgreSQL.
- Run `db upgrade`.
- Run app smoke.
- Run tests.

### 6.1.4 PostgreSQL backup policy hardening

- Clarify provider backup.
- Hide or disable misleading SQLite backup UI in PostgreSQL mode.
- Add docs for restore strategy.

### 6.1.5 Remove or isolate SQLite runtime artifacts

- Ensure `.gitignore` covers DB files.
- Remove stale local DB files from the working tree if any.
- Keep tests safe.

### 6.2 Owner-approved Google authentication

- Add user status.
- Add pending registration.
- Add owner approval UI.
- Add Google OAuth only after DB mode is clean.

## Do not do yet

- Do not remove SQLite code blindly.
- Do not delete production data.
- Do not run workspace production migration.
- Do not add Google OAuth yet.
- Do not allow auto-approved Google users.

## Final recommendation

- PostgreSQL-only cleanup: **NOT READY**.
- Main blockers:
  - Local/dev docs still present SQLite as the default path.
  - README intro still says the app runs with SQLite.
  - Backup/restore docs and UI still mix PostgreSQL production with SQLite-first language.
  - Google approval flow is not implemented yet.
- Next task should be: **6.1.2 PostgreSQL-only configuration and docs cleanup**.
