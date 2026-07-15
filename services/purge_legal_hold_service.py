import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.auth.permissions import is_approval_owner
from extensions import db
from models.activity_log import ActivityLog
from models.purge import PurgeLegalHold, workspace_terminal_state_table
from models.user import User
from models.workspace import Workspace
from utils.timezone_utils import utc_now


class PurgeLegalHoldServiceError(Exception):
    def __init__(self, message, code="LEGAL_HOLD_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


class PurgeLegalHoldAuthorizationError(PurgeLegalHoldServiceError):
    def __init__(self, message="Actor is not authorized for legal-hold administration."):
        super().__init__(message, "UNAUTHORIZED")


class PurgeLegalHoldNotFoundError(PurgeLegalHoldServiceError):
    def __init__(self, message="Legal hold or workspace was not found."):
        super().__init__(message, "NOT_FOUND")


class PurgeLegalHoldConflictError(PurgeLegalHoldServiceError):
    def __init__(self, message, code="CONFLICT"):
        super().__init__(message, code)


@dataclass(frozen=True)
class LegalHoldSummary:
    id: int
    hold_id: str
    workspace_id: int
    hold_type: str
    status: str
    source: str
    external_reference: str | None
    reason: str
    placed_by_id: int | None
    placed_by_snapshot: str
    placed_at: object
    released_by_id: int | None
    released_by_snapshot: str | None
    released_at: object | None
    release_reason: str | None


class PurgeLegalHoldService:
    _HOLD_TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$")

    @staticmethod
    def _new_session():
        return sessionmaker(bind=db.engine, autoflush=False, expire_on_commit=False)()

    @staticmethod
    def _actor(session, actor_user_id):
        actor = session.query(User).filter(User.id == actor_user_id).one_or_none()
        if (
            actor is None
            or not is_approval_owner(actor)
            or not actor.is_active
            or actor.deleted_at is not None
            or actor.approval_status != User.APPROVAL_ACTIVE
        ):
            raise PurgeLegalHoldAuthorizationError()
        return actor

    @staticmethod
    def _clean_text(value, field, maximum=1000):
        if not isinstance(value, str):
            raise PurgeLegalHoldConflictError(f"{field} is required.", "INVALID_INPUT")
        if any(ord(char) < 32 for char in value):
            raise PurgeLegalHoldConflictError(f"{field} is invalid.", "INVALID_INPUT")
        value = " ".join(value.strip().split())
        if not value or len(value) > maximum:
            raise PurgeLegalHoldConflictError(f"{field} is invalid.", "INVALID_INPUT")
        return value

    @staticmethod
    def _phrase(value, expected, legacy=None):
        accepted = {expected, legacy} - {None}
        if not isinstance(value, str) or value.strip() not in accepted:
            raise PurgeLegalHoldConflictError("Câu xác nhận không hợp lệ.", "INVALID_CONFIRMATION")

    @staticmethod
    def _terminal(session, workspace_id, lock=True):
        statement = select(workspace_terminal_state_table).where(workspace_terminal_state_table.c.id == workspace_id)
        if lock:
            statement = statement.with_for_update()
        return session.execute(statement).mappings().one_or_none()

    @staticmethod
    def _workspace_for_mutation(session, workspace_id):
        workspace = session.query(Workspace).filter(Workspace.id == workspace_id).with_for_update().one_or_none()
        terminal = PurgeLegalHoldService._terminal(session, workspace_id)
        if workspace is None or terminal is None:
            raise PurgeLegalHoldNotFoundError()
        if terminal["purged_at"] is not None or terminal["purge_request_id"] is not None:
            raise PurgeLegalHoldConflictError("Cơ sở đã kết thúc không thể thay đổi lệnh giữ dữ liệu pháp lý.", "TERMINAL_WORKSPACE")
        return workspace, terminal

    @staticmethod
    def _summary(hold):
        return LegalHoldSummary(
            id=hold.id, hold_id=hold.hold_id, workspace_id=hold.workspace_id,
            hold_type=hold.hold_type, status=hold.status, source=hold.source,
            external_reference=hold.external_reference, reason=hold.reason,
            placed_by_id=hold.placed_by_id, placed_by_snapshot=hold.placed_by_snapshot,
            placed_at=hold.placed_at, released_by_id=hold.released_by_id,
            released_by_snapshot=hold.released_by_snapshot, released_at=hold.released_at,
            release_reason=hold.release_reason,
        )

    @staticmethod
    def _audit(session, *, actor, workspace, hold, action, reason):
        session.add(ActivityLog(
            module="Permanent Purge",
            action=action,
            description=(f"{action} hold {hold.hold_id} on workspace {workspace.slug}: {reason}")[:2000],
            reference_id=hold.id,
            user_id=actor.id,
            workspace_id=workspace.id,
            severity="WARNING",
        ))

    @staticmethod
    def create_legal_hold(*, workspace_id, actor_user_id, hold_type, reason, confirmation_phrase, source="approval_portal"):
        session = PurgeLegalHoldService._new_session()
        try:
            actor = PurgeLegalHoldService._actor(session, actor_user_id)
            workspace, _terminal = PurgeLegalHoldService._workspace_for_mutation(session, workspace_id)
            hold_type = PurgeLegalHoldService._clean_text(hold_type, "Hold type", 50).upper()
            if not PurgeLegalHoldService._HOLD_TYPE.fullmatch(hold_type):
                raise PurgeLegalHoldConflictError("Loại lệnh giữ không hợp lệ.", "INVALID_INPUT")
            reason = PurgeLegalHoldService._clean_text(reason, "Reason")
            source = PurgeLegalHoldService._clean_text(source, "Source", 100)
            PurgeLegalHoldService._phrase(
                confirmation_phrase,
                f"GIỮ DỮ LIỆU PHÁP LÝ {workspace.slug}",
                legacy=f"HOLD {workspace.slug}",
            )
            hold = PurgeLegalHold(
                hold_id=str(uuid.uuid4()), workspace_id=workspace.id, hold_type=hold_type,
                status="ACTIVE", source=source, reason=reason,
                placed_by_id=actor.id, placed_by_snapshot=actor.username[:100],
                placed_at=utc_now(), released_by_id=None, released_by_snapshot=None,
                released_at=None, release_reason=None,
            )
            session.add(hold)
            session.flush()
            PurgeLegalHoldService._audit(session, actor=actor, workspace=workspace, hold=hold,
                                         action="LEGAL_HOLD_CREATE", reason=reason)
            session.commit()
            return PurgeLegalHoldService._summary(hold)
        except IntegrityError as error:
            session.rollback()
            raise PurgeLegalHoldConflictError("Legal hold could not be persisted.", "PERSISTENCE_ERROR") from error
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def release_legal_hold(*, hold_id, actor_user_id, release_reason, confirmation_phrase, expected_workspace_id=None):
        session = PurgeLegalHoldService._new_session()
        try:
            actor = PurgeLegalHoldService._actor(session, actor_user_id)
            hold_identity = session.query(PurgeLegalHold).filter(PurgeLegalHold.hold_id == hold_id).one_or_none()
            if hold_identity is None:
                raise PurgeLegalHoldNotFoundError()
            if expected_workspace_id is not None and hold_identity.workspace_id != expected_workspace_id:
                raise PurgeLegalHoldNotFoundError()
            workspace, _terminal = PurgeLegalHoldService._workspace_for_mutation(session, hold_identity.workspace_id)
            hold = session.query(PurgeLegalHold).filter(
                PurgeLegalHold.id == hold_identity.id
            ).populate_existing().with_for_update().one_or_none()
            if hold is None or hold.workspace_id != workspace.id:
                raise PurgeLegalHoldNotFoundError()
            if hold.status != "ACTIVE" or hold.released_at is not None or hold.released_by_snapshot or hold.release_reason:
                raise PurgeLegalHoldConflictError("Lệnh giữ dữ liệu pháp lý không còn hoạt động.", "ALREADY_RELEASED")
            release_reason = PurgeLegalHoldService._clean_text(release_reason, "Release reason")
            PurgeLegalHoldService._phrase(
                confirmation_phrase,
                f"GỠ GIỮ DỮ LIỆU PHÁP LÝ {hold.hold_id}",
                legacy=f"RELEASE {hold.hold_id}",
            )
            hold.status = "RELEASED"
            hold.released_by_id = actor.id
            hold.released_by_snapshot = actor.username[:100]
            hold.released_at = utc_now()
            hold.release_reason = release_reason
            hold.updated_at = utc_now()
            PurgeLegalHoldService._audit(session, actor=actor, workspace=workspace, hold=hold,
                                         action="LEGAL_HOLD_RELEASE", reason=release_reason)
            session.commit()
            return PurgeLegalHoldService._summary(hold)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def list_legal_holds(*, workspace_id, actor_user_id):
        session = PurgeLegalHoldService._new_session()
        try:
            PurgeLegalHoldService._actor(session, actor_user_id)
            workspace = session.query(Workspace).filter(Workspace.id == workspace_id).one_or_none()
            if workspace is None:
                raise PurgeLegalHoldNotFoundError()
            return [PurgeLegalHoldService._summary(hold) for hold in session.query(PurgeLegalHold).filter(
                PurgeLegalHold.workspace_id == workspace.id
            ).order_by(PurgeLegalHold.id).all()]
        finally:
            session.close()

    @staticmethod
    def get_workspace_target(*, workspace_id, actor_user_id):
        session = PurgeLegalHoldService._new_session()
        try:
            PurgeLegalHoldService._actor(session, actor_user_id)
            workspace = session.query(Workspace).filter(Workspace.id == workspace_id).one_or_none()
            terminal = PurgeLegalHoldService._terminal(session, workspace_id, lock=False)
            if workspace is None or terminal is None:
                raise PurgeLegalHoldNotFoundError()
            return {
                "id": workspace.id,
                "name": workspace.name,
                "slug": workspace.slug,
                "deleted_at": workspace.deleted_at,
                "purged": bool(terminal["purged_at"] is not None or terminal["purge_request_id"] is not None),
            }
        finally:
            session.close()
