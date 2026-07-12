# Version 6.6 — Task 6.6.5 Staged Purge UX Implementation

## Boundary

Task 6.6.5 adds a feature-flagged Approval Portal workflow for creating,
reviewing, approving, rejecting and cancelling workspace purge requests.
Only active `APPROVAL_OWNER` actors may access the workflow. The flag is
`PERMANENT_PURGE_UI_ENABLED`, defaults to false, and malformed or missing
values remain false. No production environment is enabled by this change.

## Contract

- Request phrase: `REQUEST PURGE <workspace-slug>`.
- Approval phrase: `APPROVE PURGE <workspace-slug> <lifecycle-id>`.
- Phrases are server-checked, case-sensitive, and only outer whitespace is stripped.
- The manifest is generated once at request creation and is never silently refreshed.
- Approval rebuilds and compares the exact stored manifest; drift fails closed.
- A request in `PENDING_RETENTION` is promoted atomically to `PENDING_APPROVAL`
  at the eligible boundary, with one `retention_reached` and one
  `pending_approval` event before approval continues.
- Duplicate requests for the same `(workspace_id, target_deleted_at)` lifecycle are rejected.
- Requester cannot approve or reject their own request; only the requester can cancel before approval.
- Restore invalidates matching non-terminal requests in the same database transaction.
- Restore preflight locks matching requests first, then workspace and terminal
  rows, rechecks provenance and terminal markers, and only then clears deletion
  fields. Any invalidation/event failure rolls back the restore.
- FAILED and `outcome_unknown` requests are read-only.
- Read-only list/detail parsing validates manifest version, hash and safe shape;
  malformed manifests show a safe warning and cannot be approved.
- Logo references must be empty; filesystem files are never deleted.

## Routes and UI

Implemented routes are the list, detail, request, approve, reject and cancel
routes under `/approval`. All mutations are POST requests protected by the
existing global CSRF hook and use POST/Redirect/GET. There is no confirmation
execution route and no execute route. Approved requests display:
`Execution is not available in Task 6.6.5.`

The list and detail pages provide a responsive Bootstrap table and explicit
warnings, safe manifest counts/hash, legal-hold state and
read-only terminal-state messages. Raw manifest JSON, SQL, secrets, paths and
business records are not rendered.

Mobile card expansion for the purge request list belongs to Task 6.6.6.

## Explicit non-goals

This task does not add a migration, worker, scheduler, startup hook, strong
re-authentication, Google re-authentication or production purge execution.
The internal execution service remains unexposed.

## Follow-up boundary

- Task 6.6.6: expanded route, authorization, CSRF, concurrency and browser/mobile coverage.
- Task 6.6.7: PostgreSQL locking and runtime rehearsal evidence.
- Task 6.6.8 and 6.6.9 remain not started.
- Version 6.6 is not closed by this task.
