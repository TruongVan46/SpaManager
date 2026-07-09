from sqlalchemy import text

revision = "0005_member_soft_delete"
down_revision = "0004_settings_ws_key"
branch_labels = None
depends_on = None
message = "Add soft delete fields (removed_at, removed_by_id, removal_reason) to workspace_members table"


def _is_pg(connection):
    return connection.dialect.name == "postgresql"


def _has_table(connection, table_name):
    if _is_pg(connection):
        row = connection.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = CURRENT_SCHEMA()
                  AND table_name = :tname
                LIMIT 1
                """
            ),
            {"tname": table_name},
        ).fetchone()
    else:
        row = connection.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name = :tname LIMIT 1"
            ),
            {"tname": table_name},
        ).fetchone()
    return row is not None


def _has_column(connection, table_name, column_name):
    if not _has_table(connection, table_name):
        return False
    if _is_pg(connection):
        row = connection.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = CURRENT_SCHEMA()
                  AND table_name = :tname
                  AND column_name = :cname
                LIMIT 1
                """
            ),
            {"tname": table_name, "cname": column_name},
        ).fetchone()
    else:
        rows = connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        row = next((r for r in rows if r[1] == column_name), None)
    return row is not None


def upgrade():
    from extensions import db

    with db.engine.begin() as connection:
        # 1. removed_at
        if not _has_column(connection, "workspace_members", "removed_at"):
            if _is_pg(connection):
                connection.execute(
                    text("ALTER TABLE workspace_members ADD COLUMN removed_at TIMESTAMP NULL")
                )
            else:
                connection.execute(
                    text("ALTER TABLE workspace_members ADD COLUMN removed_at TIMESTAMP")
                )

        # 2. removed_by_id
        if not _has_column(connection, "workspace_members", "removed_by_id"):
            if _is_pg(connection):
                connection.execute(
                    text(
                        "ALTER TABLE workspace_members"
                        " ADD COLUMN removed_by_id INTEGER REFERENCES users (id) ON DELETE SET NULL NULL"
                    )
                )
            else:
                connection.execute(
                    text(
                        "ALTER TABLE workspace_members"
                        " ADD COLUMN removed_by_id INTEGER REFERENCES users (id)"
                    )
                )

        # 3. removal_reason
        if not _has_column(connection, "workspace_members", "removal_reason"):
            if _is_pg(connection):
                connection.execute(
                    text("ALTER TABLE workspace_members ADD COLUMN removal_reason VARCHAR(255) NULL")
                )
            else:
                connection.execute(
                    text("ALTER TABLE workspace_members ADD COLUMN removal_reason VARCHAR(255)")
                )


def downgrade():
    from extensions import db

    with db.engine.begin() as connection:
        if _is_pg(connection):
            if _has_column(connection, "workspace_members", "removal_reason"):
                connection.execute(
                    text("ALTER TABLE workspace_members DROP COLUMN IF EXISTS removal_reason")
                )
            if _has_column(connection, "workspace_members", "removed_by_id"):
                connection.execute(
                    text("ALTER TABLE workspace_members DROP COLUMN IF EXISTS removed_by_id")
                )
            if _has_column(connection, "workspace_members", "removed_at"):
                connection.execute(
                    text("ALTER TABLE workspace_members DROP COLUMN IF EXISTS removed_at")
                )
        # SQLite does not support DROP COLUMN easily; skip on SQLite
