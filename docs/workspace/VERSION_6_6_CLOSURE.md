# Version 6.6 — Permanent Workspace Purge Workflow

## Executive status

```text
Version 6.6 — Permanent Workspace Purge Workflow
Status: CLOSED / DONE
Closure baseline:
9ce67182e92339c722f19329a395c9029ff6d6fe
Alembic head:
0009_immediate_purge_eligibility
```

## Delivered scope

Version 6.6 delivered the persisted permanent workspace purge workflow, workspace purge requests, requester/approver/executor separation, staged review and approval states, execution feature gating, durable reauthentication and throttling, password-mutation authorization revocation, legal-hold enforcement, fail-closed purge eligibility, the immediate purge eligibility migration, PostgreSQL runtime and concurrency rehearsals, terminal workspace purge state, and workspace-scoped dashboard administration metrics.

## Permanent purge boundary

Version 6.6 permanently removes business data belonging to the approved workspace according to the current purge contract while preserving the minimum records needed for identity, audit, and lifecycle traceability:

```text
User rows are preserved.
Terminal Workspace tombstones are preserved.
ActivityLog/audit records are preserved.
Purge workflow and lifecycle audit records are preserved.
```

This closure does not claim that all PostgreSQL rows are deleted.

## Deferred work

The following work is deferred to a later version:

```text
Permanent account purge
Hard deletion of User rows
Hard deletion of terminal Workspace tombstones
Audit anonymization/deletion policy
Full UI/UX overhaul
```

## Database state

```text
Production database engine: PostgreSQL
Alembic revision: 0009_immediate_purge_eligibility
```

No credentials, hostnames, connection URLs, or secrets are part of this document.

## Validation summary

```text
Focused dashboard scope tests: PASS
Basic suite: PASS
Full suite: 772 passed, 52 skipped, 238 subtests passed
compileall: PASS
pip check: PASS
git diff --check: PASS
```

## Closure decision

```text
Version 6.6 scope is frozen at commit
9ce67182e92339c722f19329a395c9029ff6d6fe.

Further account hard-deletion or UI redesign work requires a new version/task.
```
