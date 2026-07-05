# Changelog

SpaManager release notes.

## [v5.7.0] - 2026-07-05

### Added
- Added post-handover QA checklist in `docs/QA_CHECKLIST.md`.
- Added reproducible demo data plan in `docs/DEMO_DATA.md`.
- Expanded route smoke and regression coverage for core pages, empty states, permissions, and docs links.
- Added rehearsal validation coverage for import templates, PDF/Unicode, backup metadata, and artifact cleanup.

### Changed
- Refined README and documentation index links.
- Updated stale user management description in README.
- Refined runbook with quick post-deploy smoke guidance.
- Refined QA checklist with issue/incident notes.
- Marked `docs/TECH_DEBT.md` as historical technical debt notes.

### QA / Validation
- Added route smoke tests for public and authenticated pages.
- Added empty-data smoke tests.
- Added permission matrix smoke tests.
- Added docs/QA link regression checks.
- Added import/PDF/backup rehearsal coverage.
- Full test suite and compile checks pass before release.

### Safety
- No schema or migration changes.
- No business logic, auth, permission, CSRF, backup/restore, PDF/export, import, or CLI behavior changes.
- No production seed or real demo data was added.
- No database, backup, import temp, PDF/export, or runtime artifacts were committed.
- No secrets, passwords, real customer data, or real database URLs were added.

## [v5.6.0] - 2026-07-05

### Added
- Production runbook and release checklist in `docs/RUNBOOK.md`.
- User guide and admin guide in `docs/USER_GUIDE.md` and `docs/ADMIN_GUIDE.md`.
- Demo script and local demo data plan in `docs/DEMO_SCRIPT.md`.
- Documentation index in `docs/README.md`.

### Changed
- Documentation links in the main README now point to the handover doc set.
- Legacy v3.x audit reports were moved into `docs/archive/`.
- Backup Center labels visible to users were localized to Vietnamese.

### Documentation
- Added smoke checklist, release checklist, backup and restore safety notes, internal CLI usage, rollback guidance, security checks, and production do-not-run guidance.
- Added daily workflow guidance for customers, services, appointments, invoices, statistics, search/filter, recycle bin, and common issues.
- Added admin guidance for roles, user management, password policy, login protection, Activity Log, Settings, Backup/Restore, Recycle Bin, diagnostics, and troubleshooting.
- Added demo guidance for handover and presentation using fake local-only data.

### Safety
- No schema or migration changes.
- No production seed or real demo data was added.
- No backup, runtime, or import artifacts were committed.
- No secrets, passwords, real customer data, or real database URLs were added to documentation.
- No business logic, auth, permission, CSRF, backup/restore, PDF/export, or CLI behavior changed.

### Tests
- Added regression coverage for Backup Center Vietnamese labels.
- Existing tests and compile checks remain passing.

## [v5.5.0] - 2026-07-05

### Added
- Login protection with lightweight in-memory rate limiting by username and IP.
- Failed-login telemetry with ActivityLog events:
  - `AUTH_LOGIN_FAILED`
  - `AUTH_LOGIN_RATE_LIMITED`
- Security / Accounts section in operational diagnostics.
- Route-level regression coverage for user lifecycle workflows.

### Changed
- Password policy validation was centralized and shared across change password, admin reset password, and create user.
- Login UI now handles failed login and rate-limited responses consistently.
- Operational diagnostics now reports user, role, and security visibility.

### Fixed / Hardened
- Login failed and rate-limited attempts now have dedicated telemetry.
- Password policy messages are clearer and consistent.
- User lifecycle routes are protected by regression tests:
  - create user
  - edit user
  - reset password
  - toggle active/inactive
  - self-disable/self-demotion protection
  - STAFF blocked from user management
- ActivityLog sanitization continues to prevent password fields from being exposed.

### Safety
- No schema or migration changes.
- No password plaintext logging.
- No token, session, or secret logging.
- No change to CSRF, session, or permission model.
- No rewrite to Flask-Login.
- Rate limiting remains in-memory and best-effort for small deployments.

### Tests
- Added tests for login protection, password policy, security diagnostics, and user lifecycle route regressions.
- Existing auth, CSRF, permission, data audit, repair, perf, and ops diagnostics behavior preserved.

## [v5.4.0] - 2026-07-05

### Added
- Operational diagnostics report for app, database, backup, audit, repair dry-run, and performance summaries.
- Release checkpoint for the 5.4 stabilization milestone.

### Changed
- Version labels and backup metadata now reflect the current `APP_VERSION` release checkpoint.

### Fixed
- Read-only operational reporting now avoids side effects during CLI diagnostics.

### Tests
- Expanded regression coverage for diagnostics and release metadata.

## [v5.3.0] - 2026-07-05

### Added
- Customer detail page with appointment and invoice history.
- Appointment workflow polish for faster operator review.
- Invoice and payment status polish for clearer staff workflows.
- Statistics and reporting improvements across key dashboards.
- Search/filter UX polish while preserving live filtering and highlight behavior.
- Mobile and tablet workflow refinements for core business pages.

### Changed
- Customer detail pagination now preserves return links and AJAX partial refresh behavior.
- Sidebar, settings, and topbar version labels continue to render from `APP_VERSION`.
- Backup metadata now tracks the current application version.

### Fixed
- Customer history, appointment, invoice, statistics, and recycle bin UI regressions.
- Vietnamese encoding issues in sidebar, backup center, and PDF exports.
- Search and pagination layout regressions on statistics and shared tables.

### Security / Stability
- Preserved CSRF, role, and actor safety checks during recent workflow updates.
- Kept backup and restore behavior compatible with persistent storage.

### Tests
- Expanded regression coverage for live search, workflow pages, PDF export, and backup metadata.

## [v5.2.0] - 2026-07-04

### Added
- Basic User Management for OWNER/ADMIN.
- Role/permission helpers for OWNER / ADMIN / STAFF.
- Admin Dashboard summary for OWNER/ADMIN.

### Changed
- Sidebar visibility now follows role permissions.
- Settings menu moved to bottom of sidebar.
- Backup/restore UX improved with clearer warnings and confirmation.

### Fixed
- Sidebar Vietnamese mojibake.
- Activity Log action badge overlap.
- Shared pagination page-size full reload regression.
- Backup Center Vietnamese mojibake.

### Security
- STAFF blocked from admin routes at backend.
- Activity Log sanitization for password/token/csrf/session/path.
- Settings/backup/restore/import path and CSRF hardening.
- Restore/import/backup no-side-effect regression tests.

### Infrastructure / Tests
- Expanded regression test coverage.
- GitHub Actions remains passing.

## [v5.1.0] - 2026-07-04

### Added
- Production Stabilization checkpoint for SpaManager 5.1.
- SQLite migration baseline for safe stamp/upgrade on the current production database.

### Changed
- Standardized timezone handling to `Asia/Ho_Chi_Minh`.
- Aligned `deleted_by` actor auditing for delete, restore, and permanent delete flows.
- Rendered web version labels from `APP_VERSION`.

### Fixed
- Standardized HTML/JSON error handling for 404 and 500 pages.
- Added CSRF protection for forms, JSON, multipart requests, and login/logout flows.
- Fixed CSS scope regressions, mobile layout issues, appointment calendar/offcanvas scrolling, and command palette discovery/close UX.

### Security
- Tightened request protection for unsafe state-changing flows.

### Infrastructure
- Kept GitHub Actions CI green for test and compile verification.

## [v4.0] - 2026-06-29

- Earlier release checkpoint retained for project history.
