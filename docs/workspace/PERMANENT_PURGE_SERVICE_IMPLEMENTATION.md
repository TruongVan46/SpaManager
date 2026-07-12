# Version 6.6 — Task 6.6.4 Purge Service Implementation

## Status

This is an internal-only local implementation record under correction and
review. The service is not exposed through a route, UI, worker, scheduler, or
startup hook.

Production execution is not authorized. No production database action was
performed, and PostgreSQL runtime rehearsal was not run.

## Implementation boundary

- `models/purge.py` maps the existing workflow tables created by migration
  `0007_permanent_purge_workflow` using a separate registry/metadata.
- The existing terminal fields are accessed through the Core
  `workspace_terminal_state_table`; no second ORM mapper is used for the
  physical `workspaces` row.
- Each service invocation creates and closes its own SQLAlchemy session bound
  to the application engine. Caller-scoped `db.session` changes are not
  committed or rolled back by the service.
- The execution actor username is retained in `execution_trigger_snapshot`,
  and definite failed attempts retain `attempt_count` and `last_attempt_at`.
- `services/purge_manifest.py` receives an explicit session and locked purge
  plan. It performs no global `Model.query` access.
- `services/purge_service.py` locks request, workspace, legal holds, invoices,
  invoice details, and remaining target rows in deterministic order.
- PostgreSQL concurrency proof remains a Task 6.6.7 validation requirement.

## Data boundary

The implementation deletes only exact IDs captured in the locked target plan:

1. `invoice_details`, constrained by captured invoice-detail and invoice IDs;
2. `appointments`;
3. `invoices`;
4. `customers`;
5. `services`;
6. `settings`;
7. `workspace_members`.

Every delete retains a workspace predicate and checks the affected row count.
It preserves users, activity logs, workflow audit rows, legal-hold history,
and the terminal workspace tombstone. It does not delete filesystem assets.

## Safety boundary

- Only an active `APPROVAL_OWNER` may execute.
- Authorization is checked before a `COMPLETED` idempotent return.
- Requester and executor must be different users.
- Request type, lifecycle ID, invalidation fields, idempotency key, outcome
  state, status, time input, workspace and provenance must pass fail-closed
  gates.
- Request status must be `APPROVED` for a new execution.
- Retention must be reached.
- Existing legal holds are locked in deterministic ID order; any unresolved,
  malformed, unknown, or unavailable hold blocks execution.
- Stored manifest text/hash is validated, rebuilt from the locked plan, and
  compared exactly. No silent refresh is permitted.
- Any workspace logo reference blocks execution.
- A definite runtime failure after execution starts rolls back the dedicated
  main session and records `FAILED` through a guarded separate audit session;
  only the expected pre-commit `APPROVED` state may transition to `FAILED`.
- Commit exceptions are treated as outcome-unknown until a fresh locked
  reconciliation proves the request completed. Completion requires matching
  `completed_at`, terminal `purged_at`, and the execution-attempt timestamp,
  plus matching workspace provenance. Rollback cleanup errors do not convert
  uncertainty into `FAILED`; an inconsistent `COMPLETED` state is marked
  `outcome_unknown` and never overwritten with `FAILED`.
- `outcome_unknown` blocks automatic retry until manual reconciliation.
- Completed requests are idempotent no-ops only when terminal state is
  consistent and the executor is authorized.

## Explicit non-goals

- No public route.
- No UI.
- No worker or scheduler.
- No startup execution.
- No filesystem cleanup.
- No new migration.
- No production purge.

Expanded all-table tenant and PostgreSQL concurrency coverage remains a
Task 6.6.6/6.6.7 requirement. Production execution is not authorized.
Task 6.6.5–6.6.9 are not complete. Task 6.6.4 is not marked DONE until
review and commit approval are complete. Version 6.6 is not closed.
