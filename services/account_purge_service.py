"""Eligibility and request creation for the account-purge foundation.

This module deliberately stops at ``REQUESTED``.  Approval, execution,
identity mutation, session revocation, and avatar cleanup belong to later
tasks.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.auth.enums import UserRole, normalize_role_value
from extensions import db
from models.account_purge import (
    ACCOUNT_PURGE_TERMINAL_STATES,
    AccountPurgeLegalHold,
    AccountPurgeLifecycleEvent,
    AccountPurgeRequest,
    UserCreationProvenance,
)
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from utils.timezone_utils import utc_now


REQUEST_TERMINAL_STATES = {
    "REJECTED",
    "CANCELLED",
    "SUCCEEDED",
    "FAILED",
    "OUTCOME_UNKNOWN",
}
REQUESTED_STATE = "REQUESTED"
ELIGIBLE_TARGET_ROLES = {UserRole.ADMIN.value, UserRole.STAFF.value}
WORKSPACE_PROVENANCE_SOURCES = {"WORKSPACE_OWNER", "WORKSPACE_ADMIN"}


REASON_MESSAGES = {
    "ELIGIBLE": "Tài khoản đủ điều kiện để tạo yêu cầu xóa tài khoản.",
    "TARGET_NOT_FOUND": "Không tìm thấy tài khoản hoặc workspace đích.",
    "REQUESTER_NOT_ACTIVE_OWNER": "Người yêu cầu phải là OWNER đang hoạt động của workspace.",
    "SELF_PURGE_FORBIDDEN": "Không thể tạo yêu cầu xóa tài khoản của chính mình.",
    "TARGET_ROLE_PROTECTED": "Vai trò tài khoản đích được bảo vệ và không thể xóa.",
    "TARGET_ROLE_NOT_ELIGIBLE": "Chỉ tài khoản ADMIN hoặc STAFF mới thuộc phase này.",
    "TARGET_NOT_SOFT_DELETED": "Tài khoản chưa ở trạng thái removed của workspace.",
    "TARGET_STILL_ACTIVE": "Tài khoản vẫn còn membership active trong workspace.",
    "PROVENANCE_MISSING": "Tài khoản chưa có provenance workspace xác thực.",
    "PROVENANCE_UNKNOWN": "Provenance legacy của tài khoản không đủ để xác nhận an toàn.",
    "PROVENANCE_WORKSPACE_MISMATCH": "Provenance của tài khoản không thuộc workspace quản lý.",
    "PROVENANCE_SOURCE_NOT_ELIGIBLE": "Nguồn tạo tài khoản không thuộc workspace-managed flow.",
    "GOOGLE_ACCOUNT_NOT_SUPPORTED": "Tài khoản liên kết Google chưa được hỗ trợ trong phase này.",
    "EXTERNAL_WORKSPACE_HISTORY": "Tài khoản có lịch sử membership ở workspace khác.",
    "WORKSPACE_OWNERSHIP_HISTORY": "Tài khoản có lịch sử ownership ở workspace khác.",
    "ACTIVE_LEGAL_HOLD": "Tài khoản đang có legal hold hoạt động.",
    "ACTIVE_REQUEST_EXISTS": "Tài khoản đã có yêu cầu purge đang hoạt động.",
    "ALREADY_PURGED": "Tài khoản đã ở trạng thái purge terminal.",
    "INCONSISTENT_STATE": "Trạng thái tài khoản hoặc workspace không nhất quán.",
}


class AccountPurgeServiceError(Exception):
    """Base error with a deterministic safe code."""

    def __init__(self, message, code="ACCOUNT_PURGE_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


class AccountPurgeAuthorizationError(AccountPurgeServiceError):
    def __init__(self, message=None, code="REQUESTER_NOT_ACTIVE_OWNER"):
        super().__init__(message or REASON_MESSAGES[code], code)


class AccountPurgeNotFoundError(AccountPurgeServiceError):
    def __init__(self, message=None, code="TARGET_NOT_FOUND"):
        super().__init__(message or REASON_MESSAGES[code], code)


class AccountPurgeIneligibleError(AccountPurgeServiceError):
    def __init__(self, result):
        super().__init__(result.reason, result.reason_code)
        self.result = result


class AccountPurgeConflictError(AccountPurgeServiceError):
    def __init__(self, message=None, code="ACTIVE_REQUEST_EXISTS"):
        super().__init__(message or REASON_MESSAGES[code], code)


class AccountPurgePersistenceError(AccountPurgeServiceError):
    def __init__(self, message="Không thể lưu yêu cầu purge an toàn."):
        super().__init__(message, "PERSISTENCE_ERROR")


@dataclass(frozen=True)
class AccountPurgeEligibility:
    eligible: bool
    reason_code: str
    reason: str
    target_user_id: int | None
    managing_workspace_id: int | None
    target_role: str | None
    provenance_status: str
    soft_delete_status: str
    external_workspace_history_status: str
    legal_hold_status: str
    active_request_status: str

    def to_dict(self):
        return {
            "eligible": self.eligible,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "target_user_id": self.target_user_id,
            "managing_workspace_id": self.managing_workspace_id,
            "target_role": self.target_role,
            "provenance_status": self.provenance_status,
            "soft_delete_status": self.soft_delete_status,
            "external_workspace_history_status": self.external_workspace_history_status,
            "legal_hold_status": self.legal_hold_status,
            "active_request_status": self.active_request_status,
        }


class AccountPurgeService:
    """Read eligibility and atomically create a ``REQUESTED`` request."""

    @staticmethod
    def _new_session():
        return sessionmaker(bind=db.engine, autoflush=False, expire_on_commit=False)()

    @staticmethod
    def _result(code, *, target_user_id, managing_workspace_id, target_role=None,
                provenance_status="UNKNOWN", soft_delete_status="UNKNOWN",
                external_workspace_history_status="UNKNOWN", legal_hold_status="UNKNOWN",
                active_request_status="UNKNOWN"):
        return AccountPurgeEligibility(
            eligible=code == "ELIGIBLE",
            reason_code=code,
            reason=REASON_MESSAGES[code],
            target_user_id=target_user_id,
            managing_workspace_id=managing_workspace_id,
            target_role=target_role,
            provenance_status=provenance_status,
            soft_delete_status=soft_delete_status,
            external_workspace_history_status=external_workspace_history_status,
            legal_hold_status=legal_hold_status,
            active_request_status=active_request_status,
        )

    @staticmethod
    def _load_state(
        session,
        requester_id,
        target_user_id,
        managing_workspace_id,
        lock=False,
        exclude_request_id=None,
    ):
        """Load all mutable resources in the service's deterministic lock order."""
        def locked(query):
            return query.populate_existing().with_for_update() if lock else query

        workspace = locked(session.query(Workspace).filter(Workspace.id == managing_workspace_id)).one_or_none()
        requester = locked(session.query(User).filter(User.id == requester_id)).one_or_none()
        requester_membership = locked(
            session.query(WorkspaceMember).filter(
                WorkspaceMember.workspace_id == managing_workspace_id,
                WorkspaceMember.user_id == requester_id,
            ).order_by(WorkspaceMember.id)
        ).first()
        target = locked(session.query(User).filter(User.id == target_user_id)).one_or_none()
        provenance = locked(
            session.query(UserCreationProvenance).filter(UserCreationProvenance.user_id == target_user_id)
        ).one_or_none()
        memberships = locked(
            session.query(WorkspaceMember).filter(WorkspaceMember.user_id == target_user_id)
            .order_by(WorkspaceMember.workspace_id, WorkspaceMember.id)
        ).all()
        holds = locked(
            session.query(AccountPurgeLegalHold).filter(
                AccountPurgeLegalHold.target_user_id == target_user_id,
                (AccountPurgeLegalHold.managing_workspace_id.is_(None)
                 | (AccountPurgeLegalHold.managing_workspace_id == managing_workspace_id)),
            ).order_by(AccountPurgeLegalHold.id)
        ).all()
        requests = locked(
            session.query(AccountPurgeRequest).filter(
                AccountPurgeRequest.target_user_id == target_user_id,
            ).order_by(AccountPurgeRequest.id)
        ).all()
        external_created_workspaces = session.query(Workspace).filter(
            Workspace.created_by_id == target_user_id,
            Workspace.id != managing_workspace_id,
        ).order_by(Workspace.id).all()
        return {
            "workspace": workspace,
            "requester": requester,
            "requester_membership": requester_membership,
            "target": target,
            "provenance": provenance,
            "memberships": memberships,
            "holds": holds,
            "requests": requests,
            "exclude_request_id": exclude_request_id,
            "external_created_workspaces": external_created_workspaces,
        }

    @staticmethod
    def _evaluate(state, requester_id, target_user_id, managing_workspace_id, exclude_request_id=None):
        target = state["target"]
        requester = state["requester"]
        workspace = state["workspace"]
        target_role = normalize_role_value(getattr(target, "role", None)) if target else None

        if not requester or not workspace or not target:
            return AccountPurgeService._result(
                "TARGET_NOT_FOUND", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
            )
        requester_membership = state["requester_membership"]
        if (
            requester.id == target_user_id
            or not requester.is_active
            or requester.deleted_at is not None
            or not requester.is_approval_active
            or normalize_role_value(requester.role) != UserRole.OWNER.value
            or not requester_membership
            or requester_membership.status != "active"
            or normalize_role_value(requester_membership.role) != UserRole.OWNER.value
        ):
            code = "SELF_PURGE_FORBIDDEN" if requester.id == target_user_id else "REQUESTER_NOT_ACTIVE_OWNER"
            return AccountPurgeService._result(
                code, target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
            )

        if target.account_purge_state == "PURGED_TOMBSTONE":
            return AccountPurgeService._result(
                "ALREADY_PURGED", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                soft_delete_status="TERMINAL",
            )
        if target.account_purge_state not in (None, "NOT_PURGED"):
            return AccountPurgeService._result(
                "INCONSISTENT_STATE", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                soft_delete_status="INCONSISTENT",
            )

        memberships = state["memberships"]
        managing_memberships = [m for m in memberships if m.workspace_id == managing_workspace_id]
        managing_membership = managing_memberships[0] if managing_memberships else None
        if not managing_membership or managing_membership.status != "removed":
            return AccountPurgeService._result(
                "TARGET_NOT_SOFT_DELETED", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                soft_delete_status="ACTIVE" if managing_membership and managing_membership.status == "active" else "NOT_REMOVED",
            )
        if managing_membership.removed_at is None or target.deleted_at is not None:
            return AccountPurgeService._result(
                "INCONSISTENT_STATE", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                soft_delete_status="INCONSISTENT",
            )
        if any(m.status == "active" for m in managing_memberships):
            return AccountPurgeService._result(
                "TARGET_STILL_ACTIVE", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                soft_delete_status="ACTIVE",
            )

        if target_role in {UserRole.OWNER.value, UserRole.APPROVAL_OWNER.value}:
            return AccountPurgeService._result(
                "TARGET_ROLE_PROTECTED", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                soft_delete_status="REMOVED",
            )
        if target_role not in ELIGIBLE_TARGET_ROLES or normalize_role_value(managing_membership.role) != target_role:
            code = "INCONSISTENT_STATE" if normalize_role_value(managing_membership.role) != target_role else "TARGET_ROLE_NOT_ELIGIBLE"
            return AccountPurgeService._result(
                code, target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                soft_delete_status="REMOVED",
            )

        external_memberships = [m for m in memberships if m.workspace_id != managing_workspace_id]
        if external_memberships:
            return AccountPurgeService._result(
                "EXTERNAL_WORKSPACE_HISTORY", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                provenance_status="PENDING", soft_delete_status="REMOVED",
                external_workspace_history_status="PRESENT",
            )
        if state["external_created_workspaces"]:
            return AccountPurgeService._result(
                "WORKSPACE_OWNERSHIP_HISTORY", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                provenance_status="PENDING", soft_delete_status="REMOVED",
                external_workspace_history_status="PRESENT",
            )

        provider = (target.auth_provider or "local").strip().lower()
        if provider == "google" or target.oauth_id:
            return AccountPurgeService._result(
                "GOOGLE_ACCOUNT_NOT_SUPPORTED", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                provenance_status="PENDING", soft_delete_status="REMOVED",
                external_workspace_history_status="CLEAR",
            )

        provenance = state["provenance"]
        if provenance is None:
            return AccountPurgeService._result(
                "PROVENANCE_MISSING", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                provenance_status="MISSING", soft_delete_status="REMOVED",
                external_workspace_history_status="CLEAR",
            )
        if provenance.creation_source == "LEGACY_UNKNOWN":
            return AccountPurgeService._result(
                "PROVENANCE_UNKNOWN", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                provenance_status="UNKNOWN", soft_delete_status="REMOVED",
                external_workspace_history_status="CLEAR",
            )
        if provenance.created_in_workspace_id != managing_workspace_id:
            return AccountPurgeService._result(
                "PROVENANCE_WORKSPACE_MISMATCH", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                provenance_status="MISMATCH", soft_delete_status="REMOVED",
                external_workspace_history_status="CLEAR",
            )
        if (
            provenance.creation_source not in WORKSPACE_PROVENANCE_SOURCES
            or provenance.provenance_version <= 0
            or normalize_role_value(provenance.created_role) != target_role
        ):
            return AccountPurgeService._result(
                "PROVENANCE_SOURCE_NOT_ELIGIBLE", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                provenance_status="INVALID", soft_delete_status="REMOVED",
                external_workspace_history_status="CLEAR",
            )
        if provenance.created_by_user_id:
            creator = state["target"].query.session.get(User, provenance.created_by_user_id)
            if creator and ((creator.auth_provider or "local").strip().lower() == "google" or creator.oauth_id):
                return AccountPurgeService._result(
                    "PROVENANCE_SOURCE_NOT_ELIGIBLE", target_user_id=target_user_id,
                    managing_workspace_id=managing_workspace_id, target_role=target_role,
                    provenance_status="INVALID", soft_delete_status="REMOVED",
                    external_workspace_history_status="CLEAR",
                )

        if any(hold.state == "ACTIVE" for hold in state["holds"]):
            return AccountPurgeService._result(
                "ACTIVE_LEGAL_HOLD", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                provenance_status="VALID", soft_delete_status="REMOVED",
                external_workspace_history_status="CLEAR", legal_hold_status="ACTIVE",
            )
        active_requests = [
            r for r in state["requests"]
            if r.state not in REQUEST_TERMINAL_STATES
            and r.id != exclude_request_id
        ]
        if active_requests:
            return AccountPurgeService._result(
                "ACTIVE_REQUEST_EXISTS", target_user_id=target_user_id,
                managing_workspace_id=managing_workspace_id, target_role=target_role,
                provenance_status="VALID", soft_delete_status="REMOVED",
                external_workspace_history_status="CLEAR", legal_hold_status="CLEAR",
                active_request_status="ACTIVE",
            )
        return AccountPurgeService._result(
            "ELIGIBLE", target_user_id=target_user_id,
            managing_workspace_id=managing_workspace_id, target_role=target_role,
            provenance_status="VALID", soft_delete_status="REMOVED",
            external_workspace_history_status="CLEAR", legal_hold_status="CLEAR",
            active_request_status="CLEAR",
        )

    @staticmethod
    def inspect_eligibility(*, requester_id, target_user_id, managing_workspace_id):
        session = AccountPurgeService._new_session()
        try:
            state = AccountPurgeService._load_state(
                session, requester_id, target_user_id, managing_workspace_id,
            )
            return AccountPurgeService._evaluate(
                state, requester_id, target_user_id, managing_workspace_id,
            )
        finally:
            session.close()

    @staticmethod
    def create_request(*, requester_id, target_user_id, managing_workspace_id, reason, now=None):
        if not isinstance(reason, str) or not reason.strip():
            raise AccountPurgeConflictError("Lý do yêu cầu không được để trống.", "INVALID_REASON")
        normalized_reason = " ".join(reason.split())[:2000]
        event_at = now or utc_now()
        if not isinstance(event_at, datetime):
            raise AccountPurgeConflictError("Thời điểm yêu cầu không hợp lệ.", "INVALID_TIMESTAMP")

        session = AccountPurgeService._new_session()
        try:
            state = AccountPurgeService._load_state(
                session, requester_id, target_user_id, managing_workspace_id, lock=True,
            )
            result = AccountPurgeService._evaluate(
                state, requester_id, target_user_id, managing_workspace_id,
            )
            if not result.eligible:
                if result.reason_code == "REQUESTER_NOT_ACTIVE_OWNER":
                    raise AccountPurgeAuthorizationError(result.reason, result.reason_code)
                if result.reason_code == "ACTIVE_REQUEST_EXISTS":
                    raise AccountPurgeConflictError(result.reason, result.reason_code)
                raise AccountPurgeIneligibleError(result)

            requester = state["requester"]
            target = state["target"]
            provenance = state["provenance"]
            request = AccountPurgeRequest(
                target_user_id=target.id,
                managing_workspace_id=managing_workspace_id,
                target_provenance_id=provenance.id,
                state=REQUESTED_STATE,
                reason=normalized_reason,
                version=1,
                created_at=event_at,
                updated_at=event_at,
                requester_id=requester.id,
                requester_name_snapshot=(requester.full_name or requester.username)[:100],
                requester_email_snapshot=requester.email,
                requester_role_snapshot=normalize_role_value(requester.role),
                requested_at=event_at,
                eligible_at=event_at,
                target_username_snapshot=target.username,
                target_email_snapshot=target.email,
                target_role_snapshot=normalize_role_value(target.role),
                target_auth_provider_snapshot=(target.auth_provider or "local").strip().lower(),
            )
            session.add(request)
            session.flush()
            session.add(AccountPurgeLifecycleEvent(
                request_id=request.id,
                target_user_id=target.id,
                managing_workspace_id=managing_workspace_id,
                event_type=REQUESTED_STATE,
                from_state=None,
                to_state=REQUESTED_STATE,
                actor_id=requester.id,
                actor_name_snapshot=(requester.full_name or requester.username)[:100],
                actor_email_snapshot=requester.email,
                actor_role_snapshot=normalize_role_value(requester.role),
                safe_detail="Account purge request created.",
                created_at=event_at,
            ))
            session.commit()
            return request
        except AccountPurgeServiceError:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise AccountPurgeConflictError(code="ACTIVE_REQUEST_EXISTS") from exc
        except Exception as exc:
            session.rollback()
            raise AccountPurgePersistenceError() from exc
        finally:
            session.close()
