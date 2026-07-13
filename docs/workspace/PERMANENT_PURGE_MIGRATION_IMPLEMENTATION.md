# Version 6.6 - Task 6.6.3b2c
# Permanent Purge Migration Implementation Record

## Status

```text
MIGRATION SOURCE REHEARSAL VERIFIED
SQLITE PASS
POSTGRESQL PASS
TEST SUITE PASS
COMPILEALL PASS
LOCAL TEST DEPENDENCY CONTRACT ADDED
READY FOR SOURCE COMMIT
PRODUCTION MIGRATION APPLIED — RAILWAY PRE-DEPLOY PASS
PRODUCTION PURGE RUNTIME NOT IMPLEMENTED
VERSION 6.6 NOT CLOSED
```

This record documents a workflow/schema foundation migration. It also records
the later owner-confirmed production deployment outcome. It is not a closure
of the full Version 6.6 roadmap.

## Scope and authorization

- Base revision: `0006_user_ws_soft_delete`.
- Provisional revision: `0007_permanent_purge_workflow`.
- No purge request, hold, lifecycle event or schedule is created by the migration.
- No business rows, business FKs, slug values, InvoiceDetail ORM mapping or runtime code are changed.
- No model, route, service, UI or test changes are included.
- No production database, Railway, production migration or deployment command
  was run during the local implementation and rehearsal work recorded here.

Task 6.6.3b2c records the completed disposable SQLite and PostgreSQL
rehearsals. The later production deployment outcome is recorded below without
rewriting the historical pre-deployment approval state.

## Production rollback evidence contract

The read-only production evidence contract remains:

```text
Production revision: 0006_user_ws_soft_delete
Production workspaces baseline FKs:

created_by_id -> users.id
ON DELETE SET NULL

deleted_by_id -> users.id
ON DELETE SET NULL

No workflow tables.
No purged_at.
No purge_request_id.
Failed migration transaction rolled back cleanly.
```

The production-shaped baseline is valid historical schema evidence, not a
claim that production is corrupt or requires manual repair. No production FK
was altered manually.

## Production deployment outcome — 2026-07-11

The following production evidence was confirmed by the Owner and reviewed by
the coordinator after the history-aware correction was committed:

- Deployment commit:
  `965dc83bd1d685b9a811b2b22a195f18d323730b`
- Railway deployment: `ACTIVE / SUCCESS`
- Railway pre-deploy command:
  `python -m flask --app app db upgrade`
- Railway pre-deploy result: `PASS`
- Production revision: `0007_permanent_purge_workflow`

Production contains the three workflow tables:

- `workspace_purge_requests`
- `purge_legal_holds`
- `purge_lifecycle_events`

The `workspaces` table contains the terminal columns:

- `purged_at`
- `purge_request_id`

The history-aware verifier preserved the exact pre-upgrade workspace FK
multiset and added exactly one new FK:

`purge_request_id -> workspace_purge_requests.id ON DELETE RESTRICT`

The verified workspace FK baselines were:

- Fresh rebuild baseline:
  - `created_by_id -> users.id ON DELETE NO ACTION`
  - `deleted_by_id -> users.id ON DELETE SET NULL`
- Historical production-shaped baseline:
  - `created_by_id -> users.id ON DELETE SET NULL`
  - `deleted_by_id -> users.id ON DELETE SET NULL`

The historical production FK baseline was preserved. No production FK was
altered manually to force the migration to pass.

The two earlier Railway deployments failed safe and rolled back cleanly to
revision `0006_user_ws_soft_delete`. After each failure, the workflow tables
and terminal workspace columns were absent. The final root cause was
historical production-versus-fresh-rebuild FK divergence, not production
schema corruption.

Owner-confirmed production smoke passed for the login page, login flow and
dashboard, with no observed runtime regression. The controlled workspace
observation also confirmed that each tested workspace saw only its own Recycle
Bin tombstones. Soft-delete behavior, workspace-scoped Recycle Bin behavior
and Activity Log history remained intact. Permanent business deletion remains
disabled.

This migration provides only the permanent-purge schema and workflow
foundation. It does not implement:

- a purge worker;
- a runtime purge executor;
- automatic hard deletion;
- permanent deletion of `Customer`;
- permanent deletion of `Service`;
- permanent deletion of `Appointment`;
- permanent deletion of `Invoice`.

The root workspace is not hard-deleted by this migration, and legal-hold
behavior remains fail-closed.

This section records the production outcome of the migration/schema foundation
only. It does not declare the full Version 6.6 roadmap complete, and it does
not start or close roadmap Task 6.6.9.

## Final rehearsal result

SQLite and PostgreSQL both passed the controlled sequence:

```text
0006_user_ws_soft_delete
-> 0007_permanent_purge_workflow
-> 0006_user_ws_soft_delete
```

SQLite evidence confirms exact workspace schema preservation, workflow
UNIQUE/CHECK/FK/index verification, legal-hold CHECK verification, sentinel
preservation, zero `foreign_key_check` violations, controlled downgrade and
stamp.

PostgreSQL evidence confirms fresh and historical production-shaped local
Docker PostgreSQL 16 `_test` databases under `TestingConfig`, exact workspace
and workflow contracts, exactly three workspace FKs, exactly eight
`workspace_purge_requests` FKs, sentinel preservation, controlled downgrade
and stamp, restored revision 0006, and independent cleanup verification. Both
fresh disposable databases were dropped; older failure databases and SQLite
evidence artifacts were preserved outside the repository.

The migration source corrections verified by these rehearsals are:

- SQLite workspace signatures match the actual 0006 schema.
- SQLite CHECK matching canonicalizes only whitespace inside parentheses.
- PostgreSQL FK comparison canonical-sorts actual signatures while retaining
  duplicate detection. The `workspaces` baseline is captured before 0007 DDL
  and the verifier expects that exact FK multiset plus only the new
  `purge_request_id -> workspace_purge_requests.id` `RESTRICT` FK.
- This preserves both valid 0006 histories: a fresh baseline with
  `created_by_id -> users.id` `NO ACTION` and a historical production-shaped
  baseline with `created_by_id -> users.id` `SET NULL`; in both cases
  `deleted_by_id -> users.id` remains `SET NULL`.

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

The actual revision-0006 SQLite workspace schema was captured from the disposable
rehearsal database. Its canonical contract is `DATETIME` for all datetime
columns, no database defaults for status or timestamps, `id INTEGER NOT NULL`
with table-level `PRIMARY KEY (id)`, `created_by_id -> users.id ON DELETE NO
ACTION`, and `deleted_by_id -> users.id ON DELETE SET NULL`. The `slug`
uniqueness contract is the named unique index `ix_workspaces_slug` (origin `c`),
not a table `UNIQUE` clause or SQLite autoindex.

The revised SQLite rebuild reproduces that actual contract and adds only
`purged_at DATETIME`, `purge_request_id INTEGER`, the terminal UNIQUE/CHECK/FK
objects and `ix_workspaces_purged_at` for 0007. Downgrade restores the captured
0006 contract exactly.

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

SQLite CHECK verification uses a SQLite-specific whitespace normalization step
that canonicalizes whitespace immediately inside parentheses. This prevents a
formatting-only false-negative such as `CHECK ( (` versus `CHECK ((` without
changing the CHECK DDL or relaxing predicate, branch, literal, `AND`, or `OR`
semantics. A pure-Python self-check rejects changed constraint names, operators,
nullability predicates, and missing branches.

The deterministic `PRAGMA index_xinfo` tuple is:

```text
(seqno, cid, name, desc, collation, key)
```

Auxiliary `key=0` entries are retained but excluded from the ordered indexed-key
column list. Static import self-checks validate representative workspace index
metadata, the SQLite CHECK whitespace normalizer, the PostgreSQL CHECK normalizer,
and canonical PostgreSQL FK ordering without opening a database.

The first PostgreSQL disposable rehearsal created eight correct foreign keys on
`workspace_purge_requests`, but PostgreSQL catalog OID order differed from the
lexicographically sorted expected tuple. The verifier now canonical-sorts both
actual and expected signatures while preserving duplicate detection.

The history-aware correction captures the two existing workspace foreign keys
from the 0006 schema before 0007 creates any object. The expected `workspaces`
map is that captured multiset plus exactly one new `purge_request_id`
`RESTRICT` key, so neither legacy action is hardcoded or changed. Downgrade
removes exactly one occurrence of the new key and verifies the captured
baseline, preserving duplicate and action semantics.

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

## Final validation gates

- AST parse of the migration source: PASS.
- Static import self-check: PASS.
- Secret/path scan: PASS; no password, full PostgreSQL URL, machine path,
  password hash or production identifier is recorded here.
- Canonical pytest suite: PASS (`379 passed`, `91 subtests passed`).
- Compileall: PASS.
- At the time of the original local implementation report, commit/push had not
  yet been performed.

The later correction commit was:
`965dc83bd1d685b9a811b2b22a195f18d323730b`.

The owner-confirmed Railway deployment ran the production migration
successfully. Permanent business-data purge execution is not implemented by
this migration.

## Task 6.6.8d3b schema-only amendment

Task 6.6.8d3b adds the separately approved linear revision
`0008_durable_purge_reauth_state`, down revision
`0007_permanent_purge_workflow`. This amendment creates exactly two new empty
tables:

- `workspace_purge_execution_authorizations`: one current request-wide
  authorization row with generation identity, explicit state machine, nonce
  hash only, and nullable unique association to the existing
  `execution_started` lifecycle event;
- `workspace_purge_reauth_actor_throttles`: one actor-global durable throttle
  row per user.

Neither table duplicates `workspace_id`. Workspace identity remains derived
from the authoritative purge request. Both tables use restricted foreign keys,
portable named checks, and guarded empty-table downgrade. No existing table,
lifecycle event type, ActivityLog schema, authentication-session table, or
runtime field was changed.

The ORM additions are schema-only. Password verification, nonce issuance or
transport, authorization claiming, routes, and purge-service integration remain
follow-up work. The dedicated local PostgreSQL migration rehearsal is required
before coordinator review; production migration and production purge remain
unauthorized.

## Remaining runtime approval gates

1. Keep permanent purge execution disabled until the remaining Version 6.6
   roadmap tasks are separately completed, reviewed and approved.
2. Implement any future runtime integration behind fail-closed guards and
   explicit production approval.

## Pre-commit validation result

The tracked development dependency contract provides `pytest==9.1.1`.
The canonical suite passed with `379 passed`, `91 subtests passed`, and `1559
warnings` in 119.73 seconds. The three stale contracts were corrected without
changing runtime or migration source behavior: migration tests now discover the
canonical head, assert the 0007 workflow schema, and the config isolation test
clears inherited pytest/test database environment state before checking
`DevelopmentConfig`. Compileall passed over the application, migration, model,
route, service and test source trees.
