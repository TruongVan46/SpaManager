"""Internal account-level legal-hold lifecycle service."""

import re
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from core.auth.permissions import is_approval_owner
from core.auth.enums import normalize_role_value
from extensions import db
from models.account_purge import AccountPurgeLegalHold, AccountPurgeLifecycleEvent, AccountPurgeRequest
from models.activity_log import ActivityLog
from models.user import User
from models.workspace import Workspace
from utils.timezone_utils import utc_now


ACTIVE_STATE = "ACTIVE"
RELEASED_STATE = "RELEASED"


class AccountPurgeLegalHoldServiceError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class AccountPurgeLegalHoldSummary:
    id: int
    target_user_id: int
    managing_workspace_id: int | None
    request_id: int | None
    state: str
    reason: str
    placed_by_id: int
    placed_by_name_snapshot: str
    placed_by_email_snapshot: str | None
    placed_by_role_snapshot: str | None
    placed_at: object
    released_by_id: int | None
    released_by_name_snapshot: str | None
    released_by_email_snapshot: str | None
    released_by_role_snapshot: str | None
    released_at: object | None
    release_reason: str | None
    version: int


class AccountPurgeLegalHoldService:
    _REASON = re.compile(r"^.{1,2000}$", re.DOTALL)

    @staticmethod
    def _new_session():
        return sessionmaker(bind=db.engine, autoflush=False, expire_on_commit=False)()

    @staticmethod
    def _clean_reason(value, field):
        if not isinstance(value, str) or any(ord(char) < 32 for char in value):
            raise AccountPurgeLegalHoldServiceError(f"{field} is invalid.", "INVALID_REASON")
        value = " ".join(value.strip().split())
        if not value or not AccountPurgeLegalHoldService._REASON.fullmatch(value):
            raise AccountPurgeLegalHoldServiceError(f"{field} is required.", "INVALID_REASON")
        return value

    @staticmethod
    def _actor(session, actor_user_id, target_user_id=None):
        actor = session.query(User).filter(User.id == actor_user_id).with_for_update().one_or_none()
        if (
            actor is None
            or not is_approval_owner(actor)
            or not actor.is_active
            or actor.deleted_at is not None
            or not actor.is_approval_active
        ):
            raise AccountPurgeLegalHoldServiceError(
                "Actor is not authorized for account legal-hold administration.", "ACTOR_NOT_AUTHORIZED"
            )
        if target_user_id is not None and actor.id == target_user_id:
            raise AccountPurgeLegalHoldServiceError(
                "Actor and target must be different.", "ACTOR_TARGET_CONFLICT"
            )
        return actor

    @staticmethod
    def _summary(hold):
        return AccountPurgeLegalHoldSummary(
            id=hold.id,
            target_user_id=hold.target_user_id,
            managing_workspace_id=hold.managing_workspace_id,
            request_id=hold.request_id,
            state=hold.state,
            reason=hold.reason,
            placed_by_id=hold.placed_by_id,
            placed_by_name_snapshot=hold.placed_by_name_snapshot,
            placed_by_email_snapshot=hold.placed_by_email_snapshot,
            placed_by_role_snapshot=hold.placed_by_role_snapshot,
            placed_at=hold.placed_at,
            released_by_id=hold.released_by_id,
            released_by_name_snapshot=hold.released_by_name_snapshot,
            released_by_email_snapshot=hold.released_by_email_snapshot,
            released_by_role_snapshot=hold.released_by_role_snapshot,
            released_at=hold.released_at,
            release_reason=hold.release_reason,
            version=hold.version,
        )

    @staticmethod
    def _add_lifecycle_event(session, hold, actor, event_type, from_state, to_state, detail):
        if hold.request_id is None or hold.managing_workspace_id is None:
            return
        session.add(AccountPurgeLifecycleEvent(
            request_id=hold.request_id,
            target_user_id=hold.target_user_id,
            managing_workspace_id=hold.managing_workspace_id,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            actor_id=actor.id,
            actor_name_snapshot=(actor.full_name or actor.username)[:100],
            actor_email_snapshot=actor.email,
            actor_role_snapshot=normalize_role_value(actor.role),
            safe_detail=detail[:2000],
            created_at=utc_now(),
        ))

    @staticmethod
    def _add_audit(session, hold, actor, action, detail):
        session.add(ActivityLog(
            module="Account Purge",
            action=action,
            description=(f"{action}: {detail}")[:2000],
            reference_id=hold.id,
            user_id=actor.id,
            workspace_id=hold.managing_workspace_id,
            severity="WARNING",
        ))

    @staticmethod
    def place_hold(*, target_user_id, actor_user_id, reason, managing_workspace_id=None, request_id=None):
        session = AccountPurgeLegalHoldService._new_session()
        try:
            request = None
            if request_id is not None:
                request = session.query(AccountPurgeRequest).populate_existing().with_for_update().filter(
                    AccountPurgeRequest.id == request_id
                ).one_or_none()
                if request is None:
                    raise AccountPurgeLegalHoldServiceError("Account purge request was not found.", "REQUEST_NOT_FOUND")
            target = session.query(User).populate_existing().with_for_update().filter(User.id == target_user_id).one_or_none()
            if target is None:
                raise AccountPurgeLegalHoldServiceError("Target user was not found.", "TARGET_NOT_FOUND")
            actor = AccountPurgeLegalHoldService._actor(session, actor_user_id, target.id)
            if request_id is not None:
                if request.target_user_id != target.id:
                    raise AccountPurgeLegalHoldServiceError("Request target mismatch.", "REQUEST_TARGET_MISMATCH")
                if managing_workspace_id is None:
                    managing_workspace_id = request.managing_workspace_id
                elif managing_workspace_id != request.managing_workspace_id:
                    raise AccountPurgeLegalHoldServiceError("Request workspace mismatch.", "REQUEST_WORKSPACE_MISMATCH")
            workspace = None
            if managing_workspace_id is not None:
                workspace = session.query(Workspace).filter(
                    Workspace.id == managing_workspace_id
                ).with_for_update().one_or_none()
                if workspace is None:
                    raise AccountPurgeLegalHoldServiceError("Managing workspace was not found.", "WORKSPACE_NOT_FOUND")
            clean_reason = AccountPurgeLegalHoldService._clean_reason(reason, "Hold reason")
            existing = session.query(AccountPurgeLegalHold).filter(
                AccountPurgeLegalHold.target_user_id == target.id,
                AccountPurgeLegalHold.state == ACTIVE_STATE,
            ).with_for_update().all()
            if any(
                hold.managing_workspace_id == managing_workspace_id
                and hold.request_id == request_id
                for hold in existing
            ):
                raise AccountPurgeLegalHoldServiceError(
                    "An equivalent active legal hold already exists.", "DUPLICATE_ACTIVE_HOLD"
                )
            hold = AccountPurgeLegalHold(
                target_user_id=target.id,
                managing_workspace_id=managing_workspace_id,
                request_id=request_id,
                state=ACTIVE_STATE,
                reason=clean_reason,
                placed_by_id=actor.id,
                placed_by_name_snapshot=(actor.full_name or actor.username)[:100],
                placed_by_email_snapshot=actor.email,
                placed_by_role_snapshot=normalize_role_value(actor.role),
                placed_at=utc_now(),
                version=1,
            )
            session.add(hold)
            session.flush()
            AccountPurgeLegalHoldService._add_lifecycle_event(
                session, hold, actor, "LEGAL_HOLD_PLACED", None, ACTIVE_STATE, clean_reason
            )
            AccountPurgeLegalHoldService._add_audit(
                session, hold, actor, "ACCOUNT_LEGAL_HOLD_PLACED", clean_reason
            )
            session.commit()
            return AccountPurgeLegalHoldService._summary(hold)
        except AccountPurgeLegalHoldServiceError:
            session.rollback()
            raise
        except SQLAlchemyError as error:
            session.rollback()
            raise AccountPurgeLegalHoldServiceError(
                "Account legal hold could not be persisted.", "PERSISTENCE_FAILURE"
            ) from error
        except Exception as error:
            session.rollback()
            raise AccountPurgeLegalHoldServiceError(
                "Account legal hold failed safely.", "PERSISTENCE_FAILURE"
            ) from error
        finally:
            session.close()

    @staticmethod
    def release_hold(*, hold_id, actor_user_id, release_reason, expected_version=None):
        session = AccountPurgeLegalHoldService._new_session()
        try:
            hold = session.query(AccountPurgeLegalHold).filter(
                AccountPurgeLegalHold.id == hold_id
            ).with_for_update().one_or_none()
            if hold is None:
                raise AccountPurgeLegalHoldServiceError("Account legal hold was not found.", "HOLD_NOT_FOUND")
            actor = AccountPurgeLegalHoldService._actor(session, actor_user_id, hold.target_user_id)
            if expected_version is not None and hold.version != expected_version:
                raise AccountPurgeLegalHoldServiceError(
                    "The account legal hold version is stale.", "HOLD_VERSION_CONFLICT"
                )
            if hold.state != ACTIVE_STATE:
                raise AccountPurgeLegalHoldServiceError(
                    "The account legal hold is no longer active.", "HOLD_NOT_ACTIVE"
                )
            reason = AccountPurgeLegalHoldService._clean_reason(release_reason, "Release reason")
            previous_state = hold.state
            hold.state = RELEASED_STATE
            hold.released_by_id = actor.id
            hold.released_by_name_snapshot = (actor.full_name or actor.username)[:100]
            hold.released_by_email_snapshot = actor.email
            hold.released_by_role_snapshot = normalize_role_value(actor.role)
            hold.released_at = utc_now()
            hold.release_reason = reason
            hold.version += 1
            AccountPurgeLegalHoldService._add_lifecycle_event(
                session, hold, actor, "LEGAL_HOLD_RELEASED", previous_state, RELEASED_STATE, reason
            )
            AccountPurgeLegalHoldService._add_audit(
                session, hold, actor, "ACCOUNT_LEGAL_HOLD_RELEASED", reason
            )
            session.commit()
            return AccountPurgeLegalHoldService._summary(hold)
        except AccountPurgeLegalHoldServiceError:
            session.rollback()
            raise
        except Exception as error:
            session.rollback()
            raise AccountPurgeLegalHoldServiceError(
                "Account legal hold release failed safely.", "PERSISTENCE_FAILURE"
            ) from error
        finally:
            session.close()

    @staticmethod
    def list_holds(*, target_user_id, actor_user_id, managing_workspace_id=None, request_id=None, include_released=True):
        session = AccountPurgeLegalHoldService._new_session()
        try:
            target = session.query(User).filter(User.id == target_user_id).one_or_none()
            if target is None:
                raise AccountPurgeLegalHoldServiceError("Target user was not found.", "TARGET_NOT_FOUND")
            AccountPurgeLegalHoldService._actor(session, actor_user_id, target.id)
            query = session.query(AccountPurgeLegalHold).filter(
                AccountPurgeLegalHold.target_user_id == target.id
            )
            if managing_workspace_id is not None:
                query = query.filter(AccountPurgeLegalHold.managing_workspace_id == managing_workspace_id)
            if request_id is not None:
                query = query.filter(AccountPurgeLegalHold.request_id == request_id)
            if not include_released:
                query = query.filter(AccountPurgeLegalHold.state == ACTIVE_STATE)
            return [AccountPurgeLegalHoldService._summary(hold) for hold in query.order_by(AccountPurgeLegalHold.id).all()]
        finally:
            session.close()

    @staticmethod
    def inspect_active_holds(*, target_user_id, actor_user_id, managing_workspace_id=None, request_id=None):
        return AccountPurgeLegalHoldService.list_holds(
            target_user_id=target_user_id,
            actor_user_id=actor_user_id,
            managing_workspace_id=managing_workspace_id,
            request_id=request_id,
            include_released=False,
        )
