# SpaManager

> Modern Spa Management System built with Flask.

## Overview

SpaManager is a modern web-based management system for spa and beauty salons. It provides customer management, appointment scheduling, invoice management, statistics, backup & restore, Dark Mode, and responsive UI. The project follows a layered architecture and is being prepared for migration to a cloud-native SaaS platform.

## Highlights

- Dashboard Analytics
- Customer Management
- Appointment Scheduling
- Invoice Management
- Statistics & Reports
- Backup & Restore Center
- Command Palette
- Recycle Bin
- Dark Mode
- Responsive Design
- Accessibility (WCAG 2.1 AA)

## Why SpaManager?

Unlike a typical academic CRUD project, SpaManager emphasizes clean architecture, maintainability, accessibility, performance, and a future cloud migration path.

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Flask |
| ORM | SQLAlchemy |
| Database | SQLite |
| Frontend | Bootstrap 5 |
| JavaScript | Vanilla JavaScript |
| Charts | Chart.js |
| Testing | Playwright + unittest |

## Architecture

- MVC
- Repository Pattern
- Service Layer
- Validator Layer
- Core Layer

## Folder Structure

```text
core/
models/
repositories/
routes/
services/
validators/
templates/
static/
docs/

Runtime folders (ignored by Git):
database/
backup/
logs/
exports/
instance/
```

## Installation

```bash
git clone https://github.com/<your-username>/SpaManager.git
cd SpaManager

python -m venv venv

# Windows
venv\Scripts\activate

pip install -r requirements.txt

python run.py
```

The application automatically creates the SQLite database on first launch.

## Testing

```bash
python -m unittest discover
```

Playwright integration tests are also included.

## Roadmap

### Completed
- Dashboard
- Customer
- Appointment
- Invoice
- Statistics
- Backup Center
- Restore Center
- Dark Mode
- Responsive Design

### Next
- PostgreSQL
- Docker
- Google OAuth
- REST API
- Cloud Deployment
- SaaS Architecture

## Development Status

| Item | Status |
|---|---|
| Current Version | v4.0 Stable |
| Architecture | Local-first |
| Next Milestone | Cloud Edition (v5.x) |
| Long-term Goal | SaaS Platform |

## Documentation

- CHANGELOG.md
- CSS_ARCHITECTURE.md
- JAVASCRIPT_ARCHITECTURE.md
- AUDIT_REPORT_v3.7.md

## License

MIT License.

## Author

**Trường Văn**

Software Engineering Student

GitHub: https://github.com/truongvan46
