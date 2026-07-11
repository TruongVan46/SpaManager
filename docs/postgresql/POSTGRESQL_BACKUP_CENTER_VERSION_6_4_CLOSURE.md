# SpaManager Version 6.4 â€” Backup Center and PostgreSQL Guards Closure

## 1. Version Status

- **Status:** **CLOSED / DONE**
- **Closure Status:** **READY FOR CLOSURE COMMIT** (Pending final commit review and execution by the Owner)

---

## 2. Completed Scope

Version 6.4 focused on auditing, securing, and reopening the Backup Center under PostgreSQL mode while establishing strict, production-ready, fail-closed guards:
- **6.4.1 â€” PostgreSQL Backup Center access audit:** Investigated role-based access to settings and backup subroutes. Verified that only authorized roles (OWNER and ADMIN) are permitted, while STAFF and anonymous users are blocked.
- **6.4.2 â€” PostgreSQL-only Backup Center UI policy:** Defined the read-only visual specification for Backup Center in PostgreSQL mode to prevent rendering SQLite-oriented controls.
- **6.4.3 â€” Reopen Backup Center route safely:** Reopened the settings backup route `/settings/backup` safely under PostgreSQL mode, rendering static system status information instead of action forms.
- **6.4.4b â€” PostgreSQL fail-closed hardening:** Implemented strict route-level guards in `routes/setting.py`. Ensured that legacy download, delete, and update-notes routes are blocked before repository, service, or filesystem access. Verified that create, restore, upload, and validate flows are fail-closed. Confirmed that the settings page `/settings` and Backup Center do not sync or list legacy SQLite artifacts.
- **6.4.5 â€” Local PostgreSQL backup decision:** Conducted a feasibility and security audit for automating local PostgreSQL backups, resulting in a manual-only runbook design to minimize attack surface.
- **6.4.6 â€” Final tests and closure verification:** Executed regression smoke tests, canonical test suite, and compilation audits to verify complete system compliance.

---

## 3. Final Runtime Behavior

### PostgreSQL Mode
- **Backup Center UI:** Strictly read-only. Does not render the legacy backup table, forms, buttons, identifiers, filenames, paths, or modals. Renders a dynamic database label `PostgreSQL` and a warning status banner.
- **Access Control:** OWNER and ADMIN roles have read-only access to Settings UI. STAFF access to all backup subroutes is blocked with HTTP 403 Forbidden.
- **Mutation Routes:** Write/mutation routes (create, restore, upload, validate, delete, and notes) and the protected legacy download route return HTTP 400 with a blocked warning and do not interact with the filesystem or database.
- **Guard Execution:** Security guards execute before any repository, service, or filesystem interaction occurs.
- **Production Operations:** All production backups are managed externally via the cloud provider (Railway) at the infrastructure level.

### SQLite Mode (Legacy/Test Fallback)
- **Legacy Compatibility:** Legacy SQLite behavior covered by the regression tests remains preserved for test/legacy fallback use.
- **Isolated Schema:** Not intended for production runtime. Renders dynamic database label `SQLite`.

---

## 4. Local Backup Decision

- **Status:** **NOT IMPLEMENTED BY DESIGN / MANUAL POWERSHELL-RUNBOOK ONLY**
- **Rationale:** The controlled schema-only smoke test using database role `postgres` without password failed with exit code `1` (`FATAL: role "postgres" does not exist`). This evidence only refutes the exact role-postgres password-free contract. The project did not continue database role discovery. The project did not implement automatic credential handling in application code. No Flask CLI commands or Web actions were created.
- **Security Strategy:** Alternative automation would require additional role discovery and credential-handling design. Because the feature is optional, the project declined that added security and maintenance surface. Manual PowerShell runbook execution requires operator-managed credentials outside the application code.
- **Reference Doc:** [PostgreSQL Local Backup Manual Runbook and CLI Decision Record](POSTGRESQL_LOCAL_BACKUP_MANUAL_RUNBOOK.md)

---

## 5. Test Evidence

### Targeted Regression Smoke
- **Command executed:**
  ```powershell
  $env:TEST_DATABASE_URL = "sqlite:///:memory:"
  Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
  Remove-Item Env:SPAMANAGER_ALLOW_POSTGRES_TESTS -ErrorAction SilentlyContinue

  .\venv\Scripts\python.exe -m unittest `
    tests.test_basic.BasicTestCase.test_settings_backup_center_shows_postgresql_read_only_policy `
    tests.test_basic.BasicTestCase.test_settings_postgresql_download_route_blocked `
    tests.test_basic.BasicTestCase.test_settings_postgresql_delete_route_blocked `
    tests.test_basic.BasicTestCase.test_settings_postgresql_notes_route_blocked `
    tests.test_basic.BasicTestCase.test_settings_staff_backup_subroutes_are_forbidden `
    tests.test_basic.BasicTestCase.test_settings_backup_center_preserves_sqlite_legacy_ui `
    tests.test_basic.BasicTestCase.test_settings_postgresql_backup_guard_blocks_create_restore_upload_and_validate `
    tests.test_basic.BasicTestCase.test_backup_center_view_get_route_access_controls
  ```
- **Results:** 8 tests executed, 8 passed, 0 failed.

### Canonical Isolated Test Suite
- **Command executed:**
  ```powershell
  $env:TEST_DATABASE_URL = "sqlite:///:memory:"
  Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
  Remove-Item Env:SPAMANAGER_ALLOW_POSTGRES_TESTS -ErrorAction SilentlyContinue

  python -m unittest discover -s tests -p "test_*.py"
  ```
- **Results:** 379 tests executed, 379 passed, 0 failed, 0 errors, 0 skips.
- **Database Isolation:** Isolated in-memory SQLite used for all automated test runs. No local or production PostgreSQL database accessed during tests.

### Compilation Audit
- **Command executed:**
  ```powershell
  python -m compileall app.py config.py core models repositories routes services utils tests
  ```
- **Results:** All source and test files compiled cleanly. No untracked cache artifacts generated.

---

## 6. Security Evidence

- **Early Guards:** Engine guards in `routes/setting.py` occur immediately before filesystem, repository, or service layers are accessed.
- **UI Safety:** No legacy backup identifiers, filenames, filesystem paths, forms, action buttons, or modals are rendered in PostgreSQL mode. The database label displaying PostgreSQL is rendered safely.
- **Pragmatic Scope:** No database migrations or credentials were added or modified in the workspace.
- **Git Hygiene:** Artifact scans and Git state checks do not detect any untracked or modified dump, database, or log files in the repository.

---

## 7. Version 6.4 Commit Checkpoints

The following historical commits representing the roadmap steps of Version 6.4 have been verified in the Git history:
- `abab196` â€” docs: audit PostgreSQL backup center â€” Task 6.4.1
- `a38b28f` â€” docs: define PostgreSQL backup center UI policy â€” Task 6.4.2
- `9b49ae2` â€” feat: reopen backup center route safely â€” Task 6.4.3
- `6b959c8` â€” fix: harden PostgreSQL backup center â€” Task 6.4.4b
- `a220af1` â€” docs: record local PostgreSQL backup decision â€” Task 6.4.5c

---

## 8. Accepted Limitations

- **No In-App PostgreSQL Backups:** Backup generation cannot be initiated via HTTP request in PostgreSQL mode.
- **No Web-Initiated Restoration:** Restoring a database via the user interface is disabled in PostgreSQL mode.
- **Manual Credentials:** Local backup execution depends entirely on manual operator intervention and credential provisioning in the terminal.
- **Provider-Managed Production:** Restoration of the production PostgreSQL database is external and handled by Railway infrastructure management.
- **SQLite Legacy Code:** SQLite backup code is preserved solely for integration testing and local development fallback.

---

## 9. Out-of-Scope / Future Work

- **Production Backup Observability:** Potential future integration with Railway APIs to render backup health status inside the read-only settings tab.
- **Encrypted Retention:** Potential design for automated offsite encryption of database dumps.
- **Restore Rehearsal Automation:** Design for sandboxed restoration tests in isolated staging environments.

---

## 10. Closure Decision

```text
READY FOR CLOSURE COMMIT
```

The Version 6.4 closure package matches the verified runtime behavior, all targeted and canonical automated tests pass, and the documentation is aligned with the active PostgreSQL and SQLite fallback policies. The closure commit remains pending final Owner/Reviewer execution.
