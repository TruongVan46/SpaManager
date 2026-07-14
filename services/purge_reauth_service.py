"""Durable local-password re-authentication for permanent purge execution.

This module deliberately contains no route or session transport logic.  It
owns the short transactions that issue, claim, inspect, and revoke the
request-wide authorization rows introduced by migration 0008.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.activity_log_utils import build_activity_log_entry
from core.auth.permissions import is_approval_owner
from extensions import db
from models.activity_log import ActivityLog
from models.purge import (
    AUTHORIZATION_STATES,
    PURGE_REAUTH_METHODS,
    PurgeLifecycleEvent,
    WorkspacePurgeExecutionAuthorization,
    workspace_purge_execution_authorizations_table,
    WorkspacePurgeReauthActorThrottle,
    workspace_purge_reauth_actor_throttles_table,
    WorkspacePurgeRequest,
)
from models.user import User
from models.workspace import Workspace


AUTHORIZATION_ACTIVE = AUTHORIZATION_STATES[0]
AUTHORIZATION_CLAIMED = AUTHORIZATION_STATES[1]
AUTHORIZATION_SERVICE_STARTED = AUTHORIZATION_STATES[2]
AUTHORIZATION_CONSUMED_SUCCESS = AUTHORIZATION_STATES[3]
AUTHORIZATION_REVOKED = AUTHORIZATION_STATES[4]
AUTHORIZATION_CLAIMED_UNRESOLVED = AUTHORIZATION_STATES[5]

REAUTH_METHOD = PURGE_REAUTH_METHODS[0]
REAUTH_FRESHNESS = timedelta(minutes=5)
FAILURE_WINDOW = timedelta(minutes=10)
LOCKOUT_DURATION = timedelta(minutes=15)
MAX_FAILED_ATTEMPTS = 5

REVOCATION_REASONS = frozenset(
    {
        "LOGOUT",
        "PASSWORD_CHANGED",
        "PASSWORD_RESET",
        "REQUEST_CANCELLED",
        "REQUEST_REJECTED",
        "REQUEST_EXPIRED",
        "REQUEST_INVALIDATED",
        "ACTOR_INELIGIBLE",
        "SERVICE_PREFLIGHT_REJECTED",
        "MANUAL_RECONCILIATION",
    }
)


class PurgeReauthError(Exception):
    """Base error with a stable, safe code for future route mapping."""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class PurgeReauthRequiredError(PurgeReauthError):
    def __init__(self):
        super().__init__("Fresh purge re-authentication is required.", "REAUTH_REQUIRED")


class PurgeReauthInvalidCredentialError(PurgeReauthError):
    def __init__(self):
        super().__init__("The supplied re-authentication could not be accepted.", "REAUTH_INVALID_CREDENTIAL")


class PurgeReauthRateLimitedError(PurgeReauthError):
    def __init__(self):
        super().__init__("Re-authentication is temporarily unavailable.", "REAUTH_RATE_LIMITED")


class PurgeReauthProviderUnsupportedError(PurgeReauthError):
    def __init__(self):
        super().__init__("The executor authentication provider is not supported.", "REAUTH_PROVIDER_UNSUPPORTED")


class PurgeReauthActorIneligibleError(PurgeReauthError):
    def __init__(self):
        super().__init__("The purge executor is not eligible.", "REAUTH_ACTOR_INELIGIBLE")


class PurgeReauthRequestIneligibleError(PurgeReauthError):
    def __init__(self):
        super().__init__("The purge request is not eligible for re-authentication.", "REAUTH_REQUEST_INELIGIBLE")


class PurgeReauthAuthorizationBusyError(PurgeReauthError):
    def __init__(self):
        super().__init__("The purge authorization is already in use.", "REAUTH_AUTHORIZATION_BUSY")


class PurgeReauthAuthorizationMissingError(PurgeReauthError):
    def __init__(self):
        super().__init__("A valid purge authorization was not found.", "REAUTH_AUTHORIZATION_MISSING")


class PurgeReauthGenerationMismatchError(PurgeReauthError):
    def __init__(self):
        super().__init__("The purge authorization generation is invalid.", "REAUTH_GENERATION_MISMATCH")


class PurgeReauthNonceMismatchError(PurgeReauthError):
    def __init__(self):
        super().__init__("The purge authorization is invalid.", "REAUTH_NONCE_MISMATCH")


class PurgeReauthExpiredError(PurgeReauthError):
    def __init__(self):
        super().__init__("The purge authorization has expired.", "REAUTH_EXPIRED")


class PurgeReauthRevokedError(PurgeReauthError):
    def __init__(self):
        super().__init__("The purge authorization has been revoked.", "REAUTH_REVOKED")


class PurgeReauthAlreadyClaimedError(PurgeReauthError):
    def __init__(self):
        super().__init__("The purge authorization has already been claimed.", "REAUTH_ALREADY_CLAIMED")


class PurgeReauthAuditError(PurgeReauthError):
    def __init__(self):
        super().__init__("The re-authentication audit could not be committed.", "REAUTH_AUDIT_FAILED")


class PurgeReauthIssuanceOutcomeUnknownError(PurgeReauthError):
    def __init__(self):
        super().__init__("Re-authentication issuance outcome is unknown.", "REAUTH_ISSUANCE_OUTCOME_UNKNOWN")


class PurgeReauthClaimOutcomeUnknownError(PurgeReauthError):
    def __init__(self):
        super().__init__("Purge authorization claim outcome is unknown.", "REAUTH_CLAIM_OUTCOME_UNKNOWN")


@dataclass(frozen=True)
class PurgeReauthIssuance:
    authorization_id: int
    purge_request_id: int
    actor_user_id: int
    generation: int
    authenticated_at: datetime
    expires_at: datetime
    raw_nonce: str = field(repr=False)


@dataclass(frozen=True)
class PurgeReauthClaim:
    authorization_id: int
    purge_request_id: int
    actor_user_id: int
    generation: int
    claimed_at: datetime


@dataclass(frozen=True)
class PurgeReauthStateView:
    authorization_id: int | None
    purge_request_id: int
    actor_user_id: int | None
    generation: int | None
    state: str | None
    authenticated_at: datetime | None
    expires_at: datetime | None
    fresh_active_for_actor: bool


class PurgeReauthService:
    """Short, caller-independent transactions for durable purge re-auth."""

    MODULE = "PurgeReauth"

    @staticmethod
    def _new_session():
        return sessionmaker(bind=db.engine, autoflush=False, expire_on_commit=False)()

    @staticmethod
    def _database_now(session):
        value = session.execute(select(func.current_timestamp())).scalar_one()
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)

    @staticmethod
    def _reconcile_issuance(authorization_id, purge_request_id, actor_user_id,
                            generation, nonce_hash, authenticated_at, expires_at, raw_nonce):
        session = PurgeReauthService._new_session()
        try:
            authorization = session.query(WorkspacePurgeExecutionAuthorization).filter_by(
                id=authorization_id,
                purge_request_id=purge_request_id,
                actor_user_id=actor_user_id,
                generation=generation,
                state=AUTHORIZATION_ACTIVE,
            ).one_or_none()
            audit = session.query(ActivityLog).filter_by(
                module=PurgeReauthService.MODULE,
                action="ISSUE_SUCCESS",
                reference_id=authorization_id,
                user_id=actor_user_id,
            ).first()
            if authorization is not None and audit is not None and authorization.nonce_hash == nonce_hash:
                return PurgeReauthIssuance(
                    authorization_id=authorization_id,
                    purge_request_id=purge_request_id,
                    actor_user_id=actor_user_id,
                    generation=generation,
                    authenticated_at=authenticated_at,
                    expires_at=expires_at,
                    raw_nonce=raw_nonce,
                )
        finally:
            session.close()
        return None

    @staticmethod
    def _reconcile_claim(authorization_id, purge_request_id, actor_user_id, generation, claimed_at):
        session = PurgeReauthService._new_session()
        try:
            authorization = session.query(WorkspacePurgeExecutionAuthorization).filter_by(
                id=authorization_id,
                purge_request_id=purge_request_id,
                actor_user_id=actor_user_id,
                generation=generation,
                state=AUTHORIZATION_CLAIMED,
            ).one_or_none()
            audit = session.query(ActivityLog).filter_by(
                module=PurgeReauthService.MODULE,
                action="CLAIM",
                reference_id=authorization_id,
                user_id=actor_user_id,
            ).first()
            if authorization is not None and authorization.nonce_hash is None and authorization.claimed_at is not None and audit is not None:
                return PurgeReauthClaim(
                    authorization_id, purge_request_id, actor_user_id, generation, claimed_at
                )
        finally:
            session.close()
        return None

    @staticmethod
    def _audit(session, *, action, actor_id, request, authorization_id, description):
        try:
            entry = build_activity_log_entry(
                module=PurgeReauthService.MODULE,
                action=action,
                description=description,
                reference_id=authorization_id,
                severity="INFO" if action.endswith("FAILURE") or action == "RATE_LIMITED" else "SUCCESS",
                user_id=actor_id,
                workspace_id=request.workspace_id,
            )
            session.add(entry)
            session.flush()
        except Exception as exc:
            raise PurgeReauthAuditError() from exc

    @staticmethod
    def _load_request(session, purge_request_id):
        return (
            session.query(WorkspacePurgeRequest)
            .filter(WorkspacePurgeRequest.id == purge_request_id)
            .with_for_update()
            .one_or_none()
        )

    @staticmethod
    def _validate_request(request):
        if request is None or request.purge_type != "workspace":
            raise PurgeReauthRequestIneligibleError()
        if (
            request.status != "APPROVED"
            or request.approved_by_id is None
            or request.approved_at is None
            or request.requested_by_id is None
            or request.invalidated_at is not None
            or request.invalidated_by_restore
            or request.outcome_unknown
        ):
            raise PurgeReauthRequestIneligibleError()

    @staticmethod
    def _lock_workspace_for_claim(session, workspace_id):
        return (
            session.query(Workspace)
            .filter(Workspace.id == workspace_id)
            .with_for_update()
            .one_or_none()
        )

    @staticmethod
    def _load_actors(session, request, executor_user_id):
        ids = (request.requested_by_id, request.approved_by_id, executor_user_id)
        actors = {
            actor.id: actor
            for actor in session.query(User).filter(User.id.in_(ids)).with_for_update().all()
        }
        if len(actors) != len(set(ids)):
            raise PurgeReauthActorIneligibleError()
        for actor_id in ids:
            actor = actors[actor_id]
            if (
                not is_approval_owner(actor)
                or actor.is_active is not True
                or actor.deleted_at is not None
                or actor.approval_status != User.APPROVAL_ACTIVE
            ):
                raise PurgeReauthActorIneligibleError()
        executor = actors[executor_user_id]
        if executor.auth_provider != "local":
            raise PurgeReauthProviderUnsupportedError()
        return executor

    @staticmethod
    def _load_or_create_throttle(session, actor_user_id):
        throttle = (
            session.query(WorkspacePurgeReauthActorThrottle)
            .filter_by(actor_user_id=actor_user_id)
            .with_for_update()
            .one_or_none()
        )
        if throttle is not None:
            return throttle
        try:
            with session.begin_nested():
                session.execute(
                    workspace_purge_reauth_actor_throttles_table.insert().values(
                        actor_user_id=actor_user_id,
                    )
                )
        except IntegrityError:
            throttle = None
        if throttle is None:
            throttle = (
                session.query(WorkspacePurgeReauthActorThrottle)
                .filter_by(actor_user_id=actor_user_id)
                .with_for_update()
                .one()
            )
        return throttle

    @staticmethod
    def _raise_pending(error):
        if error is not None:
            raise error

    @staticmethod
    def issue_local_authorization(purge_request_id, actor_user_id, current_password):
        session = PurgeReauthService._new_session()
        issuance = None
        pending_error = None
        expected_nonce_hash = None
        try:
            session.begin()
            request = PurgeReauthService._load_request(session, purge_request_id)
            PurgeReauthService._validate_request(request)
            executor = PurgeReauthService._load_actors(session, request, actor_user_id)
            throttle = PurgeReauthService._load_or_create_throttle(session, actor_user_id)
            now = PurgeReauthService._database_now(session)

            if throttle.locked_until is not None and throttle.locked_until > now:
                PurgeReauthService._audit(
                    session,
                    action="RATE_LIMITED",
                    actor_id=actor_user_id,
                    request=request,
                    authorization_id=None,
                    description="Purge re-authentication rate limited.",
                )
                pending_error = PurgeReauthRateLimitedError()
            else:
                if throttle.locked_until is not None and throttle.locked_until <= now:
                    session.execute(
                        workspace_purge_reauth_actor_throttles_table.update()
                        .where(workspace_purge_reauth_actor_throttles_table.c.actor_user_id == actor_user_id)
                        .values(failed_attempt_count=0, first_failed_at=None,
                                last_failed_at=None, locked_until=None, updated_at=now)
                    )
                    throttle.failed_attempt_count = 0
                    throttle.first_failed_at = None
                    throttle.last_failed_at = None
                    throttle.locked_until = None
                    session.expunge(throttle)
                if throttle.first_failed_at is not None and now - throttle.first_failed_at >= FAILURE_WINDOW:
                    session.execute(
                        workspace_purge_reauth_actor_throttles_table.update()
                        .where(workspace_purge_reauth_actor_throttles_table.c.actor_user_id == actor_user_id)
                        .values(failed_attempt_count=0, first_failed_at=None,
                                last_failed_at=None, locked_until=None, updated_at=now)
                    )
                    throttle.failed_attempt_count = 0
                    throttle.first_failed_at = None
                    throttle.last_failed_at = None
                    throttle.locked_until = None
                    session.expunge(throttle)

                authorization = (
                    session.query(WorkspacePurgeExecutionAuthorization)
                    .filter_by(purge_request_id=purge_request_id)
                    .with_for_update()
                    .one_or_none()
                )
                if authorization is not None and authorization.state in {
                    AUTHORIZATION_CLAIMED,
                    AUTHORIZATION_SERVICE_STARTED,
                    AUTHORIZATION_CLAIMED_UNRESOLVED,
                }:
                    raise PurgeReauthAuthorizationBusyError()
                if authorization is not None and authorization.state == AUTHORIZATION_CONSUMED_SUCCESS:
                    raise PurgeReauthRequestIneligibleError()

                password_ok = isinstance(current_password, str) and executor.check_password(current_password)
                if not password_ok:
                    if throttle.failed_attempt_count == 0 or throttle.first_failed_at is None:
                        throttle.first_failed_at = now
                        throttle.failed_attempt_count = 1
                    else:
                        throttle.failed_attempt_count += 1
                    throttle.last_failed_at = now
                    if throttle.failed_attempt_count >= MAX_FAILED_ATTEMPTS:
                        throttle.locked_until = now + LOCKOUT_DURATION
                    session.execute(
                        workspace_purge_reauth_actor_throttles_table.update()
                        .where(workspace_purge_reauth_actor_throttles_table.c.actor_user_id == actor_user_id)
                        .values(failed_attempt_count=throttle.failed_attempt_count,
                                first_failed_at=throttle.first_failed_at,
                                last_failed_at=throttle.last_failed_at,
                                locked_until=throttle.locked_until, updated_at=now)
                    )
                    session.expunge(throttle)
                    PurgeReauthService._audit(
                        session,
                        action="PASSWORD_FAILURE",
                        actor_id=actor_user_id,
                        request=request,
                        authorization_id=authorization.id if authorization else None,
                        description=f"Purge re-authentication failed; attempts={throttle.failed_attempt_count}.",
                    )
                    pending_error = PurgeReauthInvalidCredentialError()
                else:
                    session.execute(
                        workspace_purge_reauth_actor_throttles_table.update()
                        .where(workspace_purge_reauth_actor_throttles_table.c.actor_user_id == actor_user_id)
                        .values(failed_attempt_count=0, first_failed_at=None,
                                last_failed_at=None, locked_until=None, updated_at=now)
                    )
                    raw_nonce = secrets.token_urlsafe(32)
                    nonce_hash = hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()
                    expected_nonce_hash = nonce_hash
                    generation = (authorization.generation + 1) if authorization is not None else 1
                    if authorization is None:
                        session.execute(
                            workspace_purge_execution_authorizations_table.insert().values(
                                purge_request_id=purge_request_id,
                                actor_user_id=actor_user_id,
                                method=REAUTH_METHOD,
                                generation=generation,
                                state=AUTHORIZATION_ACTIVE,
                                nonce_hash=nonce_hash,
                                authenticated_at=now,
                                expires_at=now + REAUTH_FRESHNESS,
                            )
                        )
                        authorization = (
                            session.query(WorkspacePurgeExecutionAuthorization)
                            .filter_by(purge_request_id=purge_request_id)
                            .with_for_update()
                            .one()
                        )
                    expires_at = now + REAUTH_FRESHNESS
                    session.execute(
                        workspace_purge_execution_authorizations_table.update()
                        .where(workspace_purge_execution_authorizations_table.c.id == authorization.id)
                        .values(actor_user_id=actor_user_id, method=REAUTH_METHOD,
                                generation=generation, state=AUTHORIZATION_ACTIVE,
                                nonce_hash=nonce_hash, authenticated_at=now,
                                expires_at=expires_at, consumed_at=None, claimed_at=None,
                                service_started_at=None, execution_started_event_id=None,
                                revoked_at=None, revocation_reason=None, updated_at=now)
                    )
                    session.expunge(authorization)
                    PurgeReauthService._audit(
                        session,
                        action="ISSUE_SUCCESS",
                        actor_id=actor_user_id,
                        request=request,
                        authorization_id=authorization.id,
                        description=f"Purge re-authentication issued; generation={generation}; method={REAUTH_METHOD}; expires={expires_at.isoformat()}.",
                    )
                    issuance = PurgeReauthIssuance(
                        authorization_id=authorization.id,
                        purge_request_id=purge_request_id,
                        actor_user_id=actor_user_id,
                        generation=generation,
                        authenticated_at=now,
                        expires_at=expires_at,
                        raw_nonce=raw_nonce,
                    )
            session.commit()
        except PurgeReauthError:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            if issuance is not None:
                reconciled = PurgeReauthService._reconcile_issuance(
                    issuance.authorization_id, issuance.purge_request_id,
                    issuance.actor_user_id, issuance.generation,
                    expected_nonce_hash, issuance.authenticated_at, issuance.expires_at,
                    issuance.raw_nonce,
                )
                if reconciled is not None:
                    return reconciled
            raise PurgeReauthIssuanceOutcomeUnknownError() from exc
        finally:
            session.close()
        PurgeReauthService._raise_pending(pending_error)
        return issuance

    @staticmethod
    def inspect_current_state(purge_request_id, actor_user_id=None):
        session = PurgeReauthService._new_session()
        try:
            now = PurgeReauthService._database_now(session)
            authorization = (
                session.query(WorkspacePurgeExecutionAuthorization)
                .filter_by(purge_request_id=purge_request_id)
                .one_or_none()
            )
            if authorization is None:
                return PurgeReauthStateView(None, purge_request_id, None, None, None, None, None, False)
            fresh = (
                authorization.state == AUTHORIZATION_ACTIVE
                and authorization.expires_at is not None
                and authorization.expires_at > now
                and (actor_user_id is None or authorization.actor_user_id == actor_user_id)
            )
            return PurgeReauthStateView(
                authorization.id,
                purge_request_id,
                authorization.actor_user_id,
                authorization.generation,
                authorization.state,
                authorization.authenticated_at,
                authorization.expires_at,
                fresh,
            )
        finally:
            session.close()

    @staticmethod
    def claim_for_execution(purge_request_id, workspace_id, actor_user_id, generation, raw_nonce):
        if not raw_nonce:
            raise PurgeReauthRequiredError()
        session = PurgeReauthService._new_session()
        claim = None
        try:
            session.begin()
            request = PurgeReauthService._load_request(session, purge_request_id)
            if request is None or request.workspace_id != workspace_id:
                raise PurgeReauthRequestIneligibleError()
            PurgeReauthService._validate_request(request)
            if PurgeReauthService._lock_workspace_for_claim(session, request.workspace_id) is None:
                raise PurgeReauthRequestIneligibleError()
            PurgeReauthService._load_actors(session, request, actor_user_id)
            authorization = (
                session.query(WorkspacePurgeExecutionAuthorization)
                .filter_by(purge_request_id=purge_request_id)
                .with_for_update()
                .one_or_none()
            )
            if authorization is None:
                raise PurgeReauthAuthorizationMissingError()
            if authorization.generation != generation:
                raise PurgeReauthGenerationMismatchError()
            if authorization.actor_user_id != actor_user_id:
                raise PurgeReauthAuthorizationMissingError()
            if authorization.state == AUTHORIZATION_REVOKED:
                raise PurgeReauthRevokedError()
            if authorization.state != AUTHORIZATION_ACTIVE:
                raise PurgeReauthAlreadyClaimedError()
            now = PurgeReauthService._database_now(session)
            if authorization.expires_at is None or authorization.expires_at <= now:
                raise PurgeReauthExpiredError()
            expected_hash = hashlib.sha256(str(raw_nonce).encode("utf-8")).hexdigest()
            if not authorization.nonce_hash or not hmac.compare_digest(authorization.nonce_hash, expected_hash):
                raise PurgeReauthNonceMismatchError()
            claimed_at = now
            changed = session.execute(
                update(WorkspacePurgeExecutionAuthorization)
                .where(
                    WorkspacePurgeExecutionAuthorization.id == authorization.id,
                    WorkspacePurgeExecutionAuthorization.generation == generation,
                    WorkspacePurgeExecutionAuthorization.actor_user_id == actor_user_id,
                    WorkspacePurgeExecutionAuthorization.state == AUTHORIZATION_ACTIVE,
                    WorkspacePurgeExecutionAuthorization.nonce_hash == expected_hash,
                )
                .values(
                    state=AUTHORIZATION_CLAIMED,
                    consumed_at=claimed_at,
                    claimed_at=claimed_at,
                    nonce_hash=None,
                    updated_at=claimed_at,
                )
            ).rowcount
            if changed != 1:
                raise PurgeReauthClaimOutcomeUnknownError()
            PurgeReauthService._audit(
                session,
                action="CLAIM",
                actor_id=actor_user_id,
                request=request,
                authorization_id=authorization.id,
                description=f"Purge re-authentication claimed; generation={generation}.",
            )
            claim = PurgeReauthClaim(authorization.id, purge_request_id, actor_user_id, generation, claimed_at)
            session.commit()
            return claim
        except PurgeReauthError:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            if claim is not None:
                reconciled = PurgeReauthService._reconcile_claim(
                    claim.authorization_id, claim.purge_request_id, claim.actor_user_id,
                    claim.generation, claim.claimed_at,
                )
                if reconciled is not None:
                    return reconciled
            raise PurgeReauthClaimOutcomeUnknownError() from exc
        finally:
            session.close()

    @staticmethod
    def mark_service_started(session, claim, event_id, started_at):
        changed = session.execute(
            update(WorkspacePurgeExecutionAuthorization)
            .where(
                WorkspacePurgeExecutionAuthorization.id == claim.authorization_id,
                WorkspacePurgeExecutionAuthorization.purge_request_id == claim.purge_request_id,
                WorkspacePurgeExecutionAuthorization.generation == claim.generation,
                WorkspacePurgeExecutionAuthorization.actor_user_id == claim.actor_user_id,
                WorkspacePurgeExecutionAuthorization.state == AUTHORIZATION_CLAIMED,
            )
            .values(
                state=AUTHORIZATION_SERVICE_STARTED,
                service_started_at=started_at,
                execution_started_event_id=event_id,
                updated_at=started_at,
            )
        ).rowcount
        if changed != 1:
            raise PurgeReauthClaimOutcomeUnknownError()

    @staticmethod
    def mark_consumed_success(session, claim, completed_at):
        changed = session.execute(
            update(WorkspacePurgeExecutionAuthorization)
            .where(
                WorkspacePurgeExecutionAuthorization.id == claim.authorization_id,
                WorkspacePurgeExecutionAuthorization.purge_request_id == claim.purge_request_id,
                WorkspacePurgeExecutionAuthorization.generation == claim.generation,
                WorkspacePurgeExecutionAuthorization.state == AUTHORIZATION_SERVICE_STARTED,
            )
            .values(state=AUTHORIZATION_CONSUMED_SUCCESS, updated_at=completed_at)
        ).rowcount
        if changed != 1:
            raise PurgeReauthClaimOutcomeUnknownError()

    @staticmethod
    def mark_claim_unresolved(claim, reason_code="MANUAL_RECONCILIATION"):
        session = PurgeReauthService._new_session()
        try:
            session.begin()
            request = PurgeReauthService._load_request(session, claim.purge_request_id)
            authorization = (
                session.query(WorkspacePurgeExecutionAuthorization)
                .filter_by(id=claim.authorization_id)
                .with_for_update()
                .one_or_none()
            )
            if authorization is not None and authorization.state == AUTHORIZATION_CLAIMED:
                now = PurgeReauthService._database_now(session)
                session.execute(
                    workspace_purge_execution_authorizations_table.update()
                    .where(workspace_purge_execution_authorizations_table.c.id == authorization.id)
                    .values(state=AUTHORIZATION_CLAIMED_UNRESOLVED,
                            revocation_reason=reason_code, updated_at=now)
                )
                if request is not None:
                    PurgeReauthService._audit(
                        session,
                        action="CLAIM_UNRESOLVED",
                        actor_id=claim.actor_user_id,
                        request=request,
                        authorization_id=authorization.id,
                        description=f"Purge authorization claim requires reconciliation; reason={reason_code}.",
                    )
            session.commit()
        finally:
            session.close()

    @staticmethod
    def _revoke_rows(session, rows, reason_code):
        if reason_code not in REVOCATION_REASONS:
            raise PurgeReauthRequestIneligibleError()
        now = PurgeReauthService._database_now(session)
        count = 0
        for authorization in rows:
            request = session.query(WorkspacePurgeRequest).filter_by(id=authorization.purge_request_id).one_or_none()
            if request is None:
                continue
            if authorization.state not in {AUTHORIZATION_ACTIVE, AUTHORIZATION_CLAIMED}:
                continue
            changed = session.execute(
                workspace_purge_execution_authorizations_table.update()
                .where(workspace_purge_execution_authorizations_table.c.id == authorization.id)
                .values(state=AUTHORIZATION_REVOKED, nonce_hash=None,
                        revoked_at=now, revocation_reason=reason_code, updated_at=now)
            ).rowcount
            if changed != 1:
                raise PurgeReauthClaimOutcomeUnknownError()
            PurgeReauthService._audit(
                session,
                action="REVOKE",
                actor_id=authorization.actor_user_id,
                request=request,
                authorization_id=authorization.id,
                description=f"Purge authorization revoked; generation={authorization.generation}; reason={reason_code}.",
            )
            count += 1
        return count

    @staticmethod
    def _revoke_active_authorizations_for_actor_in_session(session, actor_user_id, reason_code):
        """Revoke outstanding actor authorizations in the caller's transaction."""
        if not inspect(session.get_bind()).has_table("workspace_purge_execution_authorizations"):
            return 0
        rows = (
            session.query(WorkspacePurgeExecutionAuthorization)
            .filter(
                WorkspacePurgeExecutionAuthorization.actor_user_id == actor_user_id,
                WorkspacePurgeExecutionAuthorization.state.in_((AUTHORIZATION_ACTIVE, AUTHORIZATION_CLAIMED)),
            )
            .with_for_update()
            .all()
        )
        return PurgeReauthService._revoke_rows(session, rows, reason_code)

    @staticmethod
    def revoke_active_authorizations_for_actor(actor_user_id, reason_code):
        session = PurgeReauthService._new_session()
        try:
            session.begin()
            count = PurgeReauthService._revoke_active_authorizations_for_actor_in_session(
                session, actor_user_id, reason_code
            )
            session.commit()
            return count
        finally:
            session.close()

    @staticmethod
    def revoke_authorization_for_request(purge_request_id, reason_code):
        session = PurgeReauthService._new_session()
        try:
            session.begin()
            rows = (
                session.query(WorkspacePurgeExecutionAuthorization)
                .filter_by(purge_request_id=purge_request_id)
                .with_for_update()
                .all()
            )
            count = PurgeReauthService._revoke_rows(session, rows, reason_code)
            session.commit()
            return count
        finally:
            session.close()
