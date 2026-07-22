from extensions import db
from utils.timezone_utils import utc_now


ACCOUNT_PURGE_STATES = (
    "REQUESTED", "APPROVED", "REJECTED", "CANCELLED", "EXECUTING",
    "SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN",
)
ACCOUNT_PURGE_TERMINAL_STATES = ("NOT_PURGED", "PURGED_TOMBSTONE")
ACCOUNT_PURGE_HOLD_STATES = ("ACTIVE", "RELEASED")
ACCOUNT_PURGE_AUTHORIZATION_STATES = (
    "ACTIVE", "CLAIMED", "SERVICE_STARTED", "CONSUMED_SUCCESS", "REVOKED",
    "CLAIMED_UNRESOLVED",
)
ACCOUNT_PURGE_IDENTITY_TYPES = ("USERNAME", "EMAIL", "GOOGLE_SUBJECT")
ACCOUNT_PURGE_AVATAR_STATES = (
    "NOT_REQUIRED", "PENDING", "COMPLETED", "FAILED_RETRYABLE", "FAILED_FINAL",
)


class UserCreationProvenance(db.Model):
    __tablename__ = "user_creation_provenance"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_in_workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    creation_source = db.Column(db.String(40), nullable=False)
    created_role = db.Column(db.String(50), nullable=True)
    provenance_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)


class AccountPurgeRequest(db.Model):
    __tablename__ = "account_purge_requests"

    id = db.Column(db.Integer, primary_key=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    managing_workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    target_provenance_id = db.Column(db.Integer, db.ForeignKey("user_creation_provenance.id", ondelete="RESTRICT"), nullable=True)
    state = db.Column(db.String(30), nullable=False, default="REQUESTED", index=True)
    reason = db.Column(db.Text, nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    requester_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requester_name_snapshot = db.Column(db.String(100), nullable=False)
    requester_email_snapshot = db.Column(db.String(255), nullable=True)
    requester_role_snapshot = db.Column(db.String(50), nullable=False)
    requested_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    approver_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approver_name_snapshot = db.Column(db.String(100), nullable=True)
    approver_email_snapshot = db.Column(db.String(255), nullable=True)
    approver_role_snapshot = db.Column(db.String(50), nullable=True)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rejected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    executor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    executor_name_snapshot = db.Column(db.String(100), nullable=True)
    executor_email_snapshot = db.Column(db.String(255), nullable=True)
    executor_role_snapshot = db.Column(db.String(50), nullable=True)
    execution_authorized_at = db.Column(db.DateTime(timezone=True), nullable=True)
    execution_started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    execution_completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    eligible_at = db.Column(db.DateTime(timezone=True), nullable=True)
    cancelled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    cancellation_reason = db.Column(db.Text, nullable=True)
    failure_code = db.Column(db.String(80), nullable=True)
    failure_detail_safe = db.Column(db.Text, nullable=True)
    outcome_unknown_at = db.Column(db.DateTime(timezone=True), nullable=True)
    terminal_at = db.Column(db.DateTime(timezone=True), nullable=True)
    target_username_snapshot = db.Column(db.String(100), nullable=True)
    target_email_snapshot = db.Column(db.String(255), nullable=True)
    target_role_snapshot = db.Column(db.String(50), nullable=False)
    target_auth_provider_snapshot = db.Column(db.String(50), nullable=True)


class AccountPurgeLifecycleEvent(db.Model):
    __tablename__ = "account_purge_lifecycle_events"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("account_purge_requests.id", ondelete="RESTRICT"), nullable=False, index=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    managing_workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_type = db.Column(db.String(50), nullable=False, index=True)
    from_state = db.Column(db.String(30), nullable=True)
    to_state = db.Column(db.String(30), nullable=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name_snapshot = db.Column(db.String(100), nullable=False)
    actor_email_snapshot = db.Column(db.String(255), nullable=True)
    actor_role_snapshot = db.Column(db.String(50), nullable=True)
    safe_detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, index=True)


class AccountPurgeLegalHold(db.Model):
    __tablename__ = "account_purge_legal_holds"

    id = db.Column(db.Integer, primary_key=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    managing_workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    request_id = db.Column(db.Integer, db.ForeignKey("account_purge_requests.id", ondelete="SET NULL"), nullable=True)
    state = db.Column(db.String(20), nullable=False, default="ACTIVE", index=True)
    reason = db.Column(db.Text, nullable=False)
    placed_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    placed_by_name_snapshot = db.Column(db.String(100), nullable=False)
    placed_by_email_snapshot = db.Column(db.String(255), nullable=True)
    placed_by_role_snapshot = db.Column(db.String(50), nullable=True)
    placed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    released_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    released_by_name_snapshot = db.Column(db.String(100), nullable=True)
    released_by_email_snapshot = db.Column(db.String(255), nullable=True)
    released_by_role_snapshot = db.Column(db.String(50), nullable=True)
    released_at = db.Column(db.DateTime(timezone=True), nullable=True)
    release_reason = db.Column(db.Text, nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)


class AccountPurgeExecutionAuthorization(db.Model):
    __tablename__ = "account_purge_execution_authorizations"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("account_purge_requests.id", ondelete="RESTRICT"), nullable=False, unique=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    method = db.Column(db.String(30), nullable=False, default="local_password")
    generation = db.Column(db.Integer, nullable=False, default=1)
    state = db.Column(db.String(30), nullable=False, default="ACTIVE")
    nonce_hash = db.Column(db.String(64), nullable=True)
    authenticated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    consumed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    claimed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    service_started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revocation_reason = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class AccountIdentityReservation(db.Model):
    __tablename__ = "account_identity_reservations"

    id = db.Column(db.Integer, primary_key=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    request_id = db.Column(db.Integer, db.ForeignKey("account_purge_requests.id", ondelete="RESTRICT"), nullable=False, index=True)
    identity_type = db.Column(db.String(30), nullable=False, index=True)
    identity_fingerprint = db.Column(db.String(128), nullable=False)
    fingerprint_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    released_at = db.Column(db.DateTime(timezone=True), nullable=True)
    release_reason = db.Column(db.Text, nullable=True)


class AccountPurgeAvatarCleanup(db.Model):
    __tablename__ = "account_purge_avatar_cleanups"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("account_purge_requests.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    relative_path_snapshot = db.Column(db.String(255), nullable=True)
    ownership_proven = db.Column(db.Boolean, nullable=False, default=False)
    state = db.Column(db.String(30), nullable=False, default="NOT_REQUIRED", index=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    last_attempt_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    safe_error_code = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
