# Changelog

SpaManager release notes.

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
