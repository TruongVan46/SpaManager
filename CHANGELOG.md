# Changelog

SpaManager release notes.

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
