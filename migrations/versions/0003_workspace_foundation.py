from sqlalchemy import text

revision = "0003_workspace_foundation"
down_revision = "0002_google_auth_approval"
branch_labels = None
depends_on = None
message = "Workspace foundation tables and nullable workspace scope columns"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_pg(connection):
    return connection.dialect.name == "postgresql"


def _has_table(connection, table_name):
    """Check whether a table exists using a live DB query (no inspector caching)."""
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
    """Check whether a column exists in a table using a live DB query."""
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


def _has_index(connection, index_name):
    """Check whether a named index exists (PostgreSQL only; SQLite skips)."""
    if not _is_pg(connection):
        return False
    row = connection.execute(
        text(
            """
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = CURRENT_SCHEMA()
              AND indexname = :idx
            LIMIT 1
            """
        ),
        {"idx": index_name},
    ).fetchone()
    return row is not None


def _now_expr(connection):
    """Return the SQL expression for current timestamp appropriate to the dialect."""
    return "NOW()" if _is_pg(connection) else "CURRENT_TIMESTAMP"


def _insert_workspace_and_get_id(connection, owner_id):
    """
    Insert a new Default Workspace row and return its auto-generated id.
    Uses RETURNING on PostgreSQL and lastrowid on SQLite.
    """
    now = _now_expr(connection)
    sql = text(
        f"""
        INSERT INTO workspaces (name, slug, status, created_by_id, notes, created_at, updated_at)
        VALUES (
            'Default Spa',
            'default-spa',
            'active',
            :created_by_id,
            'Default workspace backfilled during 0003_workspace_foundation migration.',
            {now},
            {now}
        )
        """ + ("RETURNING id" if _is_pg(connection) else "")
    )
    result = connection.execute(sql, {"created_by_id": owner_id})
    if _is_pg(connection):
        return result.fetchone()[0]
    else:
        return result.lastrowid


def _insert_workspace_member(connection, workspace_id, user_id, role):
    """Insert a workspace_member row, ignoring duplicates cross-dialect."""
    now = _now_expr(connection)
    if _is_pg(connection):
        sql = text(
            f"""
            INSERT INTO workspace_members
                (workspace_id, user_id, role, status, joined_at, created_at, updated_at)
            VALUES
                (:wid, :uid, :role, 'active', {now}, {now}, {now})
            ON CONFLICT (workspace_id, user_id) DO NOTHING
            """
        )
    else:
        sql = text(
            f"""
            INSERT OR IGNORE INTO workspace_members
                (workspace_id, user_id, role, status, joined_at, created_at, updated_at)
            VALUES
                (:wid, :uid, :role, 'active', {now}, {now}, {now})
            """
        )
    connection.execute(sql, {"wid": workspace_id, "uid": user_id, "role": role})


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade():
    from extensions import db

    with db.engine.begin() as connection:
        _create_workspaces(connection)
        _create_workspace_members(connection)
        _add_workspace_id_to_business_tables(connection)
        _backfill_default_workspace(connection)


def _create_workspaces(connection):
    """Create the workspaces table if it does not yet exist."""
    if _has_table(connection, "workspaces"):
        return  # already exists (local drift or db.create_all() in 0001_baseline)

    now = _now_expr(connection)
    if _is_pg(connection):
        pk_type = "SERIAL PRIMARY KEY"
    else:
        pk_type = "INTEGER PRIMARY KEY AUTOINCREMENT"

    connection.execute(
        text(
            f"""
            CREATE TABLE workspaces (
                id          {pk_type},
                name        VARCHAR(150) NOT NULL,
                slug        VARCHAR(150) NOT NULL UNIQUE,
                status      VARCHAR(20)  NOT NULL DEFAULT 'active',
                created_by_id INTEGER     REFERENCES users (id) ON DELETE SET NULL,
                notes       TEXT,
                created_at  TIMESTAMP    NOT NULL DEFAULT {now},
                updated_at  TIMESTAMP    NOT NULL DEFAULT {now}
            )
            """
        )
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_workspaces_slug ON workspaces (slug)")
    )
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_workspaces_status ON workspaces (status)")
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_workspaces_created_at ON workspaces (created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_workspaces_created_by_id ON workspaces (created_by_id)"
        )
    )


def _create_workspace_members(connection):
    """Create the workspace_members table if it does not yet exist."""
    if _has_table(connection, "workspace_members"):
        return  # already exists

    now = _now_expr(connection)
    if _is_pg(connection):
        pk_type = "SERIAL PRIMARY KEY"
        unique_constraint = "CONSTRAINT uq_workspace_members_workspace_user UNIQUE (workspace_id, user_id)"
    else:
        pk_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
        unique_constraint = "UNIQUE (workspace_id, user_id)"

    connection.execute(
        text(
            f"""
            CREATE TABLE workspace_members (
                id             {pk_type},
                workspace_id   INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
                user_id        INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                role           VARCHAR(20) NOT NULL DEFAULT 'staff',
                status         VARCHAR(20) NOT NULL DEFAULT 'active',
                invited_by_id  INTEGER REFERENCES users (id) ON DELETE SET NULL,
                joined_at      TIMESTAMP,
                created_at     TIMESTAMP NOT NULL DEFAULT {now},
                updated_at     TIMESTAMP NOT NULL DEFAULT {now},
                {unique_constraint}
            )
            """
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_workspace_members_workspace_id"
            " ON workspace_members (workspace_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_workspace_members_user_id"
            " ON workspace_members (user_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_workspace_members_workspace_role"
            " ON workspace_members (workspace_id, role)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_workspace_members_workspace_status"
            " ON workspace_members (workspace_id, status)"
        )
    )


def _add_workspace_id_to_business_tables(connection):
    """
    Add nullable workspace_id column + FK + index to workspace-scoped tables.
    Nullable at this phase so existing data is not broken and application code
    can be updated incrementally in subsequent tasks (6.5.4 / 6.5.5).
    """
    scoped_tables = [
        "customers",
        "services",
        "appointments",
        "invoices",
        "invoice_details",
        "activity_logs",
        "settings",
    ]

    for table in scoped_tables:
        if not _has_table(connection, table):
            continue

        # --- add column ---
        if not _has_column(connection, table, "workspace_id"):
            if _is_pg(connection):
                connection.execute(
                    text(
                        f"ALTER TABLE {table}"
                        " ADD COLUMN workspace_id INTEGER REFERENCES workspaces (id) ON DELETE SET NULL"
                    )
                )
            else:
                # SQLite: FK references not enforced unless PRAGMA foreign_keys=ON,
                # but we still declare it for correctness.
                connection.execute(
                    text(
                        f"ALTER TABLE {table}"
                        " ADD COLUMN workspace_id INTEGER REFERENCES workspaces (id)"
                    )
                )

        # --- add index (idempotent; PostgreSQL uses pg_indexes guard, SQLite allows re-create IF NOT EXISTS) ---
        idx_name = f"ix_{table}_workspace_id"
        if not _has_index(connection, idx_name):
            connection.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {idx_name}"
                    f" ON {table} (workspace_id)"
                )
            )


def _backfill_default_workspace(connection):
    """
    Ensure a Default Workspace exists and backfill existing business data.

    Strategy (safe / idempotent):
    1. Create Default Workspace row if slug 'default-spa' doesn't exist yet.
    2. Assign created_by_id to the first OWNER user found (if any).
    3. Backfill workspace_id on all business rows that are currently NULL.
    4. Create workspace_member rows for all existing active users,
       skipping duplicates (ON CONFLICT / INSERT OR IGNORE).
    """
    # ---- 1. Locate or create default workspace --------------------------
    row = connection.execute(
        text("SELECT id FROM workspaces WHERE slug = 'default-spa' LIMIT 1")
    ).fetchone()

    if row:
        workspace_id = row[0]
    else:
        # Find the first OWNER user for created_by_id
        owner_row = connection.execute(
            text(
                "SELECT id FROM users"
                " WHERE role = 'OWNER' AND is_active = :active"
                " ORDER BY id ASC LIMIT 1"
            ),
            {"active": True},
        ).fetchone()
        owner_id = owner_row[0] if owner_row else None
        workspace_id = _insert_workspace_and_get_id(connection, owner_id)

    # ---- 2. Backfill workspace_id on NULL business rows -----------------
    scoped_tables = [
        "customers",
        "services",
        "appointments",
        "invoices",
        "invoice_details",
        "activity_logs",
        "settings",
    ]
    for table in scoped_tables:
        if not _has_table(connection, table):
            continue
        if not _has_column(connection, table, "workspace_id"):
            continue
        connection.execute(
            text(
                f"UPDATE {table} SET workspace_id = :wid WHERE workspace_id IS NULL"
            ),
            {"wid": workspace_id},
        )

    # ---- 3. Create workspace_members for existing active users ----------
    role_map = {
        "OWNER": "owner",
        "ADMIN": "admin",
        "STAFF": "staff",
    }
    users = connection.execute(
        text(
            "SELECT id, role FROM users WHERE is_active = :active ORDER BY id ASC"
        ),
        {"active": True},
    ).fetchall()
    for user_row in users:
        user_id = user_row[0]
        global_role = (user_row[1] or "STAFF").upper()
        ws_role = role_map.get(global_role, "staff")
        _insert_workspace_member(connection, workspace_id, user_id, ws_role)


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade():
    from extensions import db

    with db.engine.begin() as connection:
        _remove_workspace_id_from_business_tables(connection)
        _drop_workspace_members(connection)
        _drop_workspaces(connection)


def _remove_workspace_id_from_business_tables(connection):
    scoped_tables = [
        "settings",
        "activity_logs",
        "invoice_details",
        "invoices",
        "appointments",
        "services",
        "customers",
    ]
    for table in scoped_tables:
        if not _has_table(connection, table):
            continue
        idx_name = f"ix_{table}_workspace_id"
        if _has_index(connection, idx_name):
            connection.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
        if _has_column(connection, table, "workspace_id"):
            if _is_pg(connection):
                connection.execute(
                    text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS workspace_id")
                )
            # SQLite does not support DROP COLUMN; skip on SQLite (dev/test only).


def _drop_workspace_members(connection):
    for idx in [
        "ix_workspace_members_workspace_status",
        "ix_workspace_members_workspace_role",
        "ix_workspace_members_user_id",
        "ix_workspace_members_workspace_id",
    ]:
        if _has_index(connection, idx):
            connection.execute(text(f"DROP INDEX IF EXISTS {idx}"))
    if _has_table(connection, "workspace_members"):
        connection.execute(text("DROP TABLE workspace_members"))


def _drop_workspaces(connection):
    for idx in [
        "ix_workspaces_created_by_id",
        "ix_workspaces_created_at",
        "ix_workspaces_status",
        "ix_workspaces_slug",
    ]:
        if _has_index(connection, idx):
            connection.execute(text(f"DROP INDEX IF EXISTS {idx}"))
    if _has_table(connection, "workspaces"):
        connection.execute(text("DROP TABLE workspaces"))
