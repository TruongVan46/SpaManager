# Changelog

SpaManager release notes.

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
