"""
0004_settings_workspace_constraint
-----------------------------------
Drop the global UNIQUE(key) constraint on the settings table and replace it
with two partial unique indexes:

  1. uq_settings_workspace_key  — UNIQUE(workspace_id, key) WHERE workspace_id IS NOT NULL
     Enforces per-tenant key uniqueness for real workspace rows.

  2. uq_settings_null_workspace_key — UNIQUE(key) WHERE workspace_id IS NULL
     Keeps the old "globally unique key" guarantee for system-level rows
     (e.g. 'db_version') that have no workspace.

Why: migration 0003_workspace_foundation added workspace_id to settings but
left the original UNIQUE(key) constraint in place, preventing two workspaces
from storing the same key (e.g. "spa_name") and breaking tenant isolation.

NULL workspace_id rows (legacy system-wide settings) coexist safely because
PostgreSQL treats NULL != NULL in unique indexes.

Downgrade safety note:
  Restoring UNIQUE(key) on downgrade is only safe when no two rows share the
  same key under different workspace_ids.  The downgrade function checks for
  conflicts first and raises RuntimeError rather than silently deleting data.

Revision chain:
  down_revision: 0003_workspace_foundation
  revision:      0004_settings_workspace_constraint
"""

from sqlalchemy import text

revision = "0004_settings_ws_key"
down_revision = "0003_workspace_foundation"
branch_labels = None
depends_on = None
message = "Replace global UNIQUE(key) on settings with per-workspace composite unique index"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_pg(connection):
    return connection.dialect.name == "postgresql"


def _has_table(connection, table_name):
    if _is_pg(connection):
        row = connection.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = CURRENT_SCHEMA() "
                "  AND table_name = :tname LIMIT 1"
            ),
            {"tname": table_name},
        ).fetchone()
    else:
        row = connection.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:tname LIMIT 1"),
            {"tname": table_name},
        ).fetchone()
    return row is not None


def _has_index(connection, index_name):
    if _is_pg(connection):
        row = connection.execute(
            text("SELECT 1 FROM pg_indexes WHERE indexname = :name"),
            {"name": index_name},
        ).fetchone()
    else:
        row = connection.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='index' AND name=:name"),
            {"name": index_name},
        ).fetchone()
    return row is not None


def _has_unique_constraint(connection, table, constraint_name):
    """Return True if a named UNIQUE constraint exists on *table* (PG only)."""
    if not _is_pg(connection):
        return False
    row = connection.execute(
        text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = CURRENT_SCHEMA() "
            "  AND table_name = :tbl "
            "  AND constraint_name = :name "
            "  AND constraint_type = 'UNIQUE'"
        ),
        {"tbl": table, "name": constraint_name},
    ).fetchone()
    return row is not None


def _find_global_unique_key_constraint(connection):
    """
    Return the name of any UNIQUE constraint on settings(key) ONLY.
    Returns None if not found (PG only; SQLite uses indexes).
    """
    if not _is_pg(connection):
        return None
    rows = connection.execute(
        text(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'settings'
              AND c.contype = 'u'
              AND array_length(c.conkey, 1) = 1
              AND (
                  SELECT attname FROM pg_attribute
                  WHERE attrelid = t.oid AND attnum = c.conkey[1]
              ) = 'key'
            """
        )
    ).fetchall()
    if rows:
        return rows[0][0]
    return None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade():
    from extensions import db
    with db.engine.begin() as connection:
        if not _has_table(connection, "settings"):
            return

        if _is_pg(connection):
            _upgrade_postgresql(connection)
        else:
            _upgrade_sqlite(connection)


def _upgrade_postgresql(connection):
    # 1. Drop the old global UNIQUE(key) constraint (any name).
    old_constraint = _find_global_unique_key_constraint(connection)
    if old_constraint:
        connection.execute(
            text(f'ALTER TABLE settings DROP CONSTRAINT IF EXISTS "{old_constraint}"')
        )

    # 2. Per-workspace unique index: one key per workspace (non-NULL only).
    idx_ws = "uq_settings_workspace_key"
    if not _has_index(connection, idx_ws):
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_settings_workspace_key "
                "ON settings (workspace_id, key) "
                "WHERE workspace_id IS NOT NULL"
            )
        )

    # 3. System-level unique index: key uniqueness for NULL-workspace rows.
    idx_null = "uq_settings_null_workspace_key"
    if not _has_index(connection, idx_null):
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_settings_null_workspace_key "
                "ON settings (key) "
                "WHERE workspace_id IS NULL"
            )
        )


def _upgrade_sqlite(connection):
    """
    SQLite does not support partial unique indexes or DROP CONSTRAINT.
    We create a composite unique index (workspace_id, key) which is the
    closest equivalent; SQLite treats NULL as distinct so multiple NULL
    workspace_id rows with the same key are still allowed.
    """
    # Drop old simple unique index on key if it exists.
    for old_idx in ("settings_key_key", "ix_settings_key", "uq_settings_key"):
        if _has_index(connection, old_idx):
            connection.execute(text(f'DROP INDEX IF EXISTS "{old_idx}"'))

    idx_ws = "uq_settings_workspace_key"
    if not _has_index(connection, idx_ws):
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_settings_workspace_key "
                "ON settings (workspace_id, key)"
            )
        )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade():
    from extensions import db
    with db.engine.begin() as connection:
        if not _has_table(connection, "settings"):
            return

        if _is_pg(connection):
            _downgrade_postgresql(connection)
        else:
            _downgrade_sqlite(connection)


def _downgrade_postgresql(connection):
    """
    Restore UNIQUE(key) only if safe (no duplicate keys across workspaces).
    Raises RuntimeError to prevent silent data corruption.
    """
    conflict_row = connection.execute(
        text(
            "SELECT key, COUNT(*) AS cnt "
            "FROM settings "
            "GROUP BY key "
            "HAVING COUNT(*) > 1 "
            "LIMIT 1"
        )
    ).fetchone()
    if conflict_row:
        raise RuntimeError(
            f"Cannot safely downgrade migration 0004: settings table has "
            f"duplicate key '{conflict_row[0]}' across workspaces. "
            "Remove duplicate rows manually before downgrading."
        )

    # Drop indexes added by upgrade.
    for idx in ("uq_settings_workspace_key", "uq_settings_null_workspace_key"):
        if _has_index(connection, idx):
            connection.execute(text(f"DROP INDEX IF EXISTS {idx}"))

    # Restore original unique constraint.
    if not _has_unique_constraint(connection, "settings", "settings_key_key"):
        connection.execute(
            text("ALTER TABLE settings ADD CONSTRAINT settings_key_key UNIQUE (key)")
        )


def _downgrade_sqlite(connection):
    """SQLite downgrade: drop composite index, restore simple unique index."""
    for idx in ("uq_settings_workspace_key", "uq_settings_null_workspace_key"):
        if _has_index(connection, idx):
            connection.execute(text(f'DROP INDEX IF EXISTS "{idx}"'))

    if not _has_index(connection, "settings_key_key"):
        connection.execute(
            text("CREATE UNIQUE INDEX settings_key_key ON settings (key)")
        )
