# Version 6.6 - Task 6.6.3a
# Permanent Purge Migration Implementation Record

## Status

```text
MIGRATION FILE REVISED / FINAL STATIC RE-REVIEW REQUIRED
```

This record documents a provisional workflow-only migration. Migration
execution is **NOT APPROVED**.

## Scope and authorization

- Base revision: `0006_user_ws_soft_delete`.
- Provisional revision: `0007_permanent_purge_workflow`.
- No purge request, hold, lifecycle event or schedule is created by the migration.
- No business rows, business FKs, slug values, InvoiceDetail ORM mapping or runtime code are changed.
- No model, route, service, UI or test changes are included.
- No database, PostgreSQL, Docker, Railway or migration command was run in this task.

Task 6.6.3a is limited to creating and statically reviewing the migration source.
Execution remains not approved.

## Migration loader audit

`core/migration_cli.py` imports revision modules, calls `module.upgrade()`
without arguments, and only after it returns successfully opens a separate
`db.engine.begin()` connection to update `alembic_version`. The stamp is not
written before `upgrade()` and is not performed on the migration's connection.
Consequently, if SQLite DDL commits but pragma restoration raises, the loader
does not stamp the revision; the migration raises an explicit recovery error
instead of silently claiming completion.

## Files

Created or revised:

- `migrations/versions/0007_permanent_purge_workflow.py`
- `docs/workspace/PERMANENT_PURGE_MIGRATION_IMPLEMENTATION.md`

README receives only the existing implementation-record link.

## Schema implemented by the source

The migration source defines:

- `workspace_purge_requests` with lifecycle, actor snapshots, retention, status, manifest/hash, idempotency, retry and hold-clearance fields.
- `purge_legal_holds` with controlled `ACTIVE` to `RELEASED` lifecycle and retained release provenance.
- `purge_lifecycle_events` with non-null `request_id`, `event_sequence`, `event_at`, sanitized metadata and append-only application contract.
- `workspaces.purged_at` and `workspaces.purge_request_id`.
- Terminal consistency check and unique terminal request binding.

The request table enforces the portable one-lifecycle-per-deletion-event constraint:

```text
UNIQUE (workspace_id, target_deleted_at)
```

No duplicate non-unique or partial unique index is created for that pair.

## Constraint and FK contract

- Request target: `workspace_id -> workspaces.id ON DELETE RESTRICT`.
- Actor references: user FKs use `ON DELETE SET NULL` where supported, with required sanitized snapshots where provenance is retained.
- Hold target: `workspace_id -> workspaces.id ON DELETE RESTRICT`.
- Event request: `request_id -> workspace_purge_requests.id ON DELETE RESTRICT`.
- Event workspace: `workspace_id -> workspaces.id ON DELETE RESTRICT`.
- Event actor: nullable user FK with actor snapshot.
- Terminal marker: `uq_workspaces_purge_request_id` and `ck_workspaces_purge_terminal_consistency`.
- Status, hold-status, hash, sequence, attempt and completion checks are included in the portable DDL.
- An active legal hold has no stale release actor, snapshot, timestamp or reason.
- A released legal hold requires release timestamp, release snapshot and release reason.

## SQLite transaction-control conclusion

SQLite rebuild is implemented with a DBAPI-owned transaction on the same
connection used by SQLAlchemy statements:

1. Commit any SQLAlchemy inspection transaction.
2. Obtain the DBAPI connection and capture the original `PRAGMA foreign_keys` value.
3. Execute `PRAGMA foreign_keys=OFF` through the DBAPI connection outside an explicit SQLAlchemy transaction.
4. Read back the pragma and require value `0`.
5. Issue `BEGIN IMMEDIATE` through the DBAPI cursor.
6. Run SQLAlchemy statements on that same DBAPI transaction and coordinate one commit or rollback.
7. Restore the original pragma through DBAPI after rollback or commit.
8. Read back the restored value and fail closed if it differs.

The repository audit found SQLAlchemy `2.0.51`, Flask-SQLAlchemy `3.1.1`, no
SQLite `BEGIN` event hook, and `SQLiteDialect_pysqlite.do_begin()` implemented
as `pass`. Therefore `connection.begin()` alone is not treated as proof of a
real SQLite DBAPI transaction.

The migration does not use `ALTER TABLE ... RENAME TO _workspaces_0007_old` as its
first operation. If the connection cannot honor this pragma/transaction contract,
execution must be blocked rather than weakening the migration.

## SQLite safe create-new rebuild

The upgrade sequence is:

1. Inspect the exact revision-0006 workspace schema.
2. Reject unknown columns, missing expected indexes/FKs, unsupported triggers/views and stale temporary tables.
3. Create `workspace_purge_requests`, `purge_legal_holds` and `purge_lifecycle_events` in the transaction.
4. Create `_workspaces_0007_new` with the old schema plus terminal fields and the terminal FK.
5. Copy the old workspace columns explicitly; terminal target columns receive `NULL, NULL` source expressions.
6. Drop the canonical `workspaces` table.
7. Rename `_workspaces_0007_new` to `workspaces`.
8. Recreate every expected named workspace index.
9. Run `PRAGMA foreign_key_check` and verify tables, columns, indexes, FK, UNIQUE and CHECK objects.
10. Commit and restore the original foreign-key pragma state.

No temporary table is intentionally left after success or rollback. Setup-stage
failures also attempt pragma restoration. Operation and restoration errors are
chained; a restoration failure invalidates the connection. If DDL has already
committed, the error explicitly states that the revision may remain unstamped
and requires recovery. The migration does not use `legacy_alter_table` or
writable-schema editing.

## Circular FK handling

The circular relationship is handled while foreign-key enforcement is disabled only
for the explicit transactional rebuild:

```text
workspace_purge_requests.workspace_id -> workspaces.id
workspaces.purge_request_id -> workspace_purge_requests.id
```

The request table is created first against the existing canonical `workspaces` name.
The new workspace table is then created with its terminal FK, rows are copied with
null terminal values, the old table is dropped, and the new table is renamed to the
canonical name. The final foreign-key check must return zero rows.

## Full SQLite schema-preservation gate

Before rebuilding, the source checks:

- exact revision-0006 workspace columns;
- expected `PRAGMA foreign_key_list(workspaces)` entries;
- expected `PRAGMA index_list(workspaces)` names;
- SQLite schema entries for triggers/views referencing `workspaces`;
- absence of `_workspaces_0007_new` and `_workspaces_0007_old`.

Unknown extra columns and unsupported triggers/views fail closed. The copy lists
source and target expressions separately:

```text
Upgrade target: base columns + purged_at + purge_request_id
Upgrade source: base columns + NULL + NULL
Downgrade target: base columns
Downgrade source: base columns
```

The upgrade and downgrade verification gates also confirm the complete expected
workspace schema and `PRAGMA foreign_key_check` result.

The workspace column signature includes ordinal, name, normalized declared type,
not-null flag, normalized default, primary-key position and hidden flag. The
canonical revision-0006 signature is:

```text
id INTEGER PK; name VARCHAR(150) NOT NULL; slug VARCHAR(150) NOT NULL;
status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'; created_by_id INTEGER;
notes TEXT; created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;
updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP; deleted_at TIMESTAMP;
deleted_by_id INTEGER; deletion_reason VARCHAR(255)
```

Revision 0007 appends:

```text
purged_at TIMESTAMP; purge_request_id INTEGER
```

Named workspace indexes are verified by table, unique/origin/partial flags and
ordered `index_xinfo` keys:

```text
ix_workspaces_slug -> slug
ix_workspaces_status -> status
ix_workspaces_created_at -> created_at
ix_workspaces_created_by_id -> created_by_id
ix_workspaces_purged_at -> purged_at (0007 only)
```

SQLite foreign keys are grouped by foreign-key id and ordered by sequence, then
compared as referenced table, ordered source/reference columns, ON UPDATE,
ON DELETE and MATCH signatures. Duplicate or extra FKs fail closed. SQLite
UNIQUE constraints are verified through autoindex metadata and ordered columns;
`UNIQUE (workspace_id, target_deleted_at)` is a full unique constraint, not a
partial or duplicate non-unique index. CHECK verification matches normalized
constraint expressions, not names alone.

The deterministic `PRAGMA index_xinfo` tuple is:

```text
(seqno, cid, name, desc, collation, key)
```

Auxiliary `key=0` entries are retained but excluded from the ordered indexed-key
column list. Static import self-checks validate representative workspace index
metadata and the PostgreSQL CHECK normalizer without opening a database.

Each `PRAGMA index_xinfo` entry is normalized as:

```text
(seqno, cid, name, desc, collation, key)
```

Auxiliary `key=0` rows are retained in the signature but are not treated as
indexed key columns. Workspace key signatures use the audited cids:

```text
slug -> cid 2
status -> cid 3
created_at -> cid 6
created_by_id -> cid 4
purged_at -> cid 11 (0007 only)
```

## PostgreSQL strategy

PostgreSQL uses additive columns, named FK/UNIQUE/CHECK constraints, portable
string/text/date types and named indexes. It does not use UUID, JSONB or ENUM in
this baseline. PostgreSQL partial uniqueness is not used for
`(workspace_id, target_deleted_at)`.

The custom loader calls `module.upgrade()` first and stamps `alembic_version`
later using a separate `db.engine.begin()` connection. PostgreSQL preflight, DDL
and verification run inside one `db.engine.begin()` transaction. After upgrade,
the source verifies all three workflow tables, terminal workspace
columns, required indexes and named constraints through PostgreSQL catalog helpers.
Constraint checks are table-scoped through `pg_constraint`, `pg_class` and
`pg_get_constraintdef`; index checks are table-scoped and verify ordered index
definitions, uniqueness and absence of a partial predicate. A matching
constraint name on another table is not accepted.

PostgreSQL CHECK verification is semantic: status/event sets accept both
`IN (...)` and deparsed `= ANY (ARRAY[...])`, with exact literal-set equality.
Scalar, hash and compound consistency checks are verified by their structured
column/operator/literal predicates rather than raw `IN` substrings. UNIQUE
constraints use ordered catalog columns. Foreign keys use ordered source and
referenced catalog columns plus their `ON DELETE` action.

## Canonical lifecycle event vocabulary

The event CHECK explicitly allows the approved transition and audit vocabulary:

```text
request_created
retention_pending
retention_reached
pending_approval
request_approved
request_rejected
request_cancelled
blocked
unblocked_rereviewed
expired
manifest_generated
manifest_invalidated
hold_clearance_checked
hold_clearance_invalidated
legal_hold_placed
legal_hold_released
execution_started
retry_pending
manual_reconciliation
failed
completed
cancelled
rejected
```

## Upgrade order

1. Verify users/workspaces prerequisites and reject pre-existing 0007 objects.
2. Inspect and preserve the exact pre-0007 SQLite workspace schema when applicable.
3. Create `workspace_purge_requests`.
4. Create `purge_legal_holds`.
5. Create `purge_lifecycle_events`.
6. Add/rebuild `workspaces.purged_at` and `workspaces.purge_request_id`.
7. Add the workspace-to-request `RESTRICT` FK and terminal constraints.
8. Verify DDL completion; the migration loader then stamps the revision.

## Downgrade order and guards

Downgrade refuses when any request, hold, lifecycle event or terminal workspace
marker exists. It never deletes lifecycle data to make downgrade pass.

Before those data guards, the source requires a complete, unambiguous 0007 schema:
all workflow tables, terminal columns, required indexes and terminal constraints
must exist. Partial schemas are rejected rather than repaired or stamped silently.

PostgreSQL order after guards pass:

1. Drop `fk_workspaces_purge_request_id`.
2. Drop `ck_workspaces_purge_terminal_consistency`.
3. Drop `uq_workspaces_purge_request_id`.
4. Drop `ix_workspaces_purged_at`.
5. Drop `workspaces.purge_request_id`.
6. Drop `workspaces.purged_at`.
7. Drop `purge_lifecycle_events`.
8. Drop `purge_legal_holds`.
9. Drop `workspace_purge_requests`.

SQLite order after guards pass:

1. Disable foreign keys outside the transaction and begin the rebuild transaction.
2. Rebuild `workspaces` to the exact pre-0007 schema using create-new/copy/drop/rename.
3. Drop `purge_lifecycle_events`.
4. Drop `purge_legal_holds`.
5. Drop `workspace_purge_requests`.
6. Verify the pre-0007 workspace schema and named objects.
7. Run `PRAGMA foreign_key_check`.
8. Commit and restore the original foreign-key state.

The terminal workspace FK and columns are removed before the request table is
dropped. PostgreSQL and SQLite use no `CASCADE`.

## Post-DDL verification

Upgrade verifies:

- all three workflow tables exist;
- both terminal workspace columns exist;
- required indexes exist;
- required FK/UNIQUE/CHECK constraints exist;
- no temporary SQLite table remains;
- SQLite `foreign_key_check` returns zero rows.

The verification lists are canonicalized in the source and include every named
workflow index: all five request indexes, both legal-hold indexes, all four
lifecycle-event indexes, and `ix_workspaces_purged_at`. Workflow foreign keys
and their `ON DELETE` actions are verified as well. SQLite named indexes and
foreign keys are compared exactly; unknown named indexes, extra FKs, missing
FKs or changed actions fail closed. SQLite autoindexes from the unique slug
constraint are checked by origin and column, not recreated by name.

Downgrade verifies:

- all workflow tables are absent;
- terminal workspace columns are absent;
- the pre-0007 workspace columns, indexes and FKs are preserved;
- no temporary table remains;
- SQLite `foreign_key_check` returns zero rows.

## Backfill and runtime boundary

- No purge request backfill.
- No hold or lifecycle event backfill.
- No retention scheduling.
- Existing workspaces receive nullable terminal columns with `NULL` values.
- Runtime restore guards, purge service, approval routes and UI are later work and are not implemented here.

## Static review gates

- AST parse of the migration source: required.
- `git diff --check`: required.
- Migration execution: not run.
- Tests/compileall: not run by this task.
- Database/PostgreSQL/Docker/Railway: not run by this task.
- Commit/push: not performed.

## Known next review gates

1. Review the actual migration diff.
2. Review SQLite rebuild on an isolated disposable database.
3. Review PostgreSQL DDL on a disposable local rehearsal database.
4. Approve migration execution separately.
5. Only after execution/rehearsal approval, plan runtime integration behind fail-closed guards.
