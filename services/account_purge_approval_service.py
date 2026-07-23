"""Internal approval, rejection, and requester-cancellation workflow."""

from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from core.auth.permissions import is_approval_owner
from core.auth.enums import normalize_role_value
from extensions import db
from models.account_purge import AccountPurgeLifecycleEvent, AccountPurgeRequest
from models.user import User
from services.account_purge_service import AccountPurgeService
from utils.timezone_utils import utc_now


REQUESTED_STATE = "REQUESTED"
APPROVED_STATE = "APPROVED"
REJECTED_STATE = "REJECTED"
CANCELLED_STATE = "CANCELLED"


class AccountPurgeApprovalServiceError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.message = message
        self.code = code


class AccountPurgeApprovalNotFoundError(AccountPurgeApprovalServiceError):
    def __init__(self):
        super().__init__("Account purge request was not found.", "REQUEST_NOT_FOUND")


@dataclass(frozen=True)
class AccountPurgeRequestSummary:
    id: int
    state: str
    version: int
    requester_id: int | None
    target_user_id: int
    managing_workspace_id: int
    approver_id: int | None
    approved_at: object | None
    rejected_at: object | None
    cancelled_at: object | None


class AccountPurgeApprovalService:
    """Owns only REQUESTED -> approval/rejection/cancellation transitions."""

    @staticmethod
    def _new_session():
        return sessionmaker(bind=db.engine, autoflush=False, expire_on_commit=False)()

    @staticmethod
    def _summary(request):
        return AccountPurgeRequestSummary(
            id=request.id,
            state=request.state,
            version=request.version,
            requester_id=request.requester_id,
            target_user_id=request.target_user_id,
            managing_workspace_id=request.managing_workspace_id,
            approver_id=request.approver_id,
            approved_at=request.approved_at,
            rejected_at=request.rejected_at,
            cancelled_at=request.cancelled_at,
        )

    @staticmethod
    def _clean_reason(value, field):
        if not isinstance(value, str) or any(ord(char) < 32 for char in value):
            raise AccountPurgeApprovalServiceError(f"{field} is invalid.", "INVALID_REASON")
        value = " ".join(value.strip().split())
        if not value or len(value) > 2000:
            raise AccountPurgeApprovalServiceError(f"{field} is required.", "INVALID_REASON")
        return value

    @staticmethod
    def _check_version(request, expected_version):
        if expected_version is not None and request.version != expected_version:
            raise AccountPurgeApprovalServiceError(
                "The account purge request version is stale.", "REQUEST_VERSION_CONFLICT"
            )

    @staticmethod
    def _load_request_state(session, request_id, lock=True):
        request = session.query(AccountPurgeRequest).populate_existing().with_for_update().filter(
            AccountPurgeRequest.id == request_id
        ).one_or_none()
        if request is None:
            raise AccountPurgeApprovalNotFoundError()
        state = AccountPurgeService._load_existing_request_state_after_request_lock(session, request, lock=lock)
        return state, request

    @staticmethod
    def _approver(session, approver_user_id, requester_id, target_user_id, executor_id=None):
        approver = session.query(User).filter(User.id == approver_user_id).with_for_update().one_or_none()
        if (
            approver is None
            or not is_approval_owner(approver)
            or not approver.is_active
            or approver.deleted_at is not None
            or not approver.is_approval_active
        ):
            raise AccountPurgeApprovalServiceError(
                "Approver is not authorized.", "APPROVER_NOT_AUTHORIZED"
            )
        if approver.id == requester_id:
            raise AccountPurgeApprovalServiceError(
                "Requester and approver must be different.", "REQUESTER_APPROVER_CONFLICT"
            )
        if approver.id == target_user_id:
            raise AccountPurgeApprovalServiceError(
                "Approver and target must be different.", "APPROVER_TARGET_CONFLICT"
            )
        if executor_id is not None and approver.id == executor_id:
            raise AccountPurgeApprovalServiceError(
                "Approver and execution actor must be different.", "APPROVER_EXECUTION_CONFLICT"
            )
        return approver

    @staticmethod
    def _require_requested(request):
        if request.state != REQUESTED_STATE:
            raise AccountPurgeApprovalServiceError(
                "The request is not in REQUESTED state.", "INVALID_REQUEST_STATE"
            )

    @staticmethod
    def _add_lifecycle_event(session, request, actor, event_type, from_state, to_state, safe_detail):
        session.add(AccountPurgeLifecycleEvent(
            request_id=request.id,
            target_user_id=request.target_user_id,
            managing_workspace_id=request.managing_workspace_id,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            actor_id=actor.id,
            actor_name_snapshot=(actor.full_name or actor.username)[:100],
            actor_email_snapshot=actor.email,
            actor_role_snapshot=normalize_role_value(actor.role),
            safe_detail=safe_detail[:2000],
            created_at=utc_now(),
        ))

    @staticmethod
    def inspect_request(*, request_id):
        session = AccountPurgeApprovalService._new_session()
        try:
            request = session.query(AccountPurgeRequest).filter(
                AccountPurgeRequest.id == request_id
            ).one_or_none()
            if request is None:
                raise AccountPurgeApprovalNotFoundError()
            return AccountPurgeApprovalService._summary(request)
        finally:
            session.close()

    @staticmethod
    def approve_request(*, request_id, approver_user_id, expected_version=None):
        session = AccountPurgeApprovalService._new_session()
        try:
            state, request = AccountPurgeApprovalService._load_request_state(session, request_id)
            AccountPurgeApprovalService._check_version(request, expected_version)
            AccountPurgeApprovalService._require_requested(request)
            approver = AccountPurgeApprovalService._approver(
                session, approver_user_id, request.requester_id,
                request.target_user_id, request.executor_id,
            )
            result = AccountPurgeService._evaluate(
                state, request.requester_id, request.target_user_id,
                request.managing_workspace_id, exclude_request_id=request.id,
            )
            if not result.eligible:
                code = "ACTIVE_LEGAL_HOLD" if result.reason_code == "ACTIVE_LEGAL_HOLD" else "TARGET_NO_LONGER_ELIGIBLE"
                raise AccountPurgeApprovalServiceError(result.reason, code)
            previous_state = request.state
            request.state = APPROVED_STATE
            request.approver_id = approver.id
            request.approver_name_snapshot = (approver.full_name or approver.username)[:100]
            request.approver_email_snapshot = approver.email
            request.approver_role_snapshot = normalize_role_value(approver.role)
            request.approved_at = utc_now()
            request.version += 1
            AccountPurgeApprovalService._add_lifecycle_event(
                session, request, approver, "APPROVED", previous_state,
                APPROVED_STATE, "Account purge request approved.",
            )
            session.commit()
            return AccountPurgeApprovalService._summary(request)
        except AccountPurgeApprovalServiceError:
            session.rollback()
            raise
        except SQLAlchemyError as error:
            session.rollback()
            raise AccountPurgeApprovalServiceError(
                "Account purge approval could not be persisted.", "PERSISTENCE_FAILURE"
            ) from error
        except Exception as error:
            session.rollback()
            raise AccountPurgeApprovalServiceError(
                "Account purge approval failed safely.", "PERSISTENCE_FAILURE"
            ) from error
        finally:
            session.close()

    @staticmethod
    def reject_request(*, request_id, approver_user_id, rejection_reason, expected_version=None):
        session = AccountPurgeApprovalService._new_session()
        try:
            _state, request = AccountPurgeApprovalService._load_request_state(session, request_id)
            AccountPurgeApprovalService._check_version(request, expected_version)
            AccountPurgeApprovalService._require_requested(request)
            reason = AccountPurgeApprovalService._clean_reason(rejection_reason, "Rejection reason")
            approver = AccountPurgeApprovalService._approver(
                session, approver_user_id, request.requester_id,
                request.target_user_id, request.executor_id,
            )
            previous_state = request.state
            now = utc_now()
            request.state = REJECTED_STATE
            request.approver_id = approver.id
            request.approver_name_snapshot = (approver.full_name or approver.username)[:100]
            request.approver_email_snapshot = approver.email
            request.approver_role_snapshot = normalize_role_value(approver.role)
            request.rejected_at = now
            request.terminal_at = now
            request.rejection_reason = reason
            request.version += 1
            AccountPurgeApprovalService._add_lifecycle_event(
                session, request, approver, "REJECTED", previous_state,
                REJECTED_STATE, reason,
            )
            session.commit()
            return AccountPurgeApprovalService._summary(request)
        except AccountPurgeApprovalServiceError:
            session.rollback()
            raise
        except Exception as error:
            session.rollback()
            raise AccountPurgeApprovalServiceError(
                "Account purge rejection failed safely.", "PERSISTENCE_FAILURE"
            ) from error
        finally:
            session.close()

    @staticmethod
    def cancel_request(*, request_id, requester_user_id, cancellation_reason=None, expected_version=None):
        session = AccountPurgeApprovalService._new_session()
        try:
            state, request = AccountPurgeApprovalService._load_request_state(session, request_id)
            AccountPurgeApprovalService._check_version(request, expected_version)
            AccountPurgeApprovalService._require_requested(request)
            if request.requester_id != requester_user_id:
                raise AccountPurgeApprovalServiceError(
                    "Only the original requester may cancel this request.", "REQUESTER_NOT_AUTHORIZED"
                )
            requester = state["requester"]
            if requester is None:
                raise AccountPurgeApprovalServiceError(
                    "The original requester is no longer available.", "REQUESTER_NOT_AUTHORIZED"
                )
            reason = None
            if cancellation_reason is not None:
                reason = AccountPurgeApprovalService._clean_reason(cancellation_reason, "Cancellation reason")
            previous_state = request.state
            now = utc_now()
            request.state = CANCELLED_STATE
            request.cancelled_at = now
            request.terminal_at = now
            request.cancellation_reason = reason
            request.version += 1
            AccountPurgeApprovalService._add_lifecycle_event(
                session, request, requester, "CANCELLED", previous_state,
                CANCELLED_STATE, reason or "Account purge request cancelled.",
            )
            session.commit()
            return AccountPurgeApprovalService._summary(request)
        except AccountPurgeApprovalServiceError:
            session.rollback()
            raise
        except Exception as error:
            session.rollback()
            raise AccountPurgeApprovalServiceError(
                "Account purge cancellation failed safely.", "PERSISTENCE_FAILURE"
            ) from error
        finally:
            session.close()
