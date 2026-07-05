# Workspace Models and Migration Draft

## Scope

- Draft only.
- No executable migration.
- No model implementation.
- No production DB change.
- Railway pre-deploy risk acknowledged.

This document turns the v6.0.1 audit and v6.0.2 schema design into a concrete, non-executable draft for the next implementation tasks.

## Proposed SQLAlchemy models

### `Workspace`

Planned class shape:

```python
class Workspace(db.Model):
    __tablename__ = "workspaces"

    id = db.Column(...)
    name = db.Column(...)
    slug = db.Column(...)
    status = db.Column(...)
    created_at = db.Column(...)
    updated_at = db.Column(...)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_by = db.relationship("User", foreign_keys=[created_by_id], lazy=True)
    members = db.relationship("WorkspaceMember", back_populates="workspace", lazy=True)
    customers = db.relationship("Customer", backref="workspace", lazy=True)
    services = db.relationship("Service", backref="workspace", lazy=True)
    appointments = db.relationship("Appointment", backref="workspace", lazy=True)
    invoices = db.relationship("Invoice", backref="workspace", lazy=True)
    activity_logs = db.relationship("ActivityLog", backref="workspace", lazy=True)
    settings = db.relationship("Setting", backref="workspace", lazy=True)
```

### `WorkspaceMember`

Planned class shape:

```python
class WorkspaceMember(db.Model):
    __tablename__ = "workspace_members"

    id = db.Column(...)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(...)
    status = db.Column(...)
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    joined_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(...)
    updated_at = db.Column(...)

    workspace = db.relationship("Workspace", back_populates="members", lazy=True)
    user = db.relationship("User", foreign_keys=[user_id], lazy=True)
    invited_by = db.relationship("User", foreign_keys=[invited_by_id], lazy=True)
```

### Enum-like values

`Workspace.status`

- `active`
- `pending`
- `suspended`
- `archived`

`WorkspaceMember.role`

- `owner`
- `admin`
- `staff`

`WorkspaceMember.status`

- `active`
- `invited`
- `disabled`

## Existing model field additions

| Existing model | Planned field | Nullable during migration? | Target final state | Notes |
|---|---|---|---|---|
| `Customer` | `workspace_id` | Yes at first | No after backfill | Workspace-scoped customer data. |
| `Service` | `workspace_id` | Yes at first | No after backfill | Service names and pricing must stay in the workspace boundary. |
| `Appointment` | `workspace_id` | Yes at first | No after backfill | Calendar queries and status updates must be scoped. |
| `Invoice` | `workspace_id` | Yes at first | No after backfill | Reporting, export, and print flows depend on it. |
| `InvoiceDetail` | `workspace_id` | Optional / recommended | Optional or no after validation | Helps with report guards and denormalized safety. |
| `ActivityLog` | `workspace_id` | Yes at first | Depends on whether platform logs are allowed | Workspace logs should carry the boundary. |
| `Setting` | `workspace_id` | Nullable if mixed global/workspace settings | Depends on settings policy | Avoid ambiguous global/workspace key collisions. |

## Migration draft

### Pseudo-code only

```python
# PSEUDO-CODE ONLY — do not place in migrations/versions yet

def upgrade():
    # 1. create workspaces
    # 2. create workspace_members
    # 3. create a default workspace
    # 4. create membership for the current owner
    # 5. add nullable workspace_id columns to workspace-scoped tables
    # 6. backfill workspace_id for existing rows
    # 7. add indexes
    # 8. audit duplicates before unique constraints
    # 9. add composite unique constraints only when safe
    # 10. keep workspace_id nullable until app code is fully scoped
    pass


def downgrade():
    # Keep downgrade conservative.
    # Avoid destructive data removal.
    # Removing workspace columns is only a theoretical option before production adoption.
    pass
```

### Non-destructive step list

1. Create `workspaces`.
2. Create `workspace_members`.
3. Create default workspace.
4. Create workspace membership for the current owner.
5. Add nullable `workspace_id` columns to:
   - `customers`
   - `services`
   - `appointments`
   - `invoices`
   - `invoice_details`
   - `activity_logs`
   - `settings`
6. Backfill `workspace_id` from the default workspace.
7. Add indexes.
8. Add composite unique constraints after duplicate audit.
9. Only after workspace-scoped app code is stable should `NOT NULL` be considered.

### Backfill plan

- Create one default workspace for existing production data.
- Make the current owner a member of that workspace.
- Backfill all existing business rows to the default workspace.
- Decide whether old `activity_logs` and `settings` rows should stay global or be assigned to the default workspace based on their semantic meaning.
- Never drop legacy data as part of the first migration pass.

## Index and constraint draft

### `workspaces`

- `unique(slug)`
- index on `status`
- index on `created_at`

### `workspace_members`

- `unique(workspace_id, user_id)`
- index on `user_id`
- index on `(workspace_id, role)`
- index on `(workspace_id, status)`

### Workspace-scoped business tables

- `customers`: index on `(workspace_id, phone)` and `(workspace_id, email)` if duplicate detection is needed.
- `services`: index on `(workspace_id, name)`.
- `appointments`: index on `(workspace_id, appointment_time)`, `(workspace_id, status)`, `(workspace_id, customer_id)`.
- `invoices`: index on `(workspace_id, created_at)`, `(workspace_id, customer_id)`.
- `invoice_details`: index on `(workspace_id, invoice_id)` if `workspace_id` is added.
- `activity_logs`: index on `(workspace_id, created_at)`, `(workspace_id, user_id)`.
- `settings`: `unique(workspace_id, key)` if workspace-scoped.

## Downgrade / rollback considerations

- Do not drop data casually.
- A downgrade is only safe before production data is truly dependent on workspace tables.
- Once production uses workspace-scoped records, rollback becomes high risk.
- If a rollback is ever required, it should be a controlled data-migration plan, not a blind schema drop.

## Railway deploy risk

Railway currently runs:

```bash
python -m flask --app app db upgrade
```

as a pre-deploy command.

That means:

- If an executable migration is committed and pushed, Railway may run it automatically during deploy.
- A bad migration can reach production faster than a manual approval workflow would allow.
- Before any executable migration is introduced, we need local/staging rehearsal, PostgreSQL backup verification, duplicate-data audit, and owner confirmation.

For 6.0.3 specifically:

- Do **not** create the executable migration yet.
- Do **not** ship `migrations/versions/` code for workspace tables yet.
- Keep this as a draft until the migration implementation task is explicitly approved.

## Implementation checklist

### 6.0.4 — Workspace model implementation behind safe tests

- Add `models/workspace.py`.
- Add `models/workspace_member.py`.
- Add metadata/model tests.
- Keep route/query scoping untouched for now.

### 6.0.5 — Safe migration implementation and local rehearsal

- Create the executable migration.
- Rehearse locally and in staging before any production push.
- Review duplicate rows and backup safety before deploy.

### 6.0.6 — Default workspace bootstrap/backfill

- Add bootstrap/backfill code if the migration alone is not enough.
- Ensure existing production rows are assigned to a default workspace safely.

### 6.0.7 — Workspace context/session

- Add current workspace context to the session.
- Add auto-select / switch behavior if needed.

### 6.0.8 — Workspace-scoped query pass

- Update business queries to require workspace context.

### 6.0.9 — Workspace security tests

- Add regression tests for leakage, permissions, and cross-workspace data access.

### 6.0.10 — v6.0.0 checkpoint

- Confirm the workspace foundation is stable before release checkpointing.

## Open questions

- Should `activity_logs` keep platform-only rows, or should every log be attached to a workspace?
- Should `settings` remain mixed global/workspace in one table, or be split later?
- Should one user be allowed in multiple workspaces immediately in v6.0, or only after the next onboarding task?
- Do we need a workspace switcher in v6.0, or is auto-select enough for the first rollout?

## Notes

- This file is documentation only.
- No model or migration code should be copied from here into production without a separate implementation and rehearsal task.
