# Task 6.6.7e1 — PostgreSQL Functional Rehearsal Harness

## Scope

This task implements the functional PostgreSQL rehearsal harness only. Opted-in
tests were not run in this task. The actual target is the dedicated database
`spamanager_purge_rehearsal_test` at local `localhost:5433`, with migration
revision `0007_permanent_purge_workflow`.

The client endpoint is `localhost:5433`; the PostgreSQL server inside the
container is expected to report internal port `5432`.

## Lazy and guarded runtime

The PostgreSQL modules have no top-level application, extension, service, or
model imports. Runtime initialization occurs only after the exact four markers
are accepted and the fresh-process check passes:

```text
APP_ENV=testing
SPAMANAGER_TEST_PROCESS=1
SPAMANAGER_ALLOW_POSTGRES_TESTS=1
SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL=1
```

The first opted-in connection performs database identity, migration revision,
workflow table, and workspace terminal-column checks before any reset or test
fixture mutation. A normal run without the dedicated opt-in skips before app,
engine, or database initialization.

## Dedicated reset safety

Reset is allowed only after the exact target and revision are revalidated and
the public table inventory equals the explicit migration-0007 allowlist. It
uses an allowlisted `TRUNCATE ... RESTART IDENTITY CASCADE` for application
tables only. `alembic_version` is explicitly excluded and never changed.

The helper does not drop databases or schemas, does not touch `spamanager_dev`,
does not invoke Docker/psql, and does not use reflection-based broad cleanup.
Cleanup runs before and after each functional test, including failure paths.

## Synthetic functional scenarios

The skipped-by-default PostgreSQL tests cover:

- schema and runtime identity;
- request creation, immutable manifest, provenance, duplicate mapping, and event creation;
- approval, retention eligibility, event ordering, and manifest immutability;
- active legal hold blocking;
- committed manifest drift rejection;
- owner/workspace restore invalidation;
- successful internal purge with preserved users/audit and terminal tombstone;
- rollback after a controlled post-mutation exception;
- logo-reference blocking without filesystem operations.

Successful purge verification preserves all three synthetic users, verifies all
purged business tables (including benign Settings and WorkspaceMembers), and checks
terminal-marker consistency. Scalar snapshots are captured inside the active session
to prevent detached ORM reads after session removal. Manifest drift adds a new counted
customer row, approval verification uses fresh session state to verify manifest hash
immutability, and rollback checks every fixture table (including settings and workspace members)
and terminal marker. The duplicate lifecycle verification checks that exactly one request and one
event are preserved with unchanged provenance, while restore invalidation asserts the exact
expected status (REQUESTED) and associated events. Restore audit preservation is verified by
matching the unique synthetic audit description, and restore activity is validated separately.
The invalid database target is blocked by the actual fixture helper before any runtime module
import or engine creation occurs. Failed runtime initialization properly cleans up session,
engine pool, and pops app context. The harness performs no filesystem fixture or
filesystem mutation; a non-empty logo reference is blocked before purge.

No concurrency or network commit-uncertainty proof is included. Production and
Railway targets are forbidden. `spamanager_dev` is protected. Production purge
remains unauthorized and the production feature flag remains false.

PostgreSQL tests remain unexecuted in normal runs without the dedicated opt-in.
Version 6.6 remains open.

## Task 6.6.7e1.5 — Test-Only Service Session Timeout Bridge

### Problem

The core services (`PurgeRequestService`, `PurgeService`) create independent
SQLAlchemy sessions via their own `_new_session()` staticmethods at method entry:

```python
# PurgeRequestService.create_purge_request, approve_purge_request:
session = PurgeRequestService._new_session()
# PurgeService.execute_workspace_purge:
session = PurgeService._new_session()
```

These independent sessions bypass any timeout configured on the Flask scoped
`db.session`, making `prepare_scoped_session()` alone insufficient to protect
service transactions.

`UserService.restore_owner_workspace` uses the Flask scoped `db.session`
directly and is covered by `prepare_scoped_session()` called immediately before
the service invocation.

### Solution

The harness wraps the real `_new_session` factory on each service class using
`monkeypatch`, test-only. The runtime service source files are not modified.

**`apply_transaction_timeouts(executor)`** — shared helper in
`tests/postgresql/rehearsal_runtime.py`. Accepts either a SQLAlchemy `Connection`
or `Session` and executes:

```sql
SET LOCAL lock_timeout = '2s'
SET LOCAL statement_timeout = '30s'
```

Both SQL strings exist exactly once, in this helper. No other harness method
duplicates them.

**`wrap_service_new_session(service_class, monkeypatch)`** — installs a wrapper
around `service_class._new_session` using `inspect.getattr_static` to discover
the exact descriptor type (staticmethod / classmethod / instance method) and
preserve it. The wrapper:

1. Calls the original `_new_session`;
2. Calls `apply_transaction_timeouts(session)` immediately on the new session,
   before any domain query;
3. Returns the armed session;
4. On timeout setup failure: rolls back, closes, and re-raises the original error.

**`postgres_service_session_timeouts` fixture** (function-scoped, in
`tests/postgresql/conftest.py`) — wraps `PurgeRequestService._new_session` and
`PurgeService._new_session` using `monkeypatch`. Wrappers are automatically
restored at end of test.

**`postgres_case`** fixture depends on `postgres_service_session_timeouts` so
every functional test that creates service sessions inherits timeout coverage.

### Transaction Boundary Coverage

Every independent transaction created by the harness or through services receives
`lock_timeout = 2s` and `statement_timeout = 30s` applied as `SET LOCAL` (per
transaction, not session-persistent):

| Path | Mechanism |
|------|-----------|
| Standalone `identity()` | `engine.begin()` → `apply_transaction_timeouts(connection)` |
| `reset_database()` | `engine.begin()` → `identity(connection)` → timeout applied once |
| `new_session()` | construct → `apply_transaction_timeouts(session)` → cleanup on failure |
| `prepare_scoped_session()` | `db.session` → `apply_transaction_timeouts(session)` → cleanup on failure |
| `PurgeRequestService._new_session` | wrapped by bridge fixture |
| `PurgeService._new_session` | wrapped by bridge fixture |
| `UserService.restore_owner_workspace` | `prepare_scoped_session()` called immediately before |

### Descriptor and Cleanup Safety

The wrapper preserves the original descriptor type, ensuring `_new_session`
continues to behave as a `staticmethod` (which both service factories are).
On timeout failure, the newly created session is rolled back and closed to
prevent connection pool exhaustion. All timeout cleanup paths (`wrap_service_new_session`,
`prepare_scoped_session`, and `new_session`) use a traceback-preserving bare `raise`
to ensure that original timeout exceptions are propagated without alteration.

### Post-Service Verification and Duplicate Scenarios

Post-service verification is executed using bounded independent sessions (via `new_session()`).
Specifically:
- Service summaries (`PurgeRequestSummary` DTO) and persisted database models (`WorkspacePurgeRequest`) have different contracts. Fields like `manifest_canonical_text`, `target_deleted_at`, and `target_deleted_by_id` are not exposed by the summary DTO and are instead loaded from the persisted database model via independent sessions.
- In `test_request_creation_manifest_and_duplicate` and `test_approval_event_ordering_and_manifest_immutability`, verification sessions are closed before service mutations or duplicate service execution are triggered, preventing open read transactions.
- During a prior controlled rehearsal, the first 3 tests passed successfully. However, `test_approval_event_ordering_and_manifest_immutability` failed due to a harness DTO-contract mismatch (`AttributeError` when attempting to read `manifest_canonical_text` directly from `PurgeRequestSummary`). Importantly, the database cleanup invariant successfully executed and returned all application tables (including workspaces) to zero.

### No-Opt-In Behavior

With opt-in environment variables absent, skip occurs before:
- `ensure_fresh_process()` is called;
- `validate_rehearsal_environment()` is called;
- `rehearsal_runtime` is imported.

Contract tests verify the conftest-local references are patched and no runtime
module import occurs during the skip path.

### Terminal-Column ORM/Core Contract

Migration `0007_permanent_purge_workflow` adds two terminal columns to the
`workspaces` table:

- `purged_at` (TIMESTAMP);
- `purge_request_id` (INTEGER FK to `workspace_purge_requests`).

These columns are **not mapped on the `Workspace` ORM class**. Attempting to
access `workspace.purged_at` or `workspace.purge_request_id` via SQLAlchemy
ORM raises `AttributeError: 'Workspace' object has no attribute 'purged_at'`.

The runtime service (`PurgeService`) writes these terminal markers using the
SQLAlchemy Core table object:

```python
models.purge.workspace_terminal_state_table
```

The harness must therefore verify terminal state using a Core `select()` query:

```python
from sqlalchemy import select
from models.purge import workspace_terminal_state_table

terminal = verification.execute(
    select(workspace_terminal_state_table).where(
        workspace_terminal_state_table.c.id == workspace_id
    )
).mappings().one()

assert terminal["purged_at"] == execution_time
assert terminal["purge_request_id"] == request_id
```

For non-purged scenarios (legal-hold block, rollback), assertions are:

```python
assert terminal["purged_at"] is None
assert terminal["purge_request_id"] is None
```

### Task 6.6.7e4 Controlled Rerun — Result

The second controlled rehearsal (Task 6.6.7e4) reached:

- 4 tests passed (harness foundation + schema identity + request creation +
  approval event ordering);
- `test_active_legal_hold_blocks_approval` failed with:
  `AttributeError: 'Workspace' object has no attribute 'purged_at'`
  at post-approval verification, after the service's legal-hold guard had
  correctly raised `PurgeRequestConflictError` (i.e., the block mechanism
  itself functioned correctly);
- post-failure cleanup invariant **PASS**: all application tables returned to 0.

This was a harness ORM/Core contract defect, not an application runtime defect.
The functional rehearsal is **not** declared PASS from Task 6.6.7e4.

Task 6.6.7e5 corrects the harness by replacing all direct ORM terminal
attribute access with Core `workspace_terminal_state_table` queries in the
three affected test functions.

### Task 6.6.7e6 Controlled Rerun — Result

The controlled PostgreSQL suite collected 9 tests, not 10. Five tests passed
before `test_restore_invalidates_request` failed, before runtime restore
execution began. The harness attempted to call `PurgeRequestService.UserService`,
but `PurgeRequestService` does not expose `UserService`; the direct service
bundle namespace is required. The post-failure cleanup invariant passed: all 13
application tables returned to 0, with the expected schema identity and
revision `0007_permanent_purge_workflow` intact. No application runtime defect
was established by this failure, and the functional rehearsal is still not
declared PASS.
