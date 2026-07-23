"""Durable account-purge reauthentication without executing the purge."""

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, update, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from core.auth.enums import normalize_role_value
from core.auth.permissions import is_approval_owner
from extensions import db
from models.account_purge import (
    AccountPurgeExecutionAuthorization,
    AccountPurgeLifecycleEvent,
    AccountPurgeRequest,
)
from models.activity_log import ActivityLog
from models.user import User
from services.account_purge_service import AccountPurgeService
from services.purge_reauth_service import (
    FAILURE_WINDOW,
    LOCKOUT_DURATION,
    MAX_FAILED_ATTEMPTS,
    REAUTH_FRESHNESS,
    PurgeReauthService,
    workspace_purge_reauth_actor_throttles_table,
)


ACTIVE = "ACTIVE"
CLAIMED = "CLAIMED"
SERVICE_STARTED = "SERVICE_STARTED"
REVOKED = "REVOKED"
CLAIMED_UNRESOLVED = "CLAIMED_UNRESOLVED"
CONSUMED_SUCCESS = "CONSUMED_SUCCESS"

EVENT_ISSUED = "AUTHORIZATION_ISSUED"
EVENT_REISSUED = "AUTHORIZATION_REISSUED"
EVENT_CLAIMED = "AUTHORIZATION_CLAIMED"
EVENT_REVOKED = "AUTHORIZATION_REVOKED"
EVENT_SERVICE_STARTED = "AUTHORIZATION_SERVICE_STARTED"
EVENT_CLAIMED_UNRESOLVED = "AUTHORIZATION_CLAIMED_UNRESOLVED"


class AccountPurgeReauthError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.message = message
        self.code = code


class AccountPurgeReauthNotFoundError(AccountPurgeReauthError):
    def __init__(self):
        super().__init__("Account purge authorization was not found.", "AUTHORIZATION_NOT_FOUND")


@dataclass(frozen=True)
class AccountPurgeAuthorizationSummary:
    authorization_id: int
    request_id: int
    executor_user_id: int
    state: str
    generation: int
    authenticated_at: datetime | None
    expires_at: datetime | None
    claimed_at: datetime | None
    service_started_at: datetime | None
    revoked_at: datetime | None
    revocation_reason: str | None
    expired: bool


@dataclass(frozen=True)
class AccountPurgeReauthIssuance:
    authorization_id: int
    request_id: int
    executor_user_id: int
    generation: int
    authenticated_at: datetime
    expires_at: datetime
    raw_nonce: str = field(repr=False)


class AccountPurgeReauthService:
    """Owns account authorization state only; it never executes a purge."""

    @staticmethod
    def _new_session():
        return sessionmaker(bind=db.engine, autoflush=False, expire_on_commit=False)()

    @staticmethod
    def _database_now(session):
        value = session.execute(select(func.current_timestamp())).scalar_one()
        if not isinstance(value, datetime):
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return AccountPurgeReauthService._normalize_utc(value)

    @staticmethod
    def _normalize_utc(value):
        """Normalize PostgreSQL-aware and SQLite-naive UTC timestamps alike."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _throttle_timestamp(value):
        """Store UTC wall time for the legacy timestamp-without-timezone throttle table."""
        normalized = AccountPurgeReauthService._normalize_utc(value)
        return normalized.replace(tzinfo=None) if normalized is not None else None

    @staticmethod
    def _summary(authorization, now=None):
        now = AccountPurgeReauthService._normalize_utc(now or datetime.now(timezone.utc))
        expires_at = AccountPurgeReauthService._normalize_utc(authorization.expires_at)
        return AccountPurgeAuthorizationSummary(
            authorization_id=authorization.id,
            request_id=authorization.request_id,
            executor_user_id=authorization.actor_user_id,
            state=authorization.state,
            generation=authorization.generation,
            authenticated_at=AccountPurgeReauthService._normalize_utc(authorization.authenticated_at),
            expires_at=expires_at,
            claimed_at=AccountPurgeReauthService._normalize_utc(authorization.claimed_at),
            service_started_at=AccountPurgeReauthService._normalize_utc(authorization.service_started_at),
            revoked_at=AccountPurgeReauthService._normalize_utc(authorization.revoked_at),
            revocation_reason=authorization.revocation_reason,
            expired=authorization.state == ACTIVE and (
                expires_at is None or expires_at <= now
            ),
        )

    @staticmethod
    def _clean_reason(reason):
        if not isinstance(reason, str) or any(ord(char) < 32 for char in reason):
            raise AccountPurgeReauthError("Revocation reason is invalid.", "INVALID_REASON")
        reason = " ".join(reason.strip().split())
        if not reason or len(reason) > 2000:
            raise AccountPurgeReauthError("Revocation reason is required.", "INVALID_REASON")
        return reason

    @staticmethod
    def _safe_detail(authorization, *, event, actor, previous_state, previous_generation, reason=None):
        return json.dumps(
            {
                "event": event,
                "authorization_id": authorization.id,
                "previous_generation": previous_generation,
                "generation": authorization.generation,
                "previous_state": previous_state,
                "reason": reason,
                "actor_id": actor.id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )[:2000]

    @staticmethod
    def _add_event(session, request, authorization, actor, event, previous_state, previous_generation, reason=None):
        session.add(AccountPurgeLifecycleEvent(
            request_id=request.id,
            target_user_id=request.target_user_id,
            managing_workspace_id=request.managing_workspace_id,
            event_type=event,
            from_state=previous_state,
            to_state=authorization.state,
            actor_id=actor.id,
            actor_name_snapshot=(actor.full_name or actor.username)[:100],
            actor_email_snapshot=actor.email,
            actor_role_snapshot=normalize_role_value(actor.role),
            safe_detail=AccountPurgeReauthService._safe_detail(
                authorization,
                event=event,
                actor=actor,
                previous_state=previous_state,
                previous_generation=previous_generation,
                reason=reason,
            ),
        ))

    @staticmethod
    def _load_request(session, request_id):
        request = session.query(AccountPurgeRequest).populate_existing().with_for_update().filter(
            AccountPurgeRequest.id == request_id
        ).one_or_none()
        if request is None:
            raise AccountPurgeReauthError("Account purge request was not found.", "REQUEST_NOT_FOUND")
        return request

    @staticmethod
    def _load_authorization(session, request_id):
        return session.query(AccountPurgeExecutionAuthorization).populate_existing().with_for_update().filter(
            AccountPurgeExecutionAuthorization.request_id == request_id
        ).one_or_none()

    @staticmethod
    def _load_actors(session, request, executor_user_id):
        ids = [request.requester_id, request.approver_id, executor_user_id]
        actors = {
            actor.id: actor
            for actor in session.query(User).populate_existing().with_for_update().filter(User.id.in_(ids)).all()
        }
        if len(actors) != len(set(ids)):
            raise AccountPurgeReauthError("Required purge actor was not found.", "EXECUTOR_NOT_AUTHORIZED")
        executor = actors[executor_user_id]
        if executor.id == request.requester_id:
            raise AccountPurgeReauthError("Requester and executor must differ.", "REQUESTER_EXECUTOR_CONFLICT")
        if executor.id == request.approver_id:
            raise AccountPurgeReauthError("Approver and executor must differ.", "APPROVER_EXECUTOR_CONFLICT")
        if executor.id == request.target_user_id:
            raise AccountPurgeReauthError("Target and executor must differ.", "TARGET_EXECUTOR_CONFLICT")
        if (
            not is_approval_owner(executor)
            or executor.is_active is not True
            or executor.deleted_at is not None
            or executor.auth_provider != "local"
            or not executor.is_approval_active
        ):
            raise AccountPurgeReauthError("Executor is not authorized.", "EXECUTOR_NOT_AUTHORIZED")
        return actors, executor

    @staticmethod
    def _load_reviewer(session, target_user_id, actor_user_id):
        actor = session.query(User).populate_existing().with_for_update().filter(
            User.id == actor_user_id
        ).one_or_none()
        if (
            actor is None
            or not is_approval_owner(actor)
            or actor.is_active is not True
            or actor.deleted_at is not None
            or actor.auth_provider != "local"
            or not actor.is_approval_active
        ):
            raise AccountPurgeReauthError("Revocation actor is not authorized.", "EXECUTOR_NOT_AUTHORIZED")
        if actor.id == target_user_id:
            raise AccountPurgeReauthError("Target and revocation actor must differ.", "TARGET_EXECUTOR_CONFLICT")
        return actor

    @staticmethod
    def _recheck(request, state):
        if request.state != "APPROVED":
            raise AccountPurgeReauthError("The request is not approved.", "INVALID_REQUEST_STATE")
        result = AccountPurgeService._evaluate(
            state,
            request.requester_id,
            request.target_user_id,
            request.managing_workspace_id,
            exclude_request_id=request.id,
        )
        if not result.eligible:
            code = "ACTIVE_LEGAL_HOLD" if result.reason_code == "ACTIVE_LEGAL_HOLD" else "TARGET_NO_LONGER_ELIGIBLE"
            raise AccountPurgeReauthError(result.reason, code)

    @staticmethod
    def _throttle(session, actor_id):
        return PurgeReauthService._load_or_create_throttle(session, actor_id)

    @staticmethod
    def _audit_throttle(session, request, actor, action, detail):
        session.add(ActivityLog(
            module="Account Purge Reauth",
            action=action,
            description=detail[:2000],
            reference_id=request.id,
            user_id=actor.id,
            workspace_id=request.managing_workspace_id,
            severity="WARNING",
        ))

    @staticmethod
    def _reset_throttle(session, throttle, now):
        session.execute(
            update(workspace_purge_reauth_actor_throttles_table)
            .where(workspace_purge_reauth_actor_throttles_table.c.actor_user_id == throttle.actor_user_id)
            .values(failed_attempt_count=0, first_failed_at=None, last_failed_at=None, locked_until=None, updated_at=AccountPurgeReauthService._throttle_timestamp(now))
        )
        session.expire(throttle)

    @staticmethod
    def _record_failed_password(session, request, executor, throttle, now):
        first_failed_at = AccountPurgeReauthService._normalize_utc(throttle.first_failed_at)
        if first_failed_at is None or now - first_failed_at >= FAILURE_WINDOW:
            count = 1
            first = now
        else:
            count = throttle.failed_attempt_count + 1
            first = first_failed_at
        locked_until = now + LOCKOUT_DURATION if count >= MAX_FAILED_ATTEMPTS else None
        session.execute(
            update(workspace_purge_reauth_actor_throttles_table)
            .where(workspace_purge_reauth_actor_throttles_table.c.actor_user_id == executor.id)
            .values(
                failed_attempt_count=count,
                first_failed_at=AccountPurgeReauthService._throttle_timestamp(first),
                last_failed_at=AccountPurgeReauthService._throttle_timestamp(now),
                locked_until=AccountPurgeReauthService._throttle_timestamp(locked_until),
                updated_at=AccountPurgeReauthService._throttle_timestamp(now),
            )
        )
        AccountPurgeReauthService._audit_throttle(
            session, request, executor, "REAUTH_FAILURE", "Account purge reauthentication failed."
        )

    @staticmethod
    def inspect_authorization(request_id, actor_user_id=None):
        session = AccountPurgeReauthService._new_session()
        try:
            authorization = session.query(AccountPurgeExecutionAuthorization).populate_existing().filter_by(request_id=request_id).one_or_none()
            if authorization is None or (actor_user_id is not None and authorization.actor_user_id != actor_user_id):
                raise AccountPurgeReauthNotFoundError()
            return AccountPurgeReauthService._summary(authorization, AccountPurgeReauthService._database_now(session))
        finally:
            session.close()

    @staticmethod
    def reauthenticate_and_issue(request_id, executor_user_id, password, expected_request_version=None):
        session = AccountPurgeReauthService._new_session()
        try:
            request = AccountPurgeReauthService._load_request(session, request_id)
            if expected_request_version is not None and request.version != expected_request_version:
                raise AccountPurgeReauthError("The request version is stale.", "AUTHORIZATION_VERSION_CONFLICT")
            actors, executor = AccountPurgeReauthService._load_actors(session, request, executor_user_id)
            state = AccountPurgeService._load_existing_request_state_after_request_lock(session, request, lock=True)
            AccountPurgeReauthService._recheck(request, state)
            throttle = AccountPurgeReauthService._throttle(session, executor.id)
            now = AccountPurgeReauthService._database_now(session)
            locked_until = AccountPurgeReauthService._normalize_utc(throttle.locked_until)
            if locked_until is not None and locked_until > now:
                AccountPurgeReauthService._audit_throttle(session, request, executor, "REAUTH_RATE_LIMITED", "Account purge reauthentication is rate limited.")
                session.commit()
                raise AccountPurgeReauthError("Reauthentication is temporarily unavailable.", "REAUTH_THROTTLED")
            if locked_until is not None and locked_until <= now:
                AccountPurgeReauthService._reset_throttle(session, throttle, now)
            authorization = AccountPurgeReauthService._load_authorization(session, request.id)
            if authorization is not None and authorization.state == ACTIVE:
                expires_at = AccountPurgeReauthService._normalize_utc(authorization.expires_at)
                if expires_at is None:
                    raise AccountPurgeReauthError("Authorization expiry is invalid.", "AUTHORIZATION_EXPIRED")
                if expires_at > now:
                    raise AccountPurgeReauthError("An active authorization already exists.", "ACTIVE_AUTHORIZATION_EXISTS")
            if authorization is not None and authorization.state not in {ACTIVE, REVOKED}:
                raise AccountPurgeReauthError("The authorization state cannot be reissued.", "INVALID_AUTHORIZATION_STATE")
            if not isinstance(password, str) or not executor.check_password(password):
                AccountPurgeReauthService._record_failed_password(session, request, executor, throttle, now)
                session.commit()
                raise AccountPurgeReauthError("Reauthentication failed.", "REAUTH_FAILED")
            AccountPurgeReauthService._reset_throttle(session, throttle, now)
            raw_nonce = secrets.token_urlsafe(32)
            nonce_hash = hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()
            previous_state = None
            previous_generation = 0
            event = EVENT_ISSUED
            if authorization is None:
                authorization = AccountPurgeExecutionAuthorization(
                    request_id=request.id, actor_user_id=executor.id, method="local_password", generation=1,
                    state=ACTIVE, nonce_hash=nonce_hash, authenticated_at=now,
                    expires_at=now + REAUTH_FRESHNESS,
                )
                session.add(authorization)
                session.flush()
            else:
                previous_state = authorization.state
                previous_generation = authorization.generation
                authorization.generation += 1
                authorization.actor_user_id = executor.id
                authorization.state = ACTIVE
                authorization.nonce_hash = nonce_hash
                authorization.authenticated_at = now
                authorization.expires_at = now + REAUTH_FRESHNESS
                authorization.consumed_at = None
                authorization.claimed_at = None
                authorization.service_started_at = None
                authorization.revoked_at = None
                authorization.revocation_reason = None
                event = EVENT_REISSUED
            AccountPurgeReauthService._add_event(session, request, authorization, executor, event, previous_state, previous_generation)
            session.commit()
            return AccountPurgeReauthIssuance(authorization.id, request.id, executor.id, authorization.generation, now, authorization.expires_at, raw_nonce)
        except AccountPurgeReauthError:
            session.rollback()
            raise
        except SQLAlchemyError as error:
            session.rollback()
            raise AccountPurgeReauthError("Account authorization persistence failed.", "PERSISTENCE_FAILURE") from error
        except Exception as error:
            session.rollback()
            raise AccountPurgeReauthError("Account authorization failed safely.", "PERSISTENCE_FAILURE") from error
        finally:
            session.close()

    @staticmethod
    def claim_authorization(request_id, executor_user_id, raw_nonce, expected_generation):
        session = AccountPurgeReauthService._new_session()
        try:
            request = AccountPurgeReauthService._load_request(session, request_id)
            actors, executor = AccountPurgeReauthService._load_actors(session, request, executor_user_id)
            authorization = AccountPurgeReauthService._load_authorization(session, request.id)
            if authorization is None:
                raise AccountPurgeReauthNotFoundError()
            if authorization.actor_user_id != executor.id:
                raise AccountPurgeReauthError("Authorization actor mismatch.", "AUTHORIZATION_ACTOR_MISMATCH")
            if authorization.generation != expected_generation:
                raise AccountPurgeReauthError("Authorization version is stale.", "AUTHORIZATION_VERSION_CONFLICT")
            if authorization.state == REVOKED:
                raise AccountPurgeReauthError("Authorization is revoked.", "AUTHORIZATION_REVOKED")
            if authorization.state != ACTIVE:
                raise AccountPurgeReauthError("Authorization was already claimed.", "AUTHORIZATION_ALREADY_CLAIMED")
            now = AccountPurgeReauthService._database_now(session)
            expires_at = AccountPurgeReauthService._normalize_utc(authorization.expires_at)
            if expires_at is None or now >= expires_at:
                raise AccountPurgeReauthError("Authorization has expired.", "AUTHORIZATION_EXPIRED")
            expected_hash = hashlib.sha256(str(raw_nonce).encode("utf-8")).hexdigest()
            if not authorization.nonce_hash or not hmac.compare_digest(authorization.nonce_hash, expected_hash):
                raise AccountPurgeReauthError("Authorization nonce is invalid.", "AUTHORIZATION_NONCE_MISMATCH")
            state = AccountPurgeService._load_existing_request_state_after_request_lock(session, request, lock=True)
            AccountPurgeReauthService._recheck(request, state)
            previous_state = authorization.state
            previous_generation = authorization.generation
            authorization.state = CLAIMED
            authorization.generation += 1
            authorization.consumed_at = now
            authorization.claimed_at = now
            authorization.nonce_hash = None
            AccountPurgeReauthService._add_event(session, request, authorization, executor, EVENT_CLAIMED, previous_state, previous_generation)
            session.commit()
            return AccountPurgeReauthService._summary(authorization, now)
        except AccountPurgeReauthError:
            session.rollback()
            raise
        except Exception as error:
            session.rollback()
            raise AccountPurgeReauthError("Account authorization claim failed safely.", "PERSISTENCE_FAILURE") from error
        finally:
            session.close()

    @staticmethod
    def revoke_authorization(request_id, revocation_actor_user_id, reason, expected_generation=None):
        session = AccountPurgeReauthService._new_session()
        try:
            request = AccountPurgeReauthService._load_request(session, request_id)
            actor = AccountPurgeReauthService._load_reviewer(session, request.target_user_id, revocation_actor_user_id)
            authorization = AccountPurgeReauthService._load_authorization(session, request.id)
            if authorization is None:
                raise AccountPurgeReauthNotFoundError()
            if expected_generation is not None and authorization.generation != expected_generation:
                raise AccountPurgeReauthError("Authorization version is stale.", "AUTHORIZATION_VERSION_CONFLICT")
            if authorization.state in {REVOKED, CONSUMED_SUCCESS}:
                raise AccountPurgeReauthError("Authorization state cannot be revoked.", "INVALID_AUTHORIZATION_STATE")
            clean_reason = AccountPurgeReauthService._clean_reason(reason)
            previous_state = authorization.state
            previous_generation = authorization.generation
            authorization.state = REVOKED
            authorization.generation += 1
            authorization.revoked_at = AccountPurgeReauthService._database_now(session)
            authorization.revocation_reason = clean_reason
            authorization.nonce_hash = None
            AccountPurgeReauthService._add_event(session, request, authorization, actor, EVENT_REVOKED, previous_state, previous_generation, clean_reason)
            session.commit()
            return AccountPurgeReauthService._summary(authorization, authorization.revoked_at)
        except AccountPurgeReauthError:
            session.rollback()
            raise
        except Exception as error:
            session.rollback()
            raise AccountPurgeReauthError("Account authorization revocation failed safely.", "PERSISTENCE_FAILURE") from error
        finally:
            session.close()

    @staticmethod
    def _state_helper(request_id, executor_user_id, expected_generation, target_state, event, reason=None):
        session = AccountPurgeReauthService._new_session()
        try:
            request = AccountPurgeReauthService._load_request(session, request_id)
            _actors, executor = AccountPurgeReauthService._load_actors(session, request, executor_user_id)
            authorization = AccountPurgeReauthService._load_authorization(session, request.id)
            if authorization is None:
                raise AccountPurgeReauthNotFoundError()
            if authorization.actor_user_id != executor.id:
                raise AccountPurgeReauthError("Authorization actor mismatch.", "AUTHORIZATION_ACTOR_MISMATCH")
            if authorization.generation != expected_generation:
                raise AccountPurgeReauthError("Authorization version is stale.", "AUTHORIZATION_VERSION_CONFLICT")
            if request.state != "APPROVED":
                raise AccountPurgeReauthError("The request is not approved.", "INVALID_REQUEST_STATE")
            allowed = {SERVICE_STARTED: {CLAIMED}, CLAIMED_UNRESOLVED: {CLAIMED, SERVICE_STARTED}}[target_state]
            if authorization.state not in allowed:
                raise AccountPurgeReauthError("Authorization state transition is invalid.", "INVALID_AUTHORIZATION_STATE")
            if target_state == CLAIMED_UNRESOLVED:
                reason = AccountPurgeReauthService._clean_reason(reason)
            previous_state = authorization.state
            previous_generation = authorization.generation
            authorization.state = target_state
            authorization.generation += 1
            authorization.service_started_at = AccountPurgeReauthService._database_now(session) if target_state == SERVICE_STARTED else authorization.service_started_at
            if reason:
                authorization.revocation_reason = reason
            AccountPurgeReauthService._add_event(session, request, authorization, executor, event, previous_state, previous_generation, reason)
            session.commit()
            return AccountPurgeReauthService._summary(authorization)
        except AccountPurgeReauthError:
            session.rollback()
            raise
        except Exception as error:
            session.rollback()
            raise AccountPurgeReauthError("Account authorization transition failed safely.", "PERSISTENCE_FAILURE") from error
        finally:
            session.close()

    @staticmethod
    def mark_service_started(request_id, executor_user_id, expected_generation):
        return AccountPurgeReauthService._state_helper(request_id, executor_user_id, expected_generation, SERVICE_STARTED, EVENT_SERVICE_STARTED)

    @staticmethod
    def mark_claimed_unresolved(request_id, executor_user_id, reason, expected_generation):
        return AccountPurgeReauthService._state_helper(request_id, executor_user_id, expected_generation, CLAIMED_UNRESOLVED, EVENT_CLAIMED_UNRESOLVED, reason)
