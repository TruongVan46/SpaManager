from sqlalchemy import text

revision = "0006_user_ws_soft_delete"
down_revision = "0005_member_soft_delete"
branch_labels = None
depends_on = None
message = "Add soft delete fields (deleted_at, deleted_by_id, deletion_reason) to users and workspaces tables"


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
        # ---- 1. users table ----
        if _has_table(connection, "users"):
            # deleted_at
            if not _has_column(connection, "users", "deleted_at"):
                if _is_pg(connection):
                    connection.execute(
                        text("ALTER TABLE users ADD COLUMN deleted_at TIMESTAMP NULL")
                    )
                else:
                    connection.execute(
                        text("ALTER TABLE users ADD COLUMN deleted_at TIMESTAMP")
                    )

            # deleted_by_id
            if not _has_column(connection, "users", "deleted_by_id"):
                if _is_pg(connection):
                    connection.execute(
                        text(
                            "ALTER TABLE users"
                            " ADD COLUMN deleted_by_id INTEGER REFERENCES users (id) ON DELETE SET NULL"
                        )
                    )
                else:
                    connection.execute(
                        text(
                            "ALTER TABLE users"
                            " ADD COLUMN deleted_by_id INTEGER REFERENCES users (id)"
                        )
                    )

            # deletion_reason
            if not _has_column(connection, "users", "deletion_reason"):
                if _is_pg(connection):
                    connection.execute(
                        text("ALTER TABLE users ADD COLUMN deletion_reason VARCHAR(255) NULL")
                    )
                else:
                    connection.execute(
                        text("ALTER TABLE users ADD COLUMN deletion_reason VARCHAR(255)")
                    )

        # ---- 2. workspaces table ----
        if _has_table(connection, "workspaces"):
            # deleted_at
            if not _has_column(connection, "workspaces", "deleted_at"):
                if _is_pg(connection):
                    connection.execute(
                        text("ALTER TABLE workspaces ADD COLUMN deleted_at TIMESTAMP NULL")
                    )
                else:
                    connection.execute(
                        text("ALTER TABLE workspaces ADD COLUMN deleted_at TIMESTAMP")
                    )

            # deleted_by_id
            if not _has_column(connection, "workspaces", "deleted_by_id"):
                if _is_pg(connection):
                    connection.execute(
                        text(
                            "ALTER TABLE workspaces"
                            " ADD COLUMN deleted_by_id INTEGER REFERENCES users (id) ON DELETE SET NULL"
                        )
                    )
                else:
                    connection.execute(
                        text(
                            "ALTER TABLE workspaces"
                            " ADD COLUMN deleted_by_id INTEGER REFERENCES users (id)"
                        )
                    )

            # deletion_reason
            if not _has_column(connection, "workspaces", "deletion_reason"):
                if _is_pg(connection):
                    connection.execute(
                        text("ALTER TABLE workspaces ADD COLUMN deletion_reason VARCHAR(255) NULL")
                    )
                else:
                    connection.execute(
                        text("ALTER TABLE workspaces ADD COLUMN deletion_reason VARCHAR(255)")
                    )


def downgrade():
    from extensions import db

    with db.engine.begin() as connection:
        if _is_pg(connection):
            # workspaces table columns
            if _has_table(connection, "workspaces"):
                if _has_column(connection, "workspaces", "deletion_reason"):
                    connection.execute(text("ALTER TABLE workspaces DROP COLUMN IF EXISTS deletion_reason"))
                if _has_column(connection, "workspaces", "deleted_by_id"):
                    connection.execute(text("ALTER TABLE workspaces DROP COLUMN IF EXISTS deleted_by_id"))
                if _has_column(connection, "workspaces", "deleted_at"):
                    connection.execute(text("ALTER TABLE workspaces DROP COLUMN IF EXISTS deleted_at"))

            # users table columns
            if _has_table(connection, "users"):
                if _has_column(connection, "users", "deletion_reason"):
                    connection.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS deletion_reason"))
                if _has_column(connection, "users", "deleted_by_id"):
                    connection.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS deleted_by_id"))
                if _has_column(connection, "users", "deleted_at"):
                    connection.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS deleted_at"))
        # SQLite drop column skipped
