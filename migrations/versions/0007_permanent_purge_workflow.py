"""Create the workflow-only permanent workspace purge schema.

This migration is intentionally static in Task 6.6.3a. It does not create
requests, holds, events, schedules, or purge any business data.
"""

import re

from sqlalchemy import text


revision = "0007_permanent_purge_workflow"
down_revision = "0006_user_ws_soft_delete"
branch_labels = None
depends_on = None
message = "Add permanent workspace purge workflow schema"

_WORKSPACE_PURGE_REQUEST_FK_SIGNATURE = (
    "workspace_purge_requests",
    ("purge_request_id",),
    ("id",),
    "RESTRICT",
)


REQUEST_STATUSES = (
    "REQUESTED",
    "PENDING_RETENTION",
    "PENDING_APPROVAL",
    "APPROVED",
    "EXECUTING",
    "RETRY_PENDING",
    "BLOCKED",
    "COMPLETED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "FAILED",
)
HOLD_STATUSES = ("ACTIVE", "RELEASED")
HOLD_CHECK_STATUSES = ("UNKNOWN", "CLEAR", "BLOCKED", "UNAVAILABLE", "STALE")
EVENT_TYPES = (
    "request_created",
    "retention_pending",
    "retention_reached",
    "pending_approval",
    "request_approved",
    "request_rejected",
    "request_cancelled",
    "blocked",
    "unblocked_rereviewed",
    "expired",
    "manifest_generated",
    "manifest_invalidated",
    "hold_clearance_checked",
    "legal_hold_placed",
    "legal_hold_released",
    "hold_clearance_invalidated",
    "execution_started",
    "retry_pending",
    "manual_reconciliation",
    "failed",
    "completed",
    "cancelled",
    "rejected",
)

WORKSPACE_BASE_COLUMNS = (
    "id", "name", "slug", "status", "created_by_id", "notes",
    "created_at", "updated_at", "deleted_at", "deleted_by_id", "deletion_reason",
)
WORKSPACE_BASE_INDEXES = (
    "ix_workspaces_slug",
    "ix_workspaces_status",
    "ix_workspaces_created_at",
    "ix_workspaces_created_by_id",
)
REQUEST_INDEXES = (
    "ix_workspace_purge_requests_workspace_id",
    "ix_workspace_purge_requests_status_eligible_at",
    "ix_workspace_purge_requests_workspace_status",
    "ix_workspace_purge_requests_status_retry_eligible_at",
    "ix_workspace_purge_requests_hold_check_status",
)
HOLD_INDEXES = (
    "ix_purge_legal_holds_workspace_status",
    "ix_purge_legal_holds_status_type",
)
EVENT_INDEXES = (
    "ix_purge_lifecycle_events_request_event_at",
    "ix_purge_lifecycle_events_workspace_event_at",
    "ix_purge_lifecycle_events_lifecycle_id",
    "ix_purge_lifecycle_events_event_type",
)


def _workspace_column_signature(include_terminal_columns):
    signature = [
        ("id", "INTEGER", 1, None, 1, 0),
        ("name", "VARCHAR(150)", 1, None, 0, 0),
        ("slug", "VARCHAR(150)", 1, None, 0, 0),
        ("status", "VARCHAR(20)", 1, None, 0, 0),
        ("created_by_id", "INTEGER", 0, None, 0, 0),
        ("notes", "TEXT", 0, None, 0, 0),
        ("created_at", "DATETIME", 1, None, 0, 0),
        ("updated_at", "DATETIME", 1, None, 0, 0),
        ("deleted_at", "DATETIME", 0, None, 0, 0),
        ("deleted_by_id", "INTEGER", 0, None, 0, 0),
        ("deletion_reason", "VARCHAR(255)", 0, None, 0, 0),
    ]
    if include_terminal_columns:
        signature.extend([
            ("purged_at", "DATETIME", 0, None, 0, 0),
            ("purge_request_id", "INTEGER", 0, None, 0, 0),
        ])
    return tuple(signature)


def _normalize_sql_fragment(value):
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split()).upper()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return normalized


def _normalize_sqlite_check_fragment(value):
    normalized = _normalize_sql_fragment(value)
    if normalized is None:
        return None
    normalized = re.sub(r"\(\s+", "(", normalized)
    normalized = re.sub(r"\s+\)", ")", normalized)
    return normalized


def _validate_static_sqlite_check_normalizer():
    actual = """
    CONSTRAINT ck_purge_legal_holds_release_fields CHECK (
        (status = 'ACTIVE' AND released_at IS NULL)
        OR
        (status = 'RELEASED' AND released_at IS NOT NULL)
    )
    """
    expected = """
    CONSTRAINT ck_purge_legal_holds_release_fields CHECK (
    (status = 'ACTIVE' AND released_at IS NULL)
    OR
    (status = 'RELEASED' AND released_at IS NOT NULL)
    )
    """
    normalized_actual = _normalize_sqlite_check_fragment(actual)
    normalized_expected = _normalize_sqlite_check_fragment(expected)
    if normalized_actual != normalized_expected:
        raise RuntimeError("0007 SQLite CHECK normalizer whitespace self-check failed.")
    for invalid in (
        expected.replace("ck_purge_legal_holds_release_fields", "ck_other_constraint"),
        expected.replace("OR", "AND"),
        expected.replace("IS NOT NULL", "IS NULL"),
        expected.replace("OR\n    (status = 'RELEASED' AND released_at IS NOT NULL)", ""),
    ):
        if _normalize_sqlite_check_fragment(invalid) == normalized_expected:
            raise RuntimeError("0007 SQLite CHECK normalizer semantic self-check failed.")
    return True


_STATIC_SQLITE_CHECK_NORMALIZER_VALID = _validate_static_sqlite_check_normalizer()


def _normalize_postgres_check_text(value):
    normalized = _normalize_sql_fragment(value)
    cast_pattern = (
        r"::(?:text|varchar(?:\(\d+\))?|character\s+varying(?:\(\d+\))?|"
        r"integer|bigint|boolean|timestamp(?:\s+(?:without|with)\s+time\s+zone)?)(?:\[\])?"
    )
    normalized = re.sub(cast_pattern, "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\(([A-Z_][A-Z0-9_]*)\)", r"\1", normalized)
    normalized = re.sub(r"\('([^']*)'\)", r"'\1'", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _postgres_status_set_signature(definition, column_name):
    normalized = _normalize_postgres_check_text(definition)
    if column_name.upper() not in normalized or (" IN " not in normalized and " ANY " not in normalized):
        return None
    literals = tuple(sorted(item.replace("''", "'") for item in re.findall(r"'((?:''|[^'])*)'", normalized)))
    return (column_name, literals)


def _postgres_scalar_check_signature(definition, column_name):
    normalized = _normalize_postgres_check_text(definition)
    match = re.search(rf"\b{re.escape(column_name.upper())}\b\s*(>=|>|=)\s*\(?\s*('?[-A-Z0-9_]+'?|[-0-9]+)", normalized)
    if not match:
        return None
    literal = match.group(2).strip("'").upper()
    return (column_name, match.group(1), literal)


def _assert_postgres_check_semantics(connection, table_name, constraint_name, kind, expected):
    definition = _postgres_constraint_definition(connection, table_name, constraint_name)
    if definition is None or definition[0] != "c":
        raise RuntimeError(f"0007 PostgreSQL CHECK missing or wrongly scoped: {table_name}.{constraint_name}")
    normalized = _normalize_postgres_check_text(definition[1])
    if kind == "status_set":
        actual = _postgres_status_set_signature(definition[1], expected[0])
        if actual is None or actual[1] != tuple(sorted(item.upper() for item in expected[1])):
            raise RuntimeError(f"0007 PostgreSQL CHECK literal set mismatch: {table_name}.{constraint_name}")
    elif kind == "scalar":
        actual = _postgres_scalar_check_signature(definition[1], expected[0])
        if actual != (expected[0], expected[1], str(expected[2]).upper()):
            raise RuntimeError(f"0007 PostgreSQL CHECK scalar semantics mismatch: {table_name}.{constraint_name}")
    elif kind == "hash":
        if not all(fragment in normalized for fragment in (
            expected[0].upper() + " IS NULL",
            expected[0].upper() + " ~",
            "OR",
            "^[0-9A-F]{64}$",
        )):
            raise RuntimeError(f"0007 PostgreSQL CHECK hash semantics mismatch: {table_name}.{constraint_name}")
    elif kind == "predicates":
        predicates = tuple(_normalize_postgres_check_text(fragment) for fragment in expected)
        split_points = [match.start() for match in re.finditer(r"\sOR\s", normalized)]
        valid_split = False
        midpoint = len(predicates) // 2
        for split_point in split_points:
            left, right = normalized[:split_point], normalized[split_point:]
            left_ok = all(fragment in left for fragment in predicates[:midpoint])
            right_ok = all(fragment in right for fragment in predicates[midpoint:])
            if left_ok and right_ok and (midpoint <= 1 or " AND " in left) and (len(predicates) - midpoint <= 1 or " AND " in right):
                valid_split = True
                break
        if not valid_split:
            raise RuntimeError(f"0007 PostgreSQL CHECK compound semantics mismatch: {table_name}.{constraint_name}")


def _validate_static_postgres_check_normalizer():
    scalar = _postgres_scalar_check_signature(
        "CHECK (((purge_type)::text = 'workspace'::text))", "purge_type"
    )
    if scalar != ("purge_type", "=", "WORKSPACE"):
        raise RuntimeError("0007 PostgreSQL scalar CHECK normalizer self-check failed.")
    status = _postgres_status_set_signature(
        "CHECK ((status)::text = ANY (ARRAY['REQUESTED'::character varying, 'FAILED'::character varying]::text[]))",
        "status",
    )
    if status != ("status", ("FAILED", "REQUESTED")):
        raise RuntimeError("0007 PostgreSQL ANY-array CHECK normalizer self-check failed.")
    completed = _normalize_postgres_check_text(
        "CHECK (((status)::text <> 'COMPLETED'::text) OR completed_at IS NOT NULL)"
    )
    if not all(fragment in completed for fragment in ("STATUS <> 'COMPLETED'", "COMPLETED_AT IS NOT NULL", "OR")):
        raise RuntimeError("0007 PostgreSQL compound CHECK normalizer self-check failed.")
    hashed = _normalize_postgres_check_text(
        "CHECK (manifest_hash IS NULL OR (manifest_hash)::text ~ '^[0-9a-f]{64}$'::text)"
    )
    if not all(fragment in hashed for fragment in ("MANIFEST_HASH IS NULL", "MANIFEST_HASH ~", "^[0-9A-F]{64}$", "OR")):
        raise RuntimeError("0007 PostgreSQL hash CHECK normalizer self-check failed.")
    return True


_STATIC_PG_CHECK_NORMALIZER_VALID = _validate_static_postgres_check_normalizer()


def _validate_static_postgres_fk_ordering():
    fresh_baseline = (
        ("users", ("created_by_id",), ("id",), "NO ACTION"),
        ("users", ("deleted_by_id",), ("id",), "SET NULL"),
    )
    historical_baseline = (
        ("users", ("created_by_id",), ("id",), "SET NULL"),
        ("users", ("deleted_by_id",), ("id",), "SET NULL"),
    )
    for baseline in (fresh_baseline, historical_baseline):
        actual = baseline + (_WORKSPACE_PURGE_REQUEST_FK_SIGNATURE,)
        expected = baseline + (_WORKSPACE_PURGE_REQUEST_FK_SIGNATURE,)
        if tuple(sorted(actual)) != tuple(sorted(expected)):
            raise RuntimeError("0007 PostgreSQL FK ordering self-check failed.")
        invalid_cases = tuple(
            tuple(item for item in actual if item != omitted)
            for omitted in actual
        ) + (
            actual + (("users", ("approved_by_id",), ("id",), "SET NULL"),),
            tuple(
                ("users", ("created_by_id",), ("id",), "CASCADE")
                if item == baseline[0]
                else item
                for item in actual
            ),
            tuple(item for item in actual if item != _WORKSPACE_PURGE_REQUEST_FK_SIGNATURE),
            actual + (_WORKSPACE_PURGE_REQUEST_FK_SIGNATURE,),
        )
        for invalid in invalid_cases:
            if tuple(sorted(invalid)) == tuple(sorted(expected)):
                raise RuntimeError("0007 PostgreSQL FK ordering semantic self-check failed.")
    return True


_STATIC_POSTGRES_FK_ORDERING_VALID = _validate_static_postgres_fk_ordering()


def _sqlite_column_signature(connection, table_name):
    rows = connection.execute(text(f"PRAGMA table_xinfo({table_name})")).fetchall()
    return tuple(
        (
            row[1],
            _normalize_sql_fragment(row[2]),
            int(row[3]),
            _normalize_sql_fragment(row[4]),
            int(row[5]),
            int(row[6]) if len(row) > 6 else 0,
        )
        for row in rows
    )


def _sqlite_index_signature(connection, table_name, index_name):
    row = next(
        (item for item in connection.execute(text(f"PRAGMA index_list({table_name})")).fetchall() if item[1] == index_name),
        None,
    )
    if row is None:
        return None
    keys = []
    for item in connection.execute(text(f"PRAGMA index_xinfo({index_name})")).fetchall():
        if len(item) >= 6:
            keys.append((int(item[0]), int(item[1]), item[2], int(item[3]), str(item[4]).upper(), int(item[5])))
    return (table_name, int(row[2]), row[3], int(row[4]), tuple(keys))


def _sqlite_named_index_signatures(connection, table_name):
    return {
        row[1]: _sqlite_index_signature(connection, table_name, row[1])
        for row in connection.execute(text(f"PRAGMA index_list({table_name})")).fetchall()
        if not row[1].startswith("sqlite_autoindex_")
    }


def _assert_sqlite_index(connection, table_name, index_name, columns, unique=False):
    signature = _sqlite_index_signature(connection, table_name, index_name)
    if signature is None or signature[1] != int(unique) or signature[2] != "c" or signature[3] != 0:
        raise RuntimeError(f"0007 SQLite index missing or wrongly defined: {table_name}.{index_name}")
    key_columns = [item[2] for item in signature[4] if item[5] == 1]
    if any(item[3] != 0 or item[4] != "BINARY" or item[1] < 0 for item in signature[4] if item[5] == 1):
        raise RuntimeError(f"0007 SQLite index metadata is not a plain ascending BINARY key: {table_name}.{index_name}")
    if key_columns != list(columns):
        raise RuntimeError(f"0007 SQLite index column definition mismatch: {table_name}.{index_name}")


def _expected_workspace_index_signatures(include_terminal_columns):
    auxiliary_row = (1, -1, None, 0, "BINARY", 0)
    signatures = {
        "ix_workspaces_slug": ("workspaces", 1, "c", 0, ((0, 2, "slug", 0, "BINARY", 1), auxiliary_row)),
        "ix_workspaces_status": ("workspaces", 0, "c", 0, ((0, 3, "status", 0, "BINARY", 1), auxiliary_row)),
        "ix_workspaces_created_at": ("workspaces", 0, "c", 0, ((0, 6, "created_at", 0, "BINARY", 1), auxiliary_row)),
        "ix_workspaces_created_by_id": ("workspaces", 0, "c", 0, ((0, 4, "created_by_id", 0, "BINARY", 1), auxiliary_row)),
    }
    if include_terminal_columns:
        signatures["ix_workspaces_purged_at"] = ("workspaces", 0, "c", 0, ((0, 11, "purged_at", 0, "BINARY", 1), auxiliary_row))
    return signatures


def _validate_static_workspace_index_signatures():
    column_ids = {"slug": 2, "status": 3, "created_at": 6, "created_by_id": 4, "purged_at": 11}
    seen_names = set()
    seen_keys = set()
    for include_terminal_columns in (False, True):
        for name, signature in _expected_workspace_index_signatures(include_terminal_columns).items():
            if name in seen_names:
                continue
            seen_names.add(name)
            keys = tuple(item for item in signature[4] if item[5] == 1)
            if len(keys) != 1 or len(keys[0]) != 6:
                raise RuntimeError(f"0007 static index signature arity invalid: {name}")
            seqno, cid, column_name, desc, collation, key = keys[0]
            if seqno != 0 or desc != 0 or collation != "BINARY" or key != 1 or cid < 0:
                raise RuntimeError(f"0007 static index signature metadata invalid: {name}")
            if column_ids.get(column_name) != cid:
                raise RuntimeError(f"0007 static index signature cid mismatch: {name}")
            definition = (signature[0], signature[1], signature[2], signature[3], signature[4])
            if definition in seen_keys:
                raise RuntimeError(f"0007 duplicate static index definition: {name}")
            seen_keys.add(definition)
    return True


_STATIC_INDEX_SIGNATURES_VALID = _validate_static_workspace_index_signatures()


def _is_pg(connection):
    return connection.dialect.name == "postgresql"


def _has_table(connection, table_name):
    if _is_pg(connection):
        row = connection.execute(
            text(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = CURRENT_SCHEMA() AND table_name = :name
                LIMIT 1
                """
            ),
            {"name": table_name},
        ).fetchone()
    else:
        row = connection.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name LIMIT 1"),
            {"name": table_name},
        ).fetchone()
    return row is not None


def _columns(connection, table_name):
    if _is_pg(connection):
        rows = connection.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = CURRENT_SCHEMA() AND table_name = :name
                """
            ),
            {"name": table_name},
        ).fetchall()
        return {row[0] for row in rows}
    return {
        row[1]
        for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    }


def _has_column(connection, table_name, column_name):
    return _has_table(connection, table_name) and column_name in _columns(connection, table_name)


def _has_index(connection, index_name):
    if _is_pg(connection):
        row = connection.execute(
            text(
                """
                SELECT 1 FROM pg_indexes
                WHERE schemaname = CURRENT_SCHEMA() AND indexname = :name
                LIMIT 1
                """
            ),
            {"name": index_name},
        ).fetchone()
        return row is not None
    row = connection.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :name LIMIT 1"),
        {"name": index_name},
    ).fetchone()
    return row is not None


def _sqlite_index_names(connection, table_name):
    return {
        row[1]
        for row in connection.execute(text(f"PRAGMA index_list({table_name})")).fetchall()
    }


def _sqlite_unique_slug_exists(connection):
    for row in connection.execute(text("PRAGMA index_list(workspaces)")).fetchall():
        if not row[2] or row[3] not in ("u", "c"):
            continue
        columns = [index_row[2] for index_row in connection.execute(text(f"PRAGMA index_info({row[1]})")).fetchall()]
        if columns == ["slug"]:
            return True
    return False


def _sqlite_unique_constraint_exists(connection, table_name, constraint_name, columns):
    table_sql = connection.execute(
        text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
        {"name": table_name},
    ).scalar_one()
    if constraint_name.upper() not in _normalize_sql_fragment(table_sql):
        return False
    matches = []
    for row in connection.execute(text(f"PRAGMA index_list({table_name})")).fetchall():
        if not row[2] or row[3] != "u":
            continue
        key_columns = [
            item[2]
            for item in connection.execute(text(f"PRAGMA index_xinfo({row[1]})")).fetchall()
            if len(item) >= 6 and item[5] == 1
        ]
        if key_columns == list(columns):
            matches.append(row[1])
    return len(matches) == 1


def _sqlite_unique_signatures(connection, table_name):
    signatures = []
    for row in connection.execute(text(f"PRAGMA index_list({table_name})")).fetchall():
        if not row[2] or row[3] not in ("u", "c"):
            continue
        keys = [item for item in _sqlite_index_signature(connection, table_name, row[1])[4] if item[5] == 1]
        signatures.append(
            (
                row[3],
                int(row[4]),
                tuple(item[2] for item in keys),
                tuple(item[4] for item in keys),
                tuple(item[3] for item in keys),
            )
        )
    return tuple(sorted(signatures))


def _assert_sqlite_unique_signatures(connection, table_name, expected):
    if _sqlite_unique_signatures(connection, table_name) != tuple(sorted(expected)):
        raise RuntimeError(f"0007 SQLite UNIQUE signatures differ from the exact expected set: {table_name}")


def _assert_sqlite_check_constraints(connection):
    check_definitions = {
        "workspace_purge_requests": {
            "ck_workspace_purge_requests_purge_type": "purge_type = 'workspace'",
            "ck_workspace_purge_requests_status": f"status IN ({_quoted_values(REQUEST_STATUSES)})",
            "ck_workspace_purge_requests_attempt_count": "attempt_count >= 0",
            "ck_workspace_purge_requests_hold_check_status": f"hold_check_status IN ({_quoted_values(HOLD_CHECK_STATUSES)})",
            "ck_workspace_purge_requests_completed_at": "status <> 'COMPLETED' OR completed_at IS NOT NULL",
            "ck_workspace_purge_requests_manifest_hash": _check_expression(connection, "manifest_hash"),
        },
        "purge_legal_holds": {
            "ck_purge_legal_holds_status": f"status IN ({_quoted_values(HOLD_STATUSES)})",
            "ck_purge_legal_holds_release_fields": "(status = 'ACTIVE' AND released_at IS NULL AND released_by_id IS NULL AND released_by_snapshot IS NULL AND release_reason IS NULL) OR (status = 'RELEASED' AND released_at IS NOT NULL AND released_by_snapshot IS NOT NULL AND release_reason IS NOT NULL)",
        },
        "purge_lifecycle_events": {
            "ck_purge_lifecycle_events_sequence_positive": "event_sequence > 0",
            "ck_purge_lifecycle_events_event_type": f"event_type IN ({_quoted_values(EVENT_TYPES)})",
            "ck_purge_lifecycle_events_metadata_hash": _check_expression(connection, "metadata_hash"),
        },
        "workspaces": {
            "ck_workspaces_purge_terminal_consistency": "(purged_at IS NULL AND purge_request_id IS NULL) OR (purged_at IS NOT NULL AND purge_request_id IS NOT NULL AND deleted_at IS NOT NULL)",
        },
    }
    for table_name, definitions in check_definitions.items():
        table_sql = _normalize_sqlite_check_fragment(
            connection.execute(
                text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
                {"name": table_name},
            ).scalar_one()
        )
        for constraint_name, expression in definitions.items():
            expected = _normalize_sqlite_check_fragment(f"CONSTRAINT {constraint_name} CHECK ({expression})")
            if expected not in table_sql:
                raise RuntimeError(f"0007 SQLite CHECK definition mismatch: {table_name}.{constraint_name}")


def _sqlite_schema_dependencies(connection):
    return connection.execute(
        text(
            """
            SELECT type, name
            FROM sqlite_master
            WHERE type IN ('trigger', 'view')
              AND lower(COALESCE(sql, '')) LIKE '%workspaces%'
            ORDER BY type, name
            """
        )
    ).fetchall()


def _sqlite_foreign_keys(connection, table_name):
    groups = {}
    for row in connection.execute(text(f"PRAGMA foreign_key_list({table_name})")).fetchall():
        groups.setdefault(row[0], []).append(row)
    signatures = []
    for rows in groups.values():
        ordered = sorted(rows, key=lambda row: row[1])
        signatures.append(
            (
                ordered[0][2],
                tuple(row[3] for row in ordered),
                tuple(row[4] for row in ordered),
                ordered[0][5].upper(),
                ordered[0][6].upper(),
                ordered[0][7].upper(),
            )
        )
    return tuple(sorted(signatures))


def _workspace_expected_foreign_keys(connection, include_terminal_columns):
    expected = {
        ("users", ("created_by_id",), ("id",), "NO ACTION", "NO ACTION", "NONE"),
        ("users", ("deleted_by_id",), ("id",), "NO ACTION", "SET NULL", "NONE"),
    }
    if include_terminal_columns:
        expected.add(("workspace_purge_requests", ("purge_request_id",), ("id",), "NO ACTION", "RESTRICT", "NONE"))
    return tuple(sorted(expected))


def _assert_sqlite_workspace_schema(connection, include_terminal_columns):
    expected_fks = _workspace_expected_foreign_keys(connection, include_terminal_columns)
    actual_columns = _sqlite_column_signature(connection, "workspaces")
    expected_signature = _workspace_column_signature(include_terminal_columns)
    if actual_columns != expected_signature:
        raise RuntimeError("0007 SQLite workspace column signature differs from the expected exact signature.")
    actual_indexes = _sqlite_index_names(connection, "workspaces")
    expected_named_indexes = _expected_workspace_index_signatures(include_terminal_columns)
    if _sqlite_named_index_signatures(connection, "workspaces") != expected_named_indexes:
        raise RuntimeError("0007 SQLite workspace named-index signatures differ from the expected exact signatures.")
    actual_fks = _sqlite_foreign_keys(connection, "workspaces")
    if actual_fks != expected_fks:
        raise RuntimeError("0007 SQLite workspace schema foreign keys differ from the expected exact set.")
    expected_unique = [("c", 0, ("slug",), ("BINARY",), (0,))]
    if include_terminal_columns:
        expected_unique.append(("u", 0, ("purge_request_id",), ("BINARY",), (0,)))
    _assert_sqlite_unique_signatures(connection, "workspaces", expected_unique)
    if _sqlite_schema_dependencies(connection):
        raise RuntimeError("0007 refuses to rebuild workspaces with unsupported triggers or views.")
    if _has_table(connection, "_workspaces_0007_new") or _has_table(connection, "_workspaces_0007_old"):
        raise RuntimeError("0007 SQLite temporary workspace table remains after rebuild.")
    if include_terminal_columns:
        if not _sqlite_unique_constraint_exists(
            connection, "workspaces", "uq_workspaces_purge_request_id", ("purge_request_id",)
        ):
            raise RuntimeError("0007 SQLite workspace UNIQUE definition mismatch.")
        table_sql = _normalize_sql_fragment(
            connection.execute(
                text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'workspaces'")
            ).scalar_one()
        )
        expected_check = _normalize_sql_fragment(
            "CONSTRAINT ck_workspaces_purge_terminal_consistency CHECK "
            "((purged_at IS NULL AND purge_request_id IS NULL) OR "
            "(purged_at IS NOT NULL AND purge_request_id IS NOT NULL AND deleted_at IS NOT NULL))"
        )
        if expected_check not in table_sql:
            raise RuntimeError("0007 SQLite workspace CHECK definition mismatch.")
    if connection.execute(text("PRAGMA foreign_key_check")).fetchall():
        raise RuntimeError("0007 SQLite foreign_key_check reported violations.")


def _postgres_constraint_definition(connection, table_name, constraint_name):
    if not _is_pg(connection):
        return None
    row = connection.execute(
        text(
            """
            SELECT c.contype, pg_get_constraintdef(c.oid, true)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = CURRENT_SCHEMA()
              AND t.relname = :table_name
              AND c.conname = :constraint_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    ).fetchone()
    return tuple(row) if row else None


def _assert_postgres_constraint(connection, table_name, constraint_name, constraint_type, definition_fragment):
    definition = _postgres_constraint_definition(connection, table_name, constraint_name)
    if definition is None or definition[0] != constraint_type:
        raise RuntimeError(f"0007 PostgreSQL constraint missing or wrongly scoped: {table_name}.{constraint_name}")
    if definition_fragment is not None and _normalize_sql_fragment(definition_fragment) not in _normalize_sql_fragment(definition[1]):
        raise RuntimeError(f"0007 PostgreSQL constraint definition mismatch: {table_name}.{constraint_name}")


def _postgres_foreign_key_signatures(connection, table_name):
    rows = connection.execute(
        text(
            """
            SELECT rt.relname,
                   array_agg(src.attname ORDER BY source_keys.ord),
                   array_agg(ref.attname ORDER BY source_keys.ord),
                   CASE c.confdeltype
                     WHEN 'a' THEN 'NO ACTION'
                     WHEN 'r' THEN 'RESTRICT'
                     WHEN 'c' THEN 'CASCADE'
                     WHEN 'n' THEN 'SET NULL'
                     WHEN 'd' THEN 'SET DEFAULT'
                   END
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_class rt ON rt.oid = c.confrelid
            CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS source_keys(attnum, ord)
            CROSS JOIN LATERAL unnest(c.confkey) WITH ORDINALITY AS reference_keys(attnum, ord)
            JOIN pg_attribute src ON src.attrelid = t.oid AND src.attnum = source_keys.attnum
            JOIN pg_attribute ref ON ref.attrelid = rt.oid AND ref.attnum = reference_keys.attnum
            WHERE n.nspname = CURRENT_SCHEMA()
              AND t.relname = :table_name
              AND c.contype = 'f'
              AND source_keys.ord = reference_keys.ord
            GROUP BY c.oid, rt.relname, c.confdeltype
            ORDER BY c.oid
            """
        ),
        {"table_name": table_name},
    ).fetchall()
    return tuple(sorted((item[0], tuple(item[1]), tuple(item[2]), item[3]) for item in rows))


def _assert_postgres_index(connection, table_name, index_name, columns, unique=False):
    row = connection.execute(
        text(
            """
            SELECT t.relname, i.indisunique, pg_get_expr(i.indpred, i.indrelid),
                   array_agg(a.attname ORDER BY key_info.ord)
            FROM pg_class t
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_index i ON i.indrelid = t.oid
            JOIN pg_class idx ON idx.oid = i.indexrelid
            CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS key_info(attnum, ord)
            LEFT JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = key_info.attnum
            WHERE n.nspname = CURRENT_SCHEMA() AND idx.relname = :index_name
            GROUP BY t.relname, i.indisunique, pg_get_expr(i.indpred, i.indrelid)
            LIMIT 1
            """
        ),
        {"index_name": index_name},
    ).fetchone()
    if row is None or row[0] != table_name or bool(row[1]) != unique or row[2] is not None:
        raise RuntimeError(f"0007 PostgreSQL index missing, wrongly scoped or partial: {table_name}.{index_name}")
    if tuple(row[3]) != tuple(columns):
        raise RuntimeError(f"0007 PostgreSQL index column definition mismatch: {table_name}.{index_name}")


def _postgres_constraint_columns(connection, table_name, constraint_name):
    rows = connection.execute(
        text(
            """
            SELECT a.attname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS key_info(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = key_info.attnum
            WHERE n.nspname = CURRENT_SCHEMA()
              AND t.relname = :table_name
              AND c.conname = :constraint_name
            ORDER BY key_info.ord
            """
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    ).fetchall()
    return tuple(row[0] for row in rows)


def _assert_postgres_unique(connection, table_name, constraint_name, columns):
    definition = _postgres_constraint_definition(connection, table_name, constraint_name)
    if definition is None or definition[0] != "u" or _postgres_constraint_columns(connection, table_name, constraint_name) != tuple(columns):
        raise RuntimeError(f"0007 PostgreSQL UNIQUE definition mismatch: {table_name}.{constraint_name}")


def _check_expression(connection, column_name):
    if _is_pg(connection):
        return f"{column_name} IS NULL OR {column_name} ~ '^[0-9a-f]{{64}}$'"
    return f"{column_name} IS NULL OR (length({column_name}) = 64 AND {column_name} NOT GLOB '*[^0-9a-f]*')"


def _create_request_table(connection):
    if _has_table(connection, "workspace_purge_requests"):
        raise RuntimeError("0007 requires workspace_purge_requests not to exist before upgrade.")

    connection.execute(
        text(
            f"""
            CREATE TABLE workspace_purge_requests (
                id INTEGER PRIMARY KEY{' GENERATED BY DEFAULT AS IDENTITY' if _is_pg(connection) else ' AUTOINCREMENT'},
                lifecycle_id VARCHAR(36) NOT NULL,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                purge_type VARCHAR(30) NOT NULL DEFAULT 'workspace',
                status VARCHAR(30) NOT NULL DEFAULT 'REQUESTED',
                target_deleted_at TIMESTAMP NOT NULL,
                target_deleted_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                target_deleted_by_snapshot VARCHAR(100) NOT NULL,
                target_workspace_name VARCHAR(150) NOT NULL,
                target_workspace_slug VARCHAR(150) NOT NULL,
                requested_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                requested_by_snapshot VARCHAR(100) NOT NULL,
                requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                eligible_at TIMESTAMP NOT NULL,
                retention_policy_version VARCHAR(50) NOT NULL,
                approved_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                approved_by_snapshot VARCHAR(100),
                approved_at TIMESTAMP,
                rejected_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                rejected_by_snapshot VARCHAR(100),
                rejected_at TIMESTAMP,
                rejection_reason TEXT,
                cancelled_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                cancelled_by_snapshot VARCHAR(100),
                cancelled_at TIMESTAMP,
                cancellation_reason TEXT,
                invalidated_at TIMESTAMP,
                invalidated_by_restore BOOLEAN NOT NULL DEFAULT FALSE,
                invalidation_reason VARCHAR(255),
                execution_triggered_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                execution_trigger_snapshot VARCHAR(100),
                execution_started_at TIMESTAMP,
                completed_at TIMESTAMP,
                failed_at TIMESTAMP,
                failure_code VARCHAR(80),
                failure_summary TEXT,
                manifest_version VARCHAR(50) NOT NULL,
                manifest_canonical_text TEXT NOT NULL,
                manifest_hash VARCHAR(64) NOT NULL,
                idempotency_key VARCHAR(150) NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TIMESTAMP,
                retry_eligible_at TIMESTAMP,
                outcome_unknown BOOLEAN NOT NULL DEFAULT FALSE,
                hold_check_status VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
                hold_checked_at TIMESTAMP,
                hold_checked_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                hold_checked_by_snapshot VARCHAR(100),
                hold_check_source VARCHAR(100),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_workspace_purge_requests_lifecycle_id UNIQUE (lifecycle_id),
                CONSTRAINT uq_workspace_purge_requests_idempotency_key UNIQUE (idempotency_key),
                CONSTRAINT uq_workspace_purge_requests_workspace_deleted_at UNIQUE (workspace_id, target_deleted_at),
                CONSTRAINT ck_workspace_purge_requests_purge_type CHECK (purge_type = 'workspace'),
                CONSTRAINT ck_workspace_purge_requests_status CHECK (status IN ({_quoted_values(REQUEST_STATUSES)})),
                CONSTRAINT ck_workspace_purge_requests_attempt_count CHECK (attempt_count >= 0),
                CONSTRAINT ck_workspace_purge_requests_hold_check_status CHECK (hold_check_status IN ({_quoted_values(HOLD_CHECK_STATUSES)})),
                CONSTRAINT ck_workspace_purge_requests_completed_at CHECK (status <> 'COMPLETED' OR completed_at IS NOT NULL),
                CONSTRAINT ck_workspace_purge_requests_manifest_hash CHECK ({_check_expression(connection, 'manifest_hash')})
            )
            """
        )
    )

    for name, expression in {
        "ix_workspace_purge_requests_workspace_id": "workspace_id",
        "ix_workspace_purge_requests_status_eligible_at": "status, eligible_at",
        "ix_workspace_purge_requests_workspace_status": "workspace_id, status",
        "ix_workspace_purge_requests_status_retry_eligible_at": "status, retry_eligible_at",
        "ix_workspace_purge_requests_hold_check_status": "hold_check_status",
    }.items():
        connection.execute(text(f"CREATE INDEX {name} ON workspace_purge_requests ({expression})"))


def _quoted_values(values):
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def _create_hold_table(connection):
    if _has_table(connection, "purge_legal_holds"):
        raise RuntimeError("0007 requires purge_legal_holds not to exist before upgrade.")
    connection.execute(
        text(
            f"""
            CREATE TABLE purge_legal_holds (
                id INTEGER PRIMARY KEY{' GENERATED BY DEFAULT AS IDENTITY' if _is_pg(connection) else ' AUTOINCREMENT'},
                hold_id VARCHAR(36) NOT NULL,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                hold_type VARCHAR(50) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
                source VARCHAR(100) NOT NULL,
                external_reference VARCHAR(150),
                reason TEXT NOT NULL,
                placed_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                placed_by_snapshot VARCHAR(100) NOT NULL,
                placed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                released_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                released_by_snapshot VARCHAR(100),
                released_at TIMESTAMP,
                release_reason TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_purge_legal_holds_hold_id UNIQUE (hold_id),
                CONSTRAINT ck_purge_legal_holds_status CHECK (status IN ({_quoted_values(HOLD_STATUSES)})),
                CONSTRAINT ck_purge_legal_holds_release_fields CHECK (
                    (status = 'ACTIVE' AND released_at IS NULL AND released_by_id IS NULL
                        AND released_by_snapshot IS NULL AND release_reason IS NULL)
                    OR
                    (status = 'RELEASED' AND released_at IS NOT NULL
                        AND released_by_snapshot IS NOT NULL AND release_reason IS NOT NULL)
                )
            )
            """
        )
    )
    connection.execute(text("CREATE INDEX ix_purge_legal_holds_workspace_status ON purge_legal_holds (workspace_id, status)"))
    connection.execute(text("CREATE INDEX ix_purge_legal_holds_status_type ON purge_legal_holds (status, hold_type)"))


def _create_event_table(connection):
    if _has_table(connection, "purge_lifecycle_events"):
        raise RuntimeError("0007 requires purge_lifecycle_events not to exist before upgrade.")
    connection.execute(
        text(
            f"""
            CREATE TABLE purge_lifecycle_events (
                id INTEGER PRIMARY KEY{' GENERATED BY DEFAULT AS IDENTITY' if _is_pg(connection) else ' AUTOINCREMENT'},
                request_id INTEGER NOT NULL REFERENCES workspace_purge_requests(id) ON DELETE RESTRICT,
                lifecycle_id_snapshot VARCHAR(36) NOT NULL,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
                workspace_name_snapshot VARCHAR(150) NOT NULL,
                event_sequence INTEGER NOT NULL,
                event_type VARCHAR(40) NOT NULL,
                actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                actor_snapshot VARCHAR(100) NOT NULL,
                event_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status_before VARCHAR(30),
                status_after VARCHAR(30),
                reason_code VARCHAR(80),
                sanitized_summary TEXT,
                metadata_canonical_text TEXT,
                metadata_hash VARCHAR(64),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_purge_lifecycle_events_request_sequence UNIQUE (request_id, event_sequence),
                CONSTRAINT ck_purge_lifecycle_events_sequence_positive CHECK (event_sequence > 0),
                CONSTRAINT ck_purge_lifecycle_events_event_type CHECK (event_type IN ({_quoted_values(EVENT_TYPES)})),
                CONSTRAINT ck_purge_lifecycle_events_metadata_hash CHECK ({_check_expression(connection, 'metadata_hash')})
            )
            """
        )
    )
    connection.execute(text("CREATE INDEX ix_purge_lifecycle_events_request_event_at ON purge_lifecycle_events (request_id, event_at)"))
    connection.execute(text("CREATE INDEX ix_purge_lifecycle_events_workspace_event_at ON purge_lifecycle_events (workspace_id, event_at)"))
    connection.execute(text("CREATE INDEX ix_purge_lifecycle_events_lifecycle_id ON purge_lifecycle_events (lifecycle_id_snapshot)"))
    connection.execute(text("CREATE INDEX ix_purge_lifecycle_events_event_type ON purge_lifecycle_events (event_type)"))


def _rebuild_sqlite_workspaces(connection, include_terminal_columns):
    if include_terminal_columns:
        source_schema_has_terminal_columns = False
        base_columns = (
            "id, name, slug, status, created_by_id, notes, "
            "created_at, updated_at, deleted_at, deleted_by_id, deletion_reason"
        )
        target_columns = base_columns + ", purged_at, purge_request_id"
        source_expressions = base_columns + ", NULL AS purged_at, NULL AS purge_request_id"
    else:
        source_schema_has_terminal_columns = True
        base_columns = (
            "id, name, slug, status, created_by_id, notes, "
            "created_at, updated_at, deleted_at, deleted_by_id, deletion_reason"
        )
        target_columns = base_columns
        source_expressions = base_columns

    if target_columns.count(",") != source_expressions.count(","):
        raise RuntimeError("0007 SQLite workspace copy target/source expression arity mismatch.")

    required = set(WORKSPACE_BASE_COLUMNS)
    if source_schema_has_terminal_columns:
        required.update(("purged_at", "purge_request_id"))
    existing = _columns(connection, "workspaces")
    if existing != required:
        raise RuntimeError(
            "SQLite workspace rebuild requires the exact pre-0007 columns: "
            f"expected {sorted(required)}, got {sorted(existing)}"
        )
    required_indexes = set(WORKSPACE_BASE_INDEXES)
    if source_schema_has_terminal_columns:
        required_indexes.add("ix_workspaces_purged_at")
    actual_indexes = _sqlite_index_names(connection, "workspaces")
    actual_named_indexes = {name for name in actual_indexes if not name.startswith("sqlite_autoindex_")}
    if actual_named_indexes != required_indexes or not _sqlite_unique_slug_exists(connection):
        raise RuntimeError("SQLite workspace rebuild requires the exact named indexes and slug uniqueness.")
    required_fks = _workspace_expected_foreign_keys(connection, source_schema_has_terminal_columns)
    if _sqlite_foreign_keys(connection, "workspaces") != required_fks:
        raise RuntimeError("SQLite workspace rebuild requires the exact foreign-key set.")
    if _sqlite_schema_dependencies(connection):
        raise RuntimeError("SQLite workspace rebuild refuses unsupported triggers or views.")

    new_table = "_workspaces_0007_new"
    if _has_table(connection, new_table) or _has_table(connection, "_workspaces_0007_old"):
        raise RuntimeError("Temporary 0007 SQLite workspace table already exists.")
    terminal_columns = (
        ", purged_at DATETIME, purge_request_id INTEGER"
        if include_terminal_columns
        else ""
    )
    terminal_constraints = (
        ", CONSTRAINT uq_workspaces_purge_request_id UNIQUE (purge_request_id),"
        " CONSTRAINT ck_workspaces_purge_terminal_consistency CHECK ("
        "(purged_at IS NULL AND purge_request_id IS NULL) OR "
        "(purged_at IS NOT NULL AND purge_request_id IS NOT NULL AND deleted_at IS NOT NULL))"
        if include_terminal_columns
        else ""
    )
    request_fk = (
        ", FOREIGN KEY (purge_request_id) REFERENCES workspace_purge_requests(id) ON DELETE RESTRICT"
        if include_terminal_columns
        else ""
    )
    connection.execute(
        text(
            f"""
            CREATE TABLE {new_table} (
                id INTEGER NOT NULL,
                name VARCHAR(150) NOT NULL,
                slug VARCHAR(150) NOT NULL,
                status VARCHAR(20) NOT NULL,
                created_by_id INTEGER,
                notes TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                deleted_at DATETIME,
                deleted_by_id INTEGER,
                deletion_reason VARCHAR(255){terminal_columns},
                PRIMARY KEY (id),
                FOREIGN KEY (created_by_id) REFERENCES users(id),
                FOREIGN KEY (deleted_by_id) REFERENCES users(id) ON DELETE SET NULL{terminal_constraints}{request_fk}
            )
            """
        )
    )
    connection.execute(
        text(
            f"INSERT INTO {new_table} ({target_columns}) "
            f"SELECT {source_expressions} FROM workspaces"
        )
    )
    connection.execute(text("DROP TABLE workspaces"))
    connection.execute(text(f"ALTER TABLE {new_table} RENAME TO workspaces"))
    connection.execute(text("CREATE UNIQUE INDEX ix_workspaces_slug ON workspaces (slug)"))
    connection.execute(text("CREATE INDEX ix_workspaces_status ON workspaces (status)"))
    connection.execute(text("CREATE INDEX ix_workspaces_created_at ON workspaces (created_at)"))
    connection.execute(text("CREATE INDEX ix_workspaces_created_by_id ON workspaces (created_by_id)"))
    if include_terminal_columns:
        connection.execute(text("CREATE INDEX ix_workspaces_purged_at ON workspaces (purged_at)"))


def _sqlite_with_foreign_keys_disabled(connection, operation):
    raw_connection = getattr(connection.connection, "driver_connection", connection.connection)
    connection.commit()
    original = None
    pragma_disabled = False
    transaction_started = False

    def read_fk_state():
        cursor = raw_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys")
            return int(cursor.fetchone()[0])
        finally:
            cursor.close()

    def restore_state():
        cursor = raw_connection.cursor()
        try:
            cursor.execute(f"PRAGMA foreign_keys={'ON' if original else 'OFF'}")
            restored = read_fk_state()
            if restored != original:
                raise RuntimeError("0007 SQLite foreign_keys state was not restored.")
        finally:
            cursor.close()

    try:
        original = read_fk_state()
        raw_connection.commit()
        cursor = raw_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=OFF")
            pragma_disabled = True
            if read_fk_state() != 0:
                raise RuntimeError("0007 SQLite could not disable foreign_keys outside the DDL transaction.")
            cursor.execute("BEGIN IMMEDIATE")
            transaction_started = True
        finally:
            cursor.close()
    except Exception as setup_error:
        try:
            if transaction_started:
                raw_connection.rollback()
            if pragma_disabled and original is not None:
                restore_state()
        except Exception as restore_error:
            connection.invalidate(restore_error)
            raise RuntimeError(
                f"0007 SQLite setup failed ({setup_error!r}) and foreign_keys restoration also failed ({restore_error!r})."
            ) from setup_error
        raise

    try:
        operation()
        if connection.in_transaction():
            connection.commit()
        else:
            raw_connection.commit()
        transaction_started = False
    except Exception as operation_error:
        try:
            if connection.in_transaction():
                connection.rollback()
            elif transaction_started:
                raw_connection.rollback()
            restore_state()
        except Exception as restore_error:
            connection.invalidate(restore_error)
            raise RuntimeError(
                f"0007 SQLite operation failed ({operation_error!r}) and foreign_keys restoration also failed ({restore_error!r})."
            ) from operation_error
        raise

    try:
        restore_state()
    except Exception as restore_error:
        connection.invalidate(restore_error)
        raise RuntimeError(
            "0007 SQLite DDL may already be committed but foreign_keys restoration failed; "
            "the migration revision remains unstamped and requires explicit recovery."
        ) from restore_error


def _verify_sqlite_upgrade(connection):
    _assert_sqlite_workspace_schema(connection, include_terminal_columns=True)
    for table in ("workspace_purge_requests", "purge_legal_holds", "purge_lifecycle_events"):
        if not _has_table(connection, table):
            raise RuntimeError(f"0007 SQLite verification missing table: {table}")
    workflow_indexes = (
        ("workspace_purge_requests", "ix_workspace_purge_requests_workspace_id", ("workspace_id",)),
        ("workspace_purge_requests", "ix_workspace_purge_requests_status_eligible_at", ("status", "eligible_at")),
        ("workspace_purge_requests", "ix_workspace_purge_requests_workspace_status", ("workspace_id", "status")),
        ("workspace_purge_requests", "ix_workspace_purge_requests_status_retry_eligible_at", ("status", "retry_eligible_at")),
        ("workspace_purge_requests", "ix_workspace_purge_requests_hold_check_status", ("hold_check_status",)),
        ("purge_legal_holds", "ix_purge_legal_holds_workspace_status", ("workspace_id", "status")),
        ("purge_legal_holds", "ix_purge_legal_holds_status_type", ("status", "hold_type")),
        ("purge_lifecycle_events", "ix_purge_lifecycle_events_request_event_at", ("request_id", "event_at")),
        ("purge_lifecycle_events", "ix_purge_lifecycle_events_workspace_event_at", ("workspace_id", "event_at")),
        ("purge_lifecycle_events", "ix_purge_lifecycle_events_lifecycle_id", ("lifecycle_id_snapshot",)),
        ("purge_lifecycle_events", "ix_purge_lifecycle_events_event_type", ("event_type",)),
    )
    for table_name, index_name, columns in workflow_indexes:
        _assert_sqlite_index(connection, table_name, index_name, columns)
    unique_constraints = (
        ("workspaces", "sqlite_autoindex_workspaces_1", ("slug",)),
        ("workspaces", "uq_workspaces_purge_request_id", ("purge_request_id",)),
        ("workspace_purge_requests", "uq_workspace_purge_requests_lifecycle_id", ("lifecycle_id",)),
        ("workspace_purge_requests", "uq_workspace_purge_requests_idempotency_key", ("idempotency_key",)),
        ("workspace_purge_requests", "uq_workspace_purge_requests_workspace_deleted_at", ("workspace_id", "target_deleted_at")),
        ("purge_legal_holds", "uq_purge_legal_holds_hold_id", ("hold_id",)),
        ("purge_lifecycle_events", "uq_purge_lifecycle_events_request_sequence", ("request_id", "event_sequence")),
    )
    for table_name, constraint_name, columns in unique_constraints:
        if constraint_name.startswith("sqlite_autoindex_"):
            if not _sqlite_unique_slug_exists(connection):
                raise RuntimeError("0007 SQLite verification missing the unique workspace slug constraint.")
        elif not _sqlite_unique_constraint_exists(connection, table_name, constraint_name, columns):
            raise RuntimeError(f"0007 SQLite UNIQUE definition mismatch: {table_name}.{constraint_name}")
    _assert_sqlite_unique_signatures(
        connection,
        "workspace_purge_requests",
        (
            ("u", 0, ("lifecycle_id",), ("BINARY",), (0,)),
            ("u", 0, ("idempotency_key",), ("BINARY",), (0,)),
            ("u", 0, ("workspace_id", "target_deleted_at"), ("BINARY", "BINARY"), (0, 0)),
        ),
    )
    _assert_sqlite_unique_signatures(
        connection,
        "purge_legal_holds",
        (("u", 0, ("hold_id",), ("BINARY",), (0,)),),
    )
    _assert_sqlite_unique_signatures(
        connection,
        "purge_lifecycle_events",
        (("u", 0, ("request_id", "event_sequence"), ("BINARY", "BINARY"), (0, 0)),),
    )
    _assert_sqlite_check_constraints(connection)
    expected_workflow_fks = {
        "workspace_purge_requests": (
            ("users", ("approved_by_id",), ("id",), "NO ACTION", "SET NULL", "NONE"),
            ("users", ("cancelled_by_id",), ("id",), "NO ACTION", "SET NULL", "NONE"),
            ("users", ("execution_triggered_by_id",), ("id",), "NO ACTION", "SET NULL", "NONE"),
            ("users", ("hold_checked_by_id",), ("id",), "NO ACTION", "SET NULL", "NONE"),
            ("users", ("rejected_by_id",), ("id",), "NO ACTION", "SET NULL", "NONE"),
            ("users", ("requested_by_id",), ("id",), "NO ACTION", "SET NULL", "NONE"),
            ("users", ("target_deleted_by_id",), ("id",), "NO ACTION", "SET NULL", "NONE"),
            ("workspaces", ("workspace_id",), ("id",), "NO ACTION", "RESTRICT", "NONE"),
        ),
        "purge_legal_holds": (
            ("users", ("placed_by_id",), ("id",), "NO ACTION", "SET NULL", "NONE"),
            ("users", ("released_by_id",), ("id",), "NO ACTION", "SET NULL", "NONE"),
            ("workspaces", ("workspace_id",), ("id",), "NO ACTION", "RESTRICT", "NONE"),
        ),
        "purge_lifecycle_events": (
            ("users", ("actor_id",), ("id",), "NO ACTION", "SET NULL", "NONE"),
            ("workspaces", ("workspace_id",), ("id",), "NO ACTION", "RESTRICT", "NONE"),
            ("workspace_purge_requests", ("request_id",), ("id",), "NO ACTION", "RESTRICT", "NONE"),
        ),
    }
    for table_name, expected_fks in expected_workflow_fks.items():
        if _sqlite_foreign_keys(connection, table_name) != tuple(sorted(expected_fks)):
            raise RuntimeError(f"0007 SQLite verification found an unexpected FK contract on {table_name}.")


def _verify_sqlite_downgrade(connection):
    if any(_has_table(connection, table) for table in ("workspace_purge_requests", "purge_legal_holds", "purge_lifecycle_events")):
        raise RuntimeError("0007 SQLite verification found workflow tables after downgrade.")
    if _has_column(connection, "workspaces", "purged_at") or _has_column(connection, "workspaces", "purge_request_id"):
        raise RuntimeError("0007 SQLite verification found terminal columns after downgrade.")
    _assert_sqlite_workspace_schema(connection, include_terminal_columns=False)


def _add_postgres_workspace_columns(connection):
    if not _has_column(connection, "workspaces", "purged_at"):
        connection.execute(text("ALTER TABLE workspaces ADD COLUMN purged_at TIMESTAMP NULL"))
    if not _has_column(connection, "workspaces", "purge_request_id"):
        connection.execute(text("ALTER TABLE workspaces ADD COLUMN purge_request_id INTEGER NULL"))
    if _postgres_constraint_definition(connection, "workspaces", "uq_workspaces_purge_request_id") is None:
        connection.execute(text("ALTER TABLE workspaces ADD CONSTRAINT uq_workspaces_purge_request_id UNIQUE (purge_request_id)"))
    if _postgres_constraint_definition(connection, "workspaces", "ck_workspaces_purge_terminal_consistency") is None:
        connection.execute(
            text(
                """
                ALTER TABLE workspaces ADD CONSTRAINT ck_workspaces_purge_terminal_consistency
                CHECK (
                    (purged_at IS NULL AND purge_request_id IS NULL)
                    OR
                    (purged_at IS NOT NULL AND purge_request_id IS NOT NULL AND deleted_at IS NOT NULL)
                )
                """
            )
        )
    if _postgres_constraint_definition(connection, "workspaces", "fk_workspaces_purge_request_id") is None:
        connection.execute(
            text(
                "ALTER TABLE workspaces ADD CONSTRAINT fk_workspaces_purge_request_id "
                "FOREIGN KEY (purge_request_id) REFERENCES workspace_purge_requests(id) ON DELETE RESTRICT"
            )
        )
    if not _has_index(connection, "ix_workspaces_purged_at"):
        connection.execute(text("CREATE INDEX ix_workspaces_purged_at ON workspaces (purged_at)"))


def _remove_one_fk_signature(signatures, target):
    remaining = list(signatures)
    try:
        remaining.remove(target)
    except ValueError as exc:
        raise RuntimeError("0007 PostgreSQL verification missing the exact purge-request FK.") from exc
    return tuple(remaining)


def _verify_postgres_upgrade(connection, workspace_fk_baseline):
    for table in ("workspace_purge_requests", "purge_legal_holds", "purge_lifecycle_events"):
        if not _has_table(connection, table):
            raise RuntimeError(f"0007 PostgreSQL verification missing table: {table}")
    for column in ("purged_at", "purge_request_id"):
        if not _has_column(connection, "workspaces", column):
            raise RuntimeError(f"0007 PostgreSQL verification missing workspace column: {column}")
    workflow_indexes = (
        ("workspace_purge_requests", "ix_workspace_purge_requests_workspace_id", ("workspace_id",)),
        ("workspace_purge_requests", "ix_workspace_purge_requests_status_eligible_at", ("status", "eligible_at")),
        ("workspace_purge_requests", "ix_workspace_purge_requests_workspace_status", ("workspace_id", "status")),
        ("workspace_purge_requests", "ix_workspace_purge_requests_status_retry_eligible_at", ("status", "retry_eligible_at")),
        ("workspace_purge_requests", "ix_workspace_purge_requests_hold_check_status", ("hold_check_status",)),
        ("purge_legal_holds", "ix_purge_legal_holds_workspace_status", ("workspace_id", "status")),
        ("purge_legal_holds", "ix_purge_legal_holds_status_type", ("status", "hold_type")),
        ("purge_lifecycle_events", "ix_purge_lifecycle_events_request_event_at", ("request_id", "event_at")),
        ("purge_lifecycle_events", "ix_purge_lifecycle_events_workspace_event_at", ("workspace_id", "event_at")),
        ("purge_lifecycle_events", "ix_purge_lifecycle_events_lifecycle_id", ("lifecycle_id_snapshot",)),
        ("purge_lifecycle_events", "ix_purge_lifecycle_events_event_type", ("event_type",)),
        ("workspaces", "ix_workspaces_purged_at", ("purged_at",)),
    )
    for table_name, index_name, columns in workflow_indexes:
        _assert_postgres_index(connection, table_name, index_name, columns)
    constraints = (
        ("workspace_purge_requests", "uq_workspace_purge_requests_lifecycle_id", "u", None),
        ("workspace_purge_requests", "uq_workspace_purge_requests_idempotency_key", "u", None),
        ("workspace_purge_requests", "uq_workspace_purge_requests_workspace_deleted_at", "u", None),
        ("workspace_purge_requests", "ck_workspace_purge_requests_purge_type", "c", None),
        ("workspace_purge_requests", "ck_workspace_purge_requests_status", "c", None),
        ("workspace_purge_requests", "ck_workspace_purge_requests_attempt_count", "c", None),
        ("workspace_purge_requests", "ck_workspace_purge_requests_hold_check_status", "c", None),
        ("workspace_purge_requests", "ck_workspace_purge_requests_completed_at", "c", None),
        ("workspace_purge_requests", "ck_workspace_purge_requests_manifest_hash", "c", None),
        ("purge_legal_holds", "uq_purge_legal_holds_hold_id", "u", None),
        ("purge_legal_holds", "ck_purge_legal_holds_status", "c", None),
        ("purge_legal_holds", "ck_purge_legal_holds_release_fields", "c", None),
        ("purge_lifecycle_events", "uq_purge_lifecycle_events_request_sequence", "u", None),
        ("purge_lifecycle_events", "ck_purge_lifecycle_events_sequence_positive", "c", None),
        ("purge_lifecycle_events", "ck_purge_lifecycle_events_event_type", "c", None),
        ("purge_lifecycle_events", "ck_purge_lifecycle_events_metadata_hash", "c", None),
        ("workspaces", "uq_workspaces_purge_request_id", "u", None),
        ("workspaces", "ck_workspaces_purge_terminal_consistency", "c", "purged_at IS NULL AND purge_request_id IS NULL"),
        ("workspaces", "fk_workspaces_purge_request_id", "f", "FOREIGN KEY (purge_request_id) REFERENCES workspace_purge_requests(id) ON DELETE RESTRICT"),
    )
    for constraint in constraints:
        _assert_postgres_constraint(connection, *constraint)
    for table_name, constraint_name, columns in (
        ("workspace_purge_requests", "uq_workspace_purge_requests_lifecycle_id", ("lifecycle_id",)),
        ("workspace_purge_requests", "uq_workspace_purge_requests_idempotency_key", ("idempotency_key",)),
        ("workspace_purge_requests", "uq_workspace_purge_requests_workspace_deleted_at", ("workspace_id", "target_deleted_at")),
        ("purge_legal_holds", "uq_purge_legal_holds_hold_id", ("hold_id",)),
        ("purge_lifecycle_events", "uq_purge_lifecycle_events_request_sequence", ("request_id", "event_sequence")),
        ("workspaces", "uq_workspaces_purge_request_id", ("purge_request_id",)),
    ):
        _assert_postgres_unique(connection, table_name, constraint_name, columns)
    _assert_postgres_check_semantics(connection, "workspace_purge_requests", "ck_workspace_purge_requests_purge_type", "scalar", ("purge_type", "=", "workspace"))
    _assert_postgres_check_semantics(connection, "workspace_purge_requests", "ck_workspace_purge_requests_status", "status_set", ("status", REQUEST_STATUSES))
    _assert_postgres_check_semantics(connection, "workspace_purge_requests", "ck_workspace_purge_requests_attempt_count", "scalar", ("attempt_count", ">=", 0))
    _assert_postgres_check_semantics(connection, "workspace_purge_requests", "ck_workspace_purge_requests_hold_check_status", "status_set", ("hold_check_status", HOLD_CHECK_STATUSES))
    _assert_postgres_check_semantics(connection, "workspace_purge_requests", "ck_workspace_purge_requests_completed_at", "predicates", ("status <> 'COMPLETED'", "completed_at IS NOT NULL"))
    _assert_postgres_check_semantics(connection, "workspace_purge_requests", "ck_workspace_purge_requests_manifest_hash", "hash", ("manifest_hash",))
    _assert_postgres_check_semantics(connection, "purge_legal_holds", "ck_purge_legal_holds_status", "status_set", ("status", HOLD_STATUSES))
    _assert_postgres_check_semantics(connection, "purge_legal_holds", "ck_purge_legal_holds_release_fields", "predicates", ("status = 'ACTIVE'", "released_at IS NULL", "released_by_snapshot IS NULL", "release_reason IS NULL", "status = 'RELEASED'", "released_at IS NOT NULL", "released_by_snapshot IS NOT NULL", "release_reason IS NOT NULL"))
    _assert_postgres_check_semantics(connection, "purge_lifecycle_events", "ck_purge_lifecycle_events_sequence_positive", "scalar", ("event_sequence", ">", 0))
    _assert_postgres_check_semantics(connection, "purge_lifecycle_events", "ck_purge_lifecycle_events_event_type", "status_set", ("event_type", EVENT_TYPES))
    _assert_postgres_check_semantics(connection, "purge_lifecycle_events", "ck_purge_lifecycle_events_metadata_hash", "hash", ("metadata_hash",))
    _assert_postgres_check_semantics(connection, "workspaces", "ck_workspaces_purge_terminal_consistency", "predicates", ("purged_at IS NULL", "purge_request_id IS NULL", "purged_at IS NOT NULL", "purge_request_id IS NOT NULL", "deleted_at IS NOT NULL"))
    expected_workspaces_fks = tuple(workspace_fk_baseline) + (_WORKSPACE_PURGE_REQUEST_FK_SIGNATURE,)
    expected_foreign_keys = {
        "workspace_purge_requests": (
            ("users", ("approved_by_id",), ("id",), "SET NULL"),
            ("users", ("cancelled_by_id",), ("id",), "SET NULL"),
            ("users", ("execution_triggered_by_id",), ("id",), "SET NULL"),
            ("users", ("hold_checked_by_id",), ("id",), "SET NULL"),
            ("users", ("rejected_by_id",), ("id",), "SET NULL"),
            ("users", ("requested_by_id",), ("id",), "SET NULL"),
            ("users", ("target_deleted_by_id",), ("id",), "SET NULL"),
            ("workspaces", ("workspace_id",), ("id",), "RESTRICT"),
        ),
        "purge_legal_holds": (
            ("users", ("placed_by_id",), ("id",), "SET NULL"),
            ("users", ("released_by_id",), ("id",), "SET NULL"),
            ("workspaces", ("workspace_id",), ("id",), "RESTRICT"),
        ),
        "purge_lifecycle_events": (
            ("users", ("actor_id",), ("id",), "SET NULL"),
            ("workspaces", ("workspace_id",), ("id",), "RESTRICT"),
            ("workspace_purge_requests", ("request_id",), ("id",), "RESTRICT"),
        ),
        "workspaces": expected_workspaces_fks,
    }
    for table_name, expected in expected_foreign_keys.items():
        actual = _postgres_foreign_key_signatures(connection, table_name)
        if tuple(sorted(actual)) != tuple(sorted(expected)):
            raise RuntimeError(f"0007 PostgreSQL verification found an unexpected FK contract on {table_name}.")


def _verify_postgres_downgrade(connection, pre_downgrade_fks):
    for table in ("workspace_purge_requests", "purge_legal_holds", "purge_lifecycle_events"):
        if _has_table(connection, table):
            raise RuntimeError(f"0007 PostgreSQL verification found table after downgrade: {table}")
    for column in ("purged_at", "purge_request_id"):
        if _has_column(connection, "workspaces", column):
            raise RuntimeError(f"0007 PostgreSQL verification found workspace column after downgrade: {column}")
    expected_baseline = _remove_one_fk_signature(
        pre_downgrade_fks,
        _WORKSPACE_PURGE_REQUEST_FK_SIGNATURE,
    )
    actual = _postgres_foreign_key_signatures(connection, "workspaces")
    if tuple(actual) != tuple(expected_baseline):
        raise RuntimeError("0007 PostgreSQL downgrade did not restore the exact workspace FK baseline.")


def upgrade():
    from extensions import db

    if db.engine.dialect.name == "postgresql":
        with db.engine.begin() as connection:
            if not _has_table(connection, "workspaces") or not _has_table(connection, "users"):
                raise RuntimeError("0007 requires existing users and workspaces tables.")
            if _has_column(connection, "workspaces", "purged_at") or _has_column(connection, "workspaces", "purge_request_id"):
                raise RuntimeError("0007 terminal workspace columns already exist; refusing ambiguous upgrade.")
            workspace_fk_baseline = _postgres_foreign_key_signatures(connection, "workspaces")
            if _WORKSPACE_PURGE_REQUEST_FK_SIGNATURE in workspace_fk_baseline:
                raise RuntimeError("0007 workspace baseline already contains the purge-request FK.")
            _create_request_table(connection)
            _create_hold_table(connection)
            _create_event_table(connection)
            _add_postgres_workspace_columns(connection)
            _verify_postgres_upgrade(connection, workspace_fk_baseline)
    else:
        with db.engine.connect() as connection:
            if not _has_table(connection, "workspaces") or not _has_table(connection, "users"):
                raise RuntimeError("0007 requires existing users and workspaces tables.")
            if _has_column(connection, "workspaces", "purged_at") or _has_column(connection, "workspaces", "purge_request_id"):
                raise RuntimeError("0007 terminal workspace columns already exist; refusing ambiguous upgrade.")
            _assert_sqlite_workspace_schema(connection, include_terminal_columns=False)

            def operation():
                _create_request_table(connection)
                _create_hold_table(connection)
                _create_event_table(connection)
                _rebuild_sqlite_workspaces(connection, include_terminal_columns=True)
                _verify_sqlite_upgrade(connection)

            _sqlite_with_foreign_keys_disabled(connection, operation)


def _has_any_rows(connection, table_name):
    return connection.execute(text(f"SELECT 1 FROM {table_name} LIMIT 1")).fetchone() is not None


def _drop_postgres_workspace_columns(connection):
    if _postgres_constraint_definition(connection, "workspaces", "fk_workspaces_purge_request_id") is not None:
        connection.execute(text("ALTER TABLE workspaces DROP CONSTRAINT fk_workspaces_purge_request_id"))
    if _postgres_constraint_definition(connection, "workspaces", "ck_workspaces_purge_terminal_consistency") is not None:
        connection.execute(text("ALTER TABLE workspaces DROP CONSTRAINT ck_workspaces_purge_terminal_consistency"))
    if _postgres_constraint_definition(connection, "workspaces", "uq_workspaces_purge_request_id") is not None:
        connection.execute(text("ALTER TABLE workspaces DROP CONSTRAINT uq_workspaces_purge_request_id"))
    if _has_index(connection, "ix_workspaces_purged_at"):
        connection.execute(text("DROP INDEX IF EXISTS ix_workspaces_purged_at"))
    if _has_column(connection, "workspaces", "purge_request_id"):
        connection.execute(text("ALTER TABLE workspaces DROP COLUMN purge_request_id"))
    if _has_column(connection, "workspaces", "purged_at"):
        connection.execute(text("ALTER TABLE workspaces DROP COLUMN purged_at"))


def downgrade():
    from extensions import db

    def assert_empty_and_unmarked(connection):
        for table in ("workspace_purge_requests", "purge_legal_holds", "purge_lifecycle_events"):
            if _has_table(connection, table) and _has_any_rows(connection, table):
                raise RuntimeError("0007 downgrade is destructive and requires explicit manual recovery approval when lifecycle data exists.")
        if _has_table(connection, "workspaces") and (
            connection.execute(text("SELECT 1 FROM workspaces WHERE purged_at IS NOT NULL OR purge_request_id IS NOT NULL LIMIT 1")).fetchone()
            if _has_column(connection, "workspaces", "purged_at") and _has_column(connection, "workspaces", "purge_request_id")
            else False
        ):
            raise RuntimeError("0007 downgrade is blocked while terminal workspace markers exist.")

    if db.engine.dialect.name == "postgresql":
        with db.engine.begin() as connection:
            pre_downgrade_fks = _postgres_foreign_key_signatures(connection, "workspaces")
            if pre_downgrade_fks.count(_WORKSPACE_PURGE_REQUEST_FK_SIGNATURE) != 1:
                raise RuntimeError("0007 downgrade requires exactly one purge-request workspace FK.")
            _verify_postgres_upgrade(connection, _remove_one_fk_signature(pre_downgrade_fks, _WORKSPACE_PURGE_REQUEST_FK_SIGNATURE))
            assert_empty_and_unmarked(connection)
            _drop_postgres_workspace_columns(connection)
            for table in ("purge_lifecycle_events", "purge_legal_holds", "workspace_purge_requests"):
                if _has_table(connection, table):
                    connection.execute(text(f"DROP TABLE {table}"))
            _verify_postgres_downgrade(connection, pre_downgrade_fks)
    else:
        with db.engine.connect() as connection:
            _verify_sqlite_upgrade(connection)
            assert_empty_and_unmarked(connection)

            def operation():
                _rebuild_sqlite_workspaces(connection, include_terminal_columns=False)
                for table in ("purge_lifecycle_events", "purge_legal_holds", "workspace_purge_requests"):
                    if _has_table(connection, table):
                        connection.execute(text(f"DROP TABLE {table}"))
                _verify_sqlite_downgrade(connection)

            _sqlite_with_foreign_keys_disabled(connection, operation)
