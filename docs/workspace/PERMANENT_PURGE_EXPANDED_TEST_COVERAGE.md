# Task 6.6.6 — Expanded Purge Workflow Test Coverage

## Boundary

Task 6.6.6 is test-only. It expands authorization, feature-flag, CSRF, request,
approval, reject/cancel, restore-invalidation, manifest, lifecycle-event, route,
and staged-UI coverage without changing runtime behavior.

Production purge remains unauthorized. `PERMANENT_PURGE_UI_ENABLED` must remain
false in production. There is still no execute, confirm, retry, reconcile, or
refresh-manifest route. Version 6.6 is not closed by this task.

## Baseline and added coverage

The read-only discovery baseline collected 57 tests across the five purge-focused
test modules. This implementation adds the following test contracts:

### Authorization and feature flag

- `test_invalid_approval_owner_states_block_all_request_mutations`
- `test_feature_flag_parser_and_runtime_guard_are_strict`
- `test_disabled_flag_blocks_every_purge_endpoint_before_service`
- `test_navigation_and_account_actions_use_strict_boolean_template_guards`
- `test_all_purge_post_routes_require_auth_and_authenticated_csrf`

These cover invalid Approval Owner states, strict environment parsing versus
strict runtime boolean configuration, all staged purge endpoints, and CSRF/auth
ordering. Disabled routes are asserted to return 404 without invoking workflow
service methods.

### Request, approval, reject, and cancel

- `test_request_guards_fail_closed_and_roll_back_manifest_or_event_failure`
- `test_approval_event_sequence_is_complete_and_unique`
- `test_reject_and_cancel_normalize_reason_and_are_idempotent`

The tests assert no request/event mutation on guard or build failures, terminal
marker rejection, complete approval event order, actor snapshots, reason
truncation/defaulting, and no duplicate reject/cancel events.

### Restore and manifest/UI contracts

- `test_restore_invalidation_helper_mutates_only_invalidatable_statuses`
- `test_restore_owner_workspace_blocks_matching_terminal_and_unknown_outcomes`
- `test_staged_templates_render_csrf_labels_and_no_execution_controls`

The direct invalidation helper matrix only tests which statuses the helper
mutates; it does not decide whether restore may continue. The end-to-end
`UserService.restore_owner_workspace` test covers `EXECUTING`, `COMPLETED`,
`outcome_unknown`, and terminal markers. The database CHECK constraint prevents
creating an arbitrary unknown status, so that case is not claimed.
Template assertions require CSRF fields, labels, non-prefilled confirmation
input, alert semantics, and no execution controls.

The existing mixed-provenance, already-invalidated, manifest, reconciliation,
and owner/workspace lifecycle tests remain in place.

## SQLite validation boundary

SQLite validates service state transitions, no-mutation failure behavior,
manifest validation, event sequence, route guards, HTML/static contracts, and
feature-flag behavior.

SQLite does **not** prove PostgreSQL row-lock or concurrency behavior. The
following remain deferred to Task 6.6.7:

- real PostgreSQL `FOR UPDATE` behavior;
- concurrent request creation;
- concurrent approval;
- restore-versus-execute lock ordering/deadlock behavior;
- isolation level and lock timeout behavior;
- real commit uncertainty under PostgreSQL;
- PostgreSQL query-plan/runtime evidence.

Browser/mobile rendering is not run in this task and no browser framework is
added. Mobile/accessibility assertions are limited to rendered/static template
contracts.

## Validation record

Focused command:

```text
.\venv\Scripts\python.exe -m pytest -q tests/test_purge_manifest.py tests/test_purge_service.py tests/test_purge_request_service.py tests/test_approval_purge_routes.py tests/test_owner_workspace_lifecycle_security.py
```

Result:

```text
68 passed, 52 warnings, 95 subtests passed
```

Full suite result: `436 passed, 1567 warnings, 186 subtests passed in 137.04s`.
Compileall, pip check, diff check, Excel status, and final Git state are
recorded in the Task 6.6.6 handoff report.

## Explicit exclusions

- No migration was created or changed.
- No production, Railway, Docker, or PostgreSQL action was performed.
- No purge execution was called.
- No worker, scheduler, startup hook, or execute route was added.
- No Excel template or runtime artifact belongs to this task.

## Roadmap status

```text
TASK 6.6.6 EXPANDED TEST COVERAGE: IMPLEMENTED LOCALLY
TASK 6.6.7 POSTGRESQL CONCURRENCY/RUNTIME PROOF: NOT STARTED
VERSION 6.6: NOT CLOSED
```
