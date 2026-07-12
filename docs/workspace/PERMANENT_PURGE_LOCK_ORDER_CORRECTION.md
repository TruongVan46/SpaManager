# Permanent Purge Lock-Order Correction

## Scope

This document records the source-level correction for Task 6.6.7b. It does not
claim that the deadlock was reproduced against PostgreSQL.

## Confirmed original cycle

The create path originally acquired locks in this order:

```text
workspace -> terminal -> existing lifecycle request
```

Approval, execution, and restore acquire the relevant rows in the opposite
request-first order:

```text
request -> workspace -> terminal
```

Therefore create versus execute, create versus approve, and create versus
restore had a credible request/workspace lock cycle at source level.

## Minimal correction

The workspace row remains the create serialization anchor and is still locked
first. The existing lifecycle lookup is now deliberately a plain, non-locking
SELECT. The unique constraint on `(workspace_id, target_deleted_at)` remains
the final duplicate protection, and the existing `IntegrityError` mapping is
unchanged.

Approval, execution, and restore retain their request -> workspace -> terminal
order. No advisory lock, table lock, raw SQL lock, sleep, or retry loop was
added. Manifest, retention, legal-hold, logo, terminal, commit, and rollback
policy are unchanged.

## Validation boundary

This is a source-level lock-order correction only. No PostgreSQL runtime proof
has been performed yet. The exact dedicated PostgreSQL rehearsal database guard
is still pending. Task 6.6.7 PostgreSQL rehearsal remains blocked until that
guard is implemented and reviewed.

Production purge remains unauthorized, the production feature flag remains
false, and Version 6.6 remains open. This correction does not make Task 6.6.7
complete.
