# Task 6.6.7c — Dedicated PostgreSQL Rehearsal Guard

## Scope

This task adds a pure, test-only guard and a skipped-by-default pytest
foundation. No database connection, SQL, migration, Docker execution, or
PostgreSQL runtime test occurred.

The exact future rehearsal database is:

```text
spamanager_purge_rehearsal_test
```

Allowed target metadata is:

```text
backend=postgresql
host=localhost or 127.0.0.1
port=5433
database=spamanager_purge_rehearsal_test
```

## Exact opt-in

All four values must be exact:

```text
APP_ENV=testing
SPAMANAGER_TEST_PROCESS=1
SPAMANAGER_ALLOW_POSTGRES_TESTS=1
SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL=1
```

Truth-like alternatives such as `true`, `yes`, and `on` are refused.

All URL query parameters are refused. Surrounding whitespace is refused rather
than normalized. If URL parsing fails, the parser cause is suppressed and only
a typed safe error is exposed.

## Refusal and isolation rules

The guard refuses SQLite, non-PostgreSQL dialects, malformed URLs, missing or
non-local hosts, non-5433 ports, empty or non-exact databases, `spamanager_dev`,
`postgres`, template databases, arbitrary `*_test` databases, and Railway or
public/private hosts.

The dedicated opt-in is separate from the generic PostgreSQL test opt-in. An
opted-in run also fails closed if `app` or `extensions` has already been loaded;
the dedicated PostgreSQL path must run in a fresh pytest process.

The fixture performs this fresh-process check before validating the target URL.

Without the exact opt-in, the foundation fixture skips before application
import, engine creation, connection, or SQL. With opt-in, the fixture returns
only safe metadata and still does not connect in Task 6.6.7c.

Credentials are never logged, returned, or included in exception messages.
Examples must use placeholders only:

```text
postgresql://<user>:<password>@localhost:5433/spamanager_purge_rehearsal_test
```

`spamanager_dev` remains protected. No Railway or production target is
accepted.

## Boundary and remaining work

Database creation remains separately authorized. PostgreSQL migration/runtime
proof, functional PostgreSQL tests, and concurrency tests are still pending
and were not run. Production purge remains unauthorized, the production
feature flag remains false, and Version 6.6 remains open.
