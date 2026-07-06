from sqlalchemy import text
from sqlalchemy import inspect

revision = "0002_google_auth_approval"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None
message = "Google auth approval schema"


def _existing_user_columns(connection):
    try:
        inspector = inspect(connection)
        return {column["name"] for column in inspector.get_columns("users")}
    except Exception:
        return set()


def _constraint_exists(connection, constraint_name):
    if connection.dialect.name != "postgresql":
        return False
    row = connection.execute(
        text(
            """
            SELECT 1
            FROM information_schema.table_constraints
            WHERE table_schema = CURRENT_SCHEMA()
              AND table_name = 'users'
              AND constraint_name = :constraint_name
            LIMIT 1
            """
        ),
        {"constraint_name": constraint_name},
    ).fetchone()
    return row is not None


def upgrade():
    from extensions import db

    with db.engine.begin() as connection:
        existing_columns = _existing_user_columns(connection)
        if connection.dialect.name == "postgresql":
            if "approval_status" not in existing_columns:
                connection.execute(
                    text(
                        """
                        ALTER TABLE users
                        ADD COLUMN approval_status VARCHAR(20) NOT NULL DEFAULT 'active'
                        """
                    )
                )
            if "approved_by_id" not in existing_columns:
                connection.execute(
                    text(
                        """
                        ALTER TABLE users
                        ADD COLUMN approved_by_id INTEGER
                        """
                    )
                )
            if "approved_at" not in existing_columns:
                connection.execute(
                    text(
                        """
                        ALTER TABLE users
                        ADD COLUMN approved_at TIMESTAMP
                        """
                    )
                )
            if not _constraint_exists(connection, "fk_users_approved_by_id"):
                connection.execute(
                    text(
                        """
                        ALTER TABLE users
                        ADD CONSTRAINT fk_users_approved_by_id
                        FOREIGN KEY (approved_by_id) REFERENCES users (id) ON DELETE SET NULL
                        """
                    )
                )
        else:
            if "approval_status" not in existing_columns:
                connection.execute(
                    text(
                        """
                        ALTER TABLE users
                        ADD COLUMN approval_status VARCHAR(20) NOT NULL DEFAULT 'active'
                        """
                    )
                )
            if "approved_by_id" not in existing_columns:
                connection.execute(
                    text(
                        """
                        ALTER TABLE users
                        ADD COLUMN approved_by_id INTEGER
                        """
                    )
                )
            if "approved_at" not in existing_columns:
                connection.execute(
                    text(
                        """
                        ALTER TABLE users
                        ADD COLUMN approved_at DATETIME
                        """
                    )
                )
        connection.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_users_approval_status
                ON users (approval_status)
                """
            )
        )


def downgrade():
    from extensions import db

    with db.engine.begin() as connection:
        existing_columns = _existing_user_columns(connection)
        connection.execute(text("DROP INDEX IF EXISTS ix_users_approval_status"))
        if connection.dialect.name == "postgresql" and _constraint_exists(connection, "fk_users_approved_by_id"):
            connection.execute(text("ALTER TABLE users DROP CONSTRAINT fk_users_approved_by_id"))
        if "approved_at" in existing_columns:
            drop_sql = "ALTER TABLE users DROP COLUMN IF EXISTS approved_at" if connection.dialect.name == "postgresql" else "ALTER TABLE users DROP COLUMN approved_at"
            connection.execute(text(drop_sql))
        if "approved_by_id" in existing_columns:
            drop_sql = "ALTER TABLE users DROP COLUMN IF EXISTS approved_by_id" if connection.dialect.name == "postgresql" else "ALTER TABLE users DROP COLUMN approved_by_id"
            connection.execute(text(drop_sql))
        if "approval_status" in existing_columns:
            drop_sql = "ALTER TABLE users DROP COLUMN IF EXISTS approval_status" if connection.dialect.name == "postgresql" else "ALTER TABLE users DROP COLUMN approval_status"
            connection.execute(text(drop_sql))
