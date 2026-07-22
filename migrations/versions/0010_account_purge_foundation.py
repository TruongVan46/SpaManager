"""Create the schema foundation for account purge Model B.

This revision is deliberately schema-only.  It does not anonymize users,
revoke sessions, create reservations, or execute any purge behavior.
"""

from sqlalchemy import inspect, text


revision = "0010_account_purge_foundation"
down_revision = "0009_immediate_purge_eligibility"
branch_labels = None
depends_on = None
message = "Create account purge foundation schema"

USER_COLUMNS = {
    "account_purge_state",
    "account_purged_at",
    "account_purge_request_id",
    "session_revocation_version",
    "session_revoked_at",
    "account_purge_version",
}
NEW_TABLES = (
    "user_creation_provenance",
    "account_purge_requests",
    "account_purge_lifecycle_events",
    "account_purge_legal_holds",
    "account_purge_execution_authorizations",
    "account_identity_reservations",
    "account_purge_avatar_cleanups",
)


def _require_postgresql(connection):
    if connection.dialect.name != "postgresql":
        raise RuntimeError("0010 requires PostgreSQL; refusing non-PostgreSQL migration execution.")


def _columns(connection, table_name):
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _has_table(connection, table_name):
    return inspect(connection).has_table(table_name)


def _assert_pristine(connection):
    if not _has_table(connection, "users") or not _has_table(connection, "workspaces"):
        raise RuntimeError("0010 required users/workspaces schema is missing.")
    existing = [table for table in NEW_TABLES if _has_table(connection, table)]
    if existing:
        raise RuntimeError(f"0010 target tables already exist: {', '.join(existing)}")
    if USER_COLUMNS.intersection(_columns(connection, "users")):
        raise RuntimeError("0010 target user columns already exist; refusing ambiguous upgrade.")


def _add_user_columns(connection):
    statements = (
        "ALTER TABLE users ADD COLUMN account_purge_state VARCHAR(30) NOT NULL DEFAULT 'NOT_PURGED'",
        "ALTER TABLE users ADD COLUMN account_purged_at TIMESTAMPTZ",
        "ALTER TABLE users ADD COLUMN account_purge_request_id INTEGER",
        "ALTER TABLE users ADD COLUMN session_revocation_version INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN session_revoked_at TIMESTAMPTZ",
        "ALTER TABLE users ADD COLUMN account_purge_version INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD CONSTRAINT ck_users_account_purge_state CHECK (account_purge_state IN ('NOT_PURGED', 'PURGED_TOMBSTONE'))",
        "ALTER TABLE users ADD CONSTRAINT ck_users_account_purged_at CHECK (account_purge_state <> 'PURGED_TOMBSTONE' OR account_purged_at IS NOT NULL)",
        "ALTER TABLE users ADD CONSTRAINT ck_users_session_revocation_version CHECK (session_revocation_version >= 0)",
        "ALTER TABLE users ADD CONSTRAINT ck_users_account_purge_version CHECK (account_purge_version >= 0)",
    )
    for statement in statements:
        connection.execute(text(statement))


def _create_tables(connection):
    connection.execute(text("""
        CREATE TABLE user_creation_provenance (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE RESTRICT,
            created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_in_workspace_id INTEGER REFERENCES workspaces(id) ON DELETE SET NULL,
            creation_source VARCHAR(40) NOT NULL,
            created_role VARCHAR(50),
            provenance_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_user_creation_provenance_source CHECK (creation_source IN ('WORKSPACE_OWNER', 'WORKSPACE_ADMIN', 'SYSTEM_BOOTSTRAP', 'APPROVAL_BOOTSTRAP', 'GOOGLE_OAUTH', 'LEGACY_UNKNOWN')),
            CONSTRAINT ck_user_creation_provenance_version CHECK (provenance_version > 0)
        )
    """))
    connection.execute(text("""
        CREATE TABLE account_purge_requests (
            id SERIAL PRIMARY KEY,
            target_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            managing_workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
            target_provenance_id INTEGER REFERENCES user_creation_provenance(id) ON DELETE RESTRICT,
            state VARCHAR(30) NOT NULL DEFAULT 'REQUESTED',
            reason TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            requester_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            requester_name_snapshot VARCHAR(100) NOT NULL,
            requester_email_snapshot VARCHAR(255),
            requester_role_snapshot VARCHAR(50) NOT NULL,
            requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            approver_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            approver_name_snapshot VARCHAR(100),
            approver_email_snapshot VARCHAR(255),
            approver_role_snapshot VARCHAR(50),
            approved_at TIMESTAMPTZ,
            rejected_at TIMESTAMPTZ,
            rejection_reason TEXT,
            executor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            executor_name_snapshot VARCHAR(100),
            executor_email_snapshot VARCHAR(255),
            executor_role_snapshot VARCHAR(50),
            execution_authorized_at TIMESTAMPTZ,
            execution_started_at TIMESTAMPTZ,
            execution_completed_at TIMESTAMPTZ,
            eligible_at TIMESTAMPTZ,
            cancelled_at TIMESTAMPTZ,
            cancellation_reason TEXT,
            failure_code VARCHAR(80),
            failure_detail_safe TEXT,
            outcome_unknown_at TIMESTAMPTZ,
            terminal_at TIMESTAMPTZ,
            target_username_snapshot VARCHAR(100),
            target_email_snapshot VARCHAR(255),
            target_role_snapshot VARCHAR(50) NOT NULL,
            target_auth_provider_snapshot VARCHAR(50),
            CONSTRAINT ck_account_purge_request_state CHECK (state IN ('REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED', 'EXECUTING', 'SUCCEEDED', 'FAILED', 'OUTCOME_UNKNOWN')),
            CONSTRAINT ck_account_purge_request_version CHECK (version > 0),
            CONSTRAINT ck_account_purge_request_requester_target CHECK (requester_id IS NULL OR requester_id <> target_user_id),
            CONSTRAINT ck_account_purge_request_actor_separation CHECK (
                (requester_id IS NULL OR approver_id IS NULL OR requester_id <> approver_id)
                AND (requester_id IS NULL OR executor_id IS NULL OR requester_id <> executor_id)
                AND (approver_id IS NULL OR executor_id IS NULL OR approver_id <> executor_id)
            )
        )
    """))
    connection.execute(text(
        "ALTER TABLE users ADD CONSTRAINT fk_users_account_purge_request "
        "FOREIGN KEY (account_purge_request_id) REFERENCES account_purge_requests(id) ON DELETE RESTRICT"
    ))
    connection.execute(text("""
        CREATE TABLE account_purge_lifecycle_events (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES account_purge_requests(id) ON DELETE RESTRICT,
            target_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            managing_workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
            event_type VARCHAR(50) NOT NULL,
            from_state VARCHAR(30),
            to_state VARCHAR(30),
            actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            actor_name_snapshot VARCHAR(100) NOT NULL,
            actor_email_snapshot VARCHAR(255),
            actor_role_snapshot VARCHAR(50),
            safe_detail TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    connection.execute(text("""
        CREATE TABLE account_purge_legal_holds (
            id SERIAL PRIMARY KEY,
            target_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            managing_workspace_id INTEGER REFERENCES workspaces(id) ON DELETE SET NULL,
            request_id INTEGER REFERENCES account_purge_requests(id) ON DELETE SET NULL,
            state VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
            reason TEXT NOT NULL,
            placed_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            placed_by_name_snapshot VARCHAR(100) NOT NULL,
            placed_by_email_snapshot VARCHAR(255),
            placed_by_role_snapshot VARCHAR(50),
            placed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            released_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            released_by_name_snapshot VARCHAR(100),
            released_by_email_snapshot VARCHAR(255),
            released_by_role_snapshot VARCHAR(50),
            released_at TIMESTAMPTZ,
            release_reason TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT ck_account_purge_legal_hold_state CHECK (state IN ('ACTIVE', 'RELEASED')),
            CONSTRAINT ck_account_purge_legal_hold_release CHECK (state <> 'RELEASED' OR released_at IS NOT NULL),
            CONSTRAINT ck_account_purge_legal_hold_version CHECK (version > 0)
        )
    """))
    connection.execute(text("""
        CREATE TABLE account_purge_execution_authorizations (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL UNIQUE REFERENCES account_purge_requests(id) ON DELETE RESTRICT,
            actor_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            method VARCHAR(30) NOT NULL DEFAULT 'local_password',
            generation INTEGER NOT NULL DEFAULT 1,
            state VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
            nonce_hash VARCHAR(64),
            authenticated_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            consumed_at TIMESTAMPTZ,
            claimed_at TIMESTAMPTZ,
            service_started_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            revocation_reason VARCHAR(80),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_account_purge_auth_method CHECK (method IN ('local_password')),
            CONSTRAINT ck_account_purge_auth_generation CHECK (generation > 0),
            CONSTRAINT ck_account_purge_auth_state CHECK (state IN ('ACTIVE', 'CLAIMED', 'SERVICE_STARTED', 'CONSUMED_SUCCESS', 'REVOKED', 'CLAIMED_UNRESOLVED'))
        )
    """))
    connection.execute(text("""
        CREATE TABLE account_identity_reservations (
            id SERIAL PRIMARY KEY,
            target_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            request_id INTEGER NOT NULL REFERENCES account_purge_requests(id) ON DELETE RESTRICT,
            identity_type VARCHAR(30) NOT NULL,
            identity_fingerprint VARCHAR(128) NOT NULL,
            fingerprint_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            released_at TIMESTAMPTZ,
            release_reason TEXT,
            CONSTRAINT ck_account_identity_type CHECK (identity_type IN ('USERNAME', 'EMAIL', 'GOOGLE_SUBJECT')),
            CONSTRAINT ck_account_identity_fingerprint_version CHECK (fingerprint_version > 0)
        )
    """))
    connection.execute(text("""
        CREATE TABLE account_purge_avatar_cleanups (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL UNIQUE REFERENCES account_purge_requests(id) ON DELETE RESTRICT,
            target_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            relative_path_snapshot VARCHAR(255),
            ownership_proven BOOLEAN NOT NULL DEFAULT FALSE,
            state VARCHAR(30) NOT NULL DEFAULT 'NOT_REQUIRED',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_attempt_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            safe_error_code VARCHAR(80),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_account_avatar_cleanup_state CHECK (state IN ('NOT_REQUIRED', 'PENDING', 'COMPLETED', 'FAILED_RETRYABLE', 'FAILED_FINAL')),
            CONSTRAINT ck_account_avatar_cleanup_attempts CHECK (attempt_count >= 0),
            CONSTRAINT ck_account_avatar_cleanup_completed CHECK (state <> 'COMPLETED' OR completed_at IS NOT NULL)
        )
    """))


def _create_indexes(connection):
    statements = (
        "CREATE INDEX ix_user_creation_provenance_workspace_source ON user_creation_provenance (created_in_workspace_id, creation_source)",
        "CREATE INDEX ix_account_purge_requests_target_state ON account_purge_requests (target_user_id, state)",
        "CREATE INDEX ix_account_purge_requests_workspace_state ON account_purge_requests (managing_workspace_id, state)",
        "CREATE INDEX ix_account_purge_requests_requester ON account_purge_requests (requester_id)",
        "CREATE INDEX ix_account_purge_requests_approver ON account_purge_requests (approver_id)",
        "CREATE INDEX ix_account_purge_requests_executor ON account_purge_requests (executor_id)",
        "CREATE UNIQUE INDEX uq_account_purge_requests_active_target ON account_purge_requests (target_user_id) WHERE state NOT IN ('REJECTED', 'CANCELLED', 'SUCCEEDED', 'FAILED', 'OUTCOME_UNKNOWN')",
        "CREATE INDEX ix_account_purge_lifecycle_request_created ON account_purge_lifecycle_events (request_id, created_at)",
        "CREATE INDEX ix_account_purge_legal_holds_target_state ON account_purge_legal_holds (target_user_id, state)",
        "CREATE INDEX ix_account_purge_legal_holds_workspace_state ON account_purge_legal_holds (managing_workspace_id, state)",
        "CREATE INDEX ix_account_purge_legal_holds_request ON account_purge_legal_holds (request_id)",
        "CREATE INDEX ix_account_purge_auth_actor_state ON account_purge_execution_authorizations (actor_user_id, state)",
        "CREATE INDEX ix_account_identity_reservations_lookup ON account_identity_reservations (identity_type, identity_fingerprint)",
        "CREATE UNIQUE INDEX uq_account_identity_reservations_active ON account_identity_reservations (identity_type, identity_fingerprint) WHERE released_at IS NULL",
        "CREATE INDEX ix_account_purge_avatar_cleanups_state ON account_purge_avatar_cleanups (state, target_user_id)",
    )
    for statement in statements:
        connection.execute(text(statement))


def _assert_upgrade(connection):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if not set(NEW_TABLES).issubset(tables):
        raise RuntimeError("0010 did not create the complete account purge foundation.")
    if not USER_COLUMNS.issubset(_columns(connection, "users")):
        raise RuntimeError("0010 did not add the complete user terminal-state foundation.")


def upgrade():
    from extensions import db

    with db.engine.begin() as connection:
        _require_postgresql(connection)
        _assert_pristine(connection)
        _add_user_columns(connection)
        _create_tables(connection)
        _create_indexes(connection)
        _assert_upgrade(connection)


def _assert_empty(connection):
    for table_name in NEW_TABLES:
        if connection.execute(text(f"SELECT 1 FROM {table_name} LIMIT 1")).first() is not None:
            raise RuntimeError("0010 downgrade requires all account foundation tables to be empty.")
    user_row = connection.execute(text(
        "SELECT 1 FROM users WHERE account_purge_state <> 'NOT_PURGED' "
        "OR account_purged_at IS NOT NULL OR account_purge_request_id IS NOT NULL "
        "OR session_revocation_version <> 0 OR session_revoked_at IS NOT NULL "
        "OR account_purge_version <> 0 LIMIT 1"
    )).first()
    if user_row is not None:
        raise RuntimeError("0010 downgrade refuses to remove populated user foundation metadata.")


def downgrade():
    from extensions import db

    with db.engine.begin() as connection:
        _require_postgresql(connection)
        _assert_empty(connection)
        connection.execute(text("ALTER TABLE users DROP CONSTRAINT fk_users_account_purge_request"))
        for table_name in reversed(NEW_TABLES):
            connection.execute(text(f"DROP TABLE {table_name}"))
        for constraint_name in (
            "ck_users_account_purge_state",
            "ck_users_account_purged_at",
            "ck_users_session_revocation_version",
            "ck_users_account_purge_version",
        ):
            connection.execute(text(f"ALTER TABLE users DROP CONSTRAINT {constraint_name}"))
        for column_name in reversed(sorted(USER_COLUMNS)):
            connection.execute(text(f"ALTER TABLE users DROP COLUMN {column_name}"))
