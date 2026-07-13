from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Text, text
from sqlalchemy.orm import registry


_registry = registry()
metadata = MetaData()


workspace_terminal_state_table = Table(
    "workspaces",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("deleted_at", DateTime),
    Column("deleted_by_id", Integer),
    Column("purged_at", DateTime),
    Column("purge_request_id", Integer),
)


workspace_purge_requests_table = Table(
    "workspace_purge_requests",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("lifecycle_id", String(36), nullable=False),
    Column("workspace_id", Integer, nullable=False),
    Column("purge_type", String(30), nullable=False, server_default=text("'workspace'")),
    Column("status", String(30), nullable=False, server_default=text("'REQUESTED'")),
    Column("target_deleted_at", DateTime, nullable=False),
    Column("target_deleted_by_id", Integer),
    Column("target_deleted_by_snapshot", String(100), nullable=False),
    Column("target_workspace_name", String(150), nullable=False),
    Column("target_workspace_slug", String(150), nullable=False),
    Column("requested_by_id", Integer),
    Column("requested_by_snapshot", String(100), nullable=False),
    Column("requested_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("eligible_at", DateTime, nullable=False),
    Column("retention_policy_version", String(50), nullable=False),
    Column("approved_by_id", Integer),
    Column("approved_by_snapshot", String(100)),
    Column("approved_at", DateTime),
    Column("rejected_by_id", Integer),
    Column("rejected_by_snapshot", String(100)),
    Column("rejected_at", DateTime),
    Column("rejection_reason", Text),
    Column("cancelled_by_id", Integer),
    Column("cancelled_by_snapshot", String(100)),
    Column("cancelled_at", DateTime),
    Column("cancellation_reason", Text),
    Column("invalidated_at", DateTime),
    Column("invalidated_by_restore", Boolean, nullable=False, server_default=text("FALSE")),
    Column("invalidation_reason", String(255)),
    Column("execution_triggered_by_id", Integer),
    Column("execution_trigger_snapshot", String(100)),
    Column("execution_started_at", DateTime),
    Column("completed_at", DateTime),
    Column("failed_at", DateTime),
    Column("failure_code", String(80)),
    Column("failure_summary", Text),
    Column("manifest_version", String(50), nullable=False),
    Column("manifest_canonical_text", Text, nullable=False),
    Column("manifest_hash", String(64), nullable=False),
    Column("idempotency_key", String(150), nullable=False),
    Column("attempt_count", Integer, nullable=False, server_default=text("0")),
    Column("last_attempt_at", DateTime),
    Column("retry_eligible_at", DateTime),
    Column("outcome_unknown", Boolean, nullable=False, server_default=text("FALSE")),
    Column("hold_check_status", String(30), nullable=False, server_default=text("'UNKNOWN'")),
    Column("hold_checked_at", DateTime),
    Column("hold_checked_by_id", Integer),
    Column("hold_checked_by_snapshot", String(100)),
    Column("hold_check_source", String(100)),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

purge_legal_holds_table = Table(
    "purge_legal_holds",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("hold_id", String(36), nullable=False),
    Column("workspace_id", Integer, nullable=False),
    Column("hold_type", String(50), nullable=False),
    Column("status", String(20), nullable=False, server_default=text("'ACTIVE'")),
    Column("source", String(100), nullable=False),
    Column("external_reference", String(150)),
    Column("reason", Text, nullable=False),
    Column("placed_by_id", Integer),
    Column("placed_by_snapshot", String(100), nullable=False),
    Column("placed_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("released_by_id", Integer),
    Column("released_by_snapshot", String(100)),
    Column("released_at", DateTime),
    Column("release_reason", Text),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

purge_lifecycle_events_table = Table(
    "purge_lifecycle_events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("request_id", Integer, nullable=False),
    Column("lifecycle_id_snapshot", String(36), nullable=False),
    Column("workspace_id", Integer, nullable=False),
    Column("workspace_name_snapshot", String(150), nullable=False),
    Column("event_sequence", Integer, nullable=False),
    Column("event_type", String(40), nullable=False),
    Column("actor_id", Integer),
    Column("actor_snapshot", String(100), nullable=False),
    Column("event_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("status_before", String(30)),
    Column("status_after", String(30)),
    Column("reason_code", String(80)),
    Column("sanitized_summary", Text),
    Column("metadata_canonical_text", Text),
    Column("metadata_hash", String(64)),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)


AUTHORIZATION_STATES = (
    "ACTIVE",
    "CLAIMED",
    "SERVICE_STARTED",
    "CONSUMED_SUCCESS",
    "REVOKED",
    "CLAIMED_UNRESOLVED",
)
PURGE_REAUTH_METHODS = ("local_password",)


workspace_purge_execution_authorizations_table = Table(
    "workspace_purge_execution_authorizations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "purge_request_id",
        Integer,
        ForeignKey("workspace_purge_requests.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "actor_user_id",
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("method", String(30), nullable=False, server_default=text("'local_password'")),
    Column("generation", Integer, nullable=False, server_default=text("1")),
    Column("state", String(30), nullable=False, server_default=text("'ACTIVE'")),
    Column("nonce_hash", String(64)),
    Column("authenticated_at", DateTime),
    Column("expires_at", DateTime),
    Column("consumed_at", DateTime),
    Column("claimed_at", DateTime),
    Column("service_started_at", DateTime),
    Column(
        "execution_started_event_id",
        Integer,
        ForeignKey("purge_lifecycle_events.id", ondelete="RESTRICT"),
    ),
    Column("revoked_at", DateTime),
    Column("revocation_reason", String(80)),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)


workspace_purge_reauth_actor_throttles_table = Table(
    "workspace_purge_reauth_actor_throttles",
    metadata,
    Column(
        "actor_user_id",
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("failed_attempt_count", Integer, nullable=False, server_default=text("0")),
    Column("first_failed_at", DateTime),
    Column("last_failed_at", DateTime),
    Column("locked_until", DateTime),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)


@_registry.mapped
class WorkspacePurgeRequest:
    __table__ = workspace_purge_requests_table


@_registry.mapped
class PurgeLegalHold:
    __table__ = purge_legal_holds_table


@_registry.mapped
class PurgeLifecycleEvent:
    __table__ = purge_lifecycle_events_table


@_registry.mapped
class WorkspacePurgeExecutionAuthorization:
    __table__ = workspace_purge_execution_authorizations_table


@_registry.mapped
class WorkspacePurgeReauthActorThrottle:
    __table__ = workspace_purge_reauth_actor_throttles_table
