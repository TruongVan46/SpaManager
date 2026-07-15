import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.auth.permissions import is_approval_owner
from extensions import db
from models.purge import (
    PurgeLegalHold,
    PurgeLifecycleEvent,
    WorkspacePurgeRequest,
    workspace_terminal_state_table,
)
from models.user import User
from models.workspace import Workspace
from services.purge_manifest import (
    DESTRUCTIVE_SCOPES,
    PurgeManifestError,
    build_manifest,
    build_purge_plan,
    validate_stored_manifest,
)
from utils.timezone_utils import utc_now


RETENTION_DAYS = 30
RETENTION_POLICY_VERSION = "workspace-purge-30d-v1"
REQUESTED_STATUSES = {"REQUESTED", "PENDING_RETENTION", "PENDING_APPROVAL"}
APPROVABLE_STATUS = "PENDING_APPROVAL"
TERMINAL_STATUSES = {"COMPLETED", "CANCELLED", "REJECTED", "EXPIRED", "FAILED"}
INVALIDATABLE_STATUSES = {"REQUESTED", "PENDING_RETENTION", "PENDING_APPROVAL", "APPROVED", "BLOCKED", "RETRY_PENDING"}


class PurgeRequestServiceError(Exception):
    def __init__(self, message, code="PURGE_REQUEST_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


class PurgeRequestNotFoundError(PurgeRequestServiceError):
    def __init__(self, message="Purge request or workspace was not found."):
        super().__init__(message, "NOT_FOUND")


class PurgeRequestAuthorizationError(PurgeRequestServiceError):
    def __init__(self, message="Actor is not authorized for this purge request."):
        super().__init__(message, "UNAUTHORIZED")


class PurgeRequestConflictError(PurgeRequestServiceError):
    def __init__(self, message, code="CONFLICT"):
        super().__init__(message, code)


@dataclass(frozen=True)
class PurgeRequestSummary:
    id: int
    lifecycle_id: str
    workspace_id: int
    workspace_name: str
    workspace_slug: str
    status: str
    requested_by_snapshot: str
    requested_by_id: int
    approved_by_snapshot: str | None
    approved_by_id: int | None
    requested_at: datetime
    eligible_at: datetime
    approved_at: datetime | None
    rejected_at: datetime | None
    cancelled_at: datetime | None
    invalidated_at: datetime | None
    outcome_unknown: bool
    manifest_hash: str
    destructive_counts: dict
    preserved: list
    external_assets: list
    hold_check_status: str
    failure_code: str | None
    failure_summary: str | None
    manifest_valid: bool
    manifest_error: str | None
    retention_reached: bool


@dataclass(frozen=True)
class PurgeRequestPage:
    items: list
    page: int
    per_page: int
    total: int

    @property
    def pages(self):
        return max(1, (self.total + self.per_page - 1) // self.per_page)

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def next_num(self):
        return self.page + 1

    @property
    def prev_num(self):
        return self.page - 1


class PurgeRequestService:
    @staticmethod
    def _new_session():
        return sessionmaker(bind=db.engine, autoflush=False, expire_on_commit=False)()

    @staticmethod
    def _now(value):
        if value is not None and not isinstance(value, datetime):
            raise PurgeRequestConflictError("Thời điểm quy trình phải là ngày giờ hợp lệ.", "INVALID_NOW")
        return value or utc_now()

    @staticmethod
    def _actor(session, actor_id):
        actor = session.query(User).filter(User.id == actor_id).one_or_none()
        if actor is None or not is_approval_owner(actor) or not actor.is_active or actor.deleted_at is not None or actor.approval_status != User.APPROVAL_ACTIVE:
            raise PurgeRequestAuthorizationError()
        return actor

    @staticmethod
    def _phrase(value, expected, legacy=None):
        accepted = {expected, legacy} - {None}
        if not isinstance(value, str) or value.strip() not in accepted:
            raise PurgeRequestConflictError("Câu xác nhận không hợp lệ.", "INVALID_CONFIRMATION")

    @staticmethod
    def _terminal(session, workspace_id, lock=True):
        query = select(workspace_terminal_state_table).where(workspace_terminal_state_table.c.id == workspace_id)
        if lock:
            query = query.with_for_update()
        return session.execute(query).mappings().one_or_none()

    @staticmethod
    def _logo_present(session, workspace_id):
        from models.setting import Setting
        rows = session.query(Setting).filter(Setting.workspace_id == workspace_id, Setting.key == "spa_logo").all()
        return any(row.value is not None and (not isinstance(row.value, str) or row.value != "") for row in rows)

    @staticmethod
    def _holds_state(session, workspace_id, lock=False, holds=None):
        if holds is None:
            query = session.query(PurgeLegalHold).filter(PurgeLegalHold.workspace_id == workspace_id).order_by(PurgeLegalHold.id)
            if lock:
                query = query.with_for_update()
            holds = query.all()
        for hold in holds:
            if hold.status != "RELEASED" or hold.released_at is None or not hold.released_by_snapshot or not hold.release_reason:
                return "BLOCKED"
        return "CLEAR"

    @staticmethod
    def _event(session, request, workspace, actor_id, event_type, before, after, event_at, summary):
        sequence = session.query(func.max(PurgeLifecycleEvent.event_sequence)).filter(PurgeLifecycleEvent.request_id == request.id).scalar() or 0
        sequence += sum(
            1 for pending in session.new
            if isinstance(pending, PurgeLifecycleEvent) and pending.request_id == request.id
        )
        session.add(PurgeLifecycleEvent(
            request_id=request.id,
            lifecycle_id_snapshot=request.lifecycle_id,
            workspace_id=workspace.id,
            workspace_name_snapshot=workspace.name,
            event_sequence=sequence + 1,
            event_type=event_type,
            actor_id=actor_id,
            actor_snapshot=session.query(User).filter(User.id == actor_id).one_or_none().username[:100] if actor_id else "SYSTEM",
            event_at=event_at,
            status_before=before,
            status_after=after,
            reason_code=event_type.upper(),
            sanitized_summary=summary[:1000],
        ))

    @staticmethod
    def _manifest_summary(request):
        error = None
        try:
            if not isinstance(request.manifest_canonical_text, str):
                raise ValueError("manifest text unavailable")
            if request.manifest_version != "purge-manifest-v1":
                raise ValueError("unsupported manifest version")
            import hashlib
            if hashlib.sha256(request.manifest_canonical_text.encode("utf-8")).hexdigest() != request.manifest_hash:
                raise ValueError("manifest hash mismatch")
            payload = json.loads(request.manifest_canonical_text)
            if not isinstance(payload, dict) or not isinstance(payload.get("destructive"), list):
                raise ValueError("manifest shape invalid")
            if payload.get("manifest_version") != "purge-manifest-v1":
                raise ValueError("manifest payload version invalid")
            allowed_tables = {table for table, _action, _scope in DESTRUCTIVE_SCOPES}
            seen_tables = set()
            for item in payload["destructive"]:
                if not isinstance(item, dict) or not isinstance(item.get("table"), str) or not re.fullmatch(r"[A-Za-z0-9_]{1,100}", item["table"]):
                    raise ValueError("destructive manifest item invalid")
                if item["table"] not in allowed_tables or item["table"] in seen_tables:
                    raise ValueError("destructive manifest table invalid")
                seen_tables.add(item["table"])
                if isinstance(item.get("count"), bool) or not isinstance(item.get("count"), int) or item["count"] < 0:
                    raise ValueError("destructive manifest count invalid")
            for key in ("preserved", "external_assets"):
                if not isinstance(payload.get(key), list) or any(not isinstance(item, dict) for item in payload[key]):
                    raise ValueError("manifest disposition shape invalid")
            destructive = {item.get("table"): item.get("count", 0) for item in payload.get("destructive", []) if isinstance(item, dict)}
            return destructive, payload.get("preserved", []), payload.get("external_assets", []), True, None
        except (TypeError, ValueError, AttributeError, UnicodeError):
            return {}, [], [], False, "MANIFEST_INVALID"

    @staticmethod
    def summarize(request, now=None):
        destructive, preserved, external_assets, manifest_valid, manifest_error = PurgeRequestService._manifest_summary(request)
        current_time = now or utc_now()
        return PurgeRequestSummary(
            id=request.id, lifecycle_id=request.lifecycle_id, workspace_id=request.workspace_id,
            workspace_name=request.target_workspace_name, workspace_slug=request.target_workspace_slug,
            status=request.status, requested_by_snapshot=request.requested_by_snapshot,
            requested_by_id=request.requested_by_id,
            approved_by_snapshot=request.approved_by_snapshot, requested_at=request.requested_at,
            approved_by_id=request.approved_by_id,
            eligible_at=request.eligible_at, approved_at=request.approved_at, rejected_at=request.rejected_at,
            cancelled_at=request.cancelled_at, invalidated_at=request.invalidated_at,
            outcome_unknown=bool(request.outcome_unknown), manifest_hash=request.manifest_hash,
            destructive_counts=destructive, preserved=preserved, external_assets=external_assets,
            hold_check_status=request.hold_check_status, failure_code=request.failure_code,
            failure_summary=request.failure_summary, manifest_valid=manifest_valid,
            manifest_error=manifest_error, retention_reached=current_time >= request.eligible_at,
        )

    @staticmethod
    def create_purge_request(*, workspace_id, requester_user_id, confirmation_phrase, now=None):
        now = PurgeRequestService._now(now)
        session = PurgeRequestService._new_session()
        try:
            requester = PurgeRequestService._actor(session, requester_user_id)
            workspace = session.query(Workspace).filter(Workspace.id == workspace_id).with_for_update().one_or_none()
            terminal = PurgeRequestService._terminal(session, workspace_id)
            if workspace is None or terminal is None:
                raise PurgeRequestNotFoundError()
            target_deleted_at = workspace.deleted_at
            PurgeRequestService._phrase(
                confirmation_phrase,
                f"YÊU CẦU XÓA VĨNH VIỄN {workspace.slug}",
                legacy=f"REQUEST PURGE {workspace.slug}",
            )
            if workspace.deleted_at is None:
                raise PurgeRequestConflictError("Chỉ cơ sở đã xóa mềm mới có thể tạo yêu cầu.", "ACTIVE_WORKSPACE")
            if terminal["purged_at"] is not None or terminal["purge_request_id"] is not None:
                raise PurgeRequestConflictError("Cơ sở đã được xóa vĩnh viễn.", "ALREADY_PURGED")
            if workspace.deleted_by_id is None:
                raise PurgeRequestConflictError("Thông tin nguồn gốc xóa cơ sở chưa đầy đủ.", "PROVENANCE_INVALID")
            if PurgeRequestService._logo_present(session, workspace.id):
                raise PurgeRequestConflictError("Phải xóa liên kết logo cơ sở trước khi tạo yêu cầu xóa vĩnh viễn.", "WORKSPACE_LOGO_PRESENT")
            # The workspace row is the create serialization anchor. Keep the
            # existing-request lookup non-locking so it cannot invert the
            # request -> workspace order used by approval, execution, and restore.
            existing = session.query(WorkspacePurgeRequest).filter(
                WorkspacePurgeRequest.workspace_id == workspace.id,
                WorkspacePurgeRequest.target_deleted_at == workspace.deleted_at,
            ).one_or_none()
            if existing is not None:
                raise PurgeRequestConflictError(f"Yêu cầu đã tồn tại: {existing.id}.", "DUPLICATE_LIFECYCLE")
            lifecycle_id = str(uuid.uuid4())
            eligible_at = workspace.deleted_at + timedelta(days=RETENTION_DAYS)
            status = "PENDING_APPROVAL" if now >= eligible_at else "PENDING_RETENTION"
            hold_state = PurgeRequestService._holds_state(session, workspace.id)
            request = WorkspacePurgeRequest(
                lifecycle_id=lifecycle_id, workspace_id=workspace.id, purge_type="workspace", status=status,
                target_deleted_at=target_deleted_at, target_deleted_by_id=workspace.deleted_by_id,
                target_deleted_by_snapshot=workspace.deleted_by.username[:100] if workspace.deleted_by else "UNKNOWN",
                target_workspace_name=workspace.name, target_workspace_slug=workspace.slug,
                requested_by_id=requester.id, requested_by_snapshot=requester.username[:100], requested_at=now,
                eligible_at=eligible_at, retention_policy_version=RETENTION_POLICY_VERSION,
                manifest_version="purge-manifest-v1", manifest_canonical_text="", manifest_hash="" if False else "0" * 64,
                idempotency_key=str(uuid.uuid4()), hold_check_status=hold_state, hold_checked_at=now,
                hold_checked_by_id=requester.id, hold_checked_by_snapshot=requester.username[:100],
                hold_check_source="request_creation", created_at=now, updated_at=now,
            )
            session.add(request)
            session.flush()
            purge_plan = build_purge_plan(session, workspace, lock=True)
            manifest_text, manifest_digest = build_manifest(session, request, workspace, purge_plan)
            request.manifest_canonical_text = manifest_text
            request.manifest_hash = manifest_digest
            PurgeRequestService._event(session, request, workspace, requester.id, "request_created", None, status, now, "Purge request created.")
            if status == "PENDING_RETENTION":
                PurgeRequestService._event(session, request, workspace, requester.id, "retention_pending", status, status, now, "Retention window is pending.")
            session.commit()
            return PurgeRequestService.summarize(request)
        except IntegrityError:
            session.rollback()
            lookup = PurgeRequestService._new_session()
            try:
                existing = lookup.query(WorkspacePurgeRequest).filter(
                    WorkspacePurgeRequest.workspace_id == workspace_id,
                    WorkspacePurgeRequest.target_deleted_at == target_deleted_at,
                ).one_or_none()
            finally:
                lookup.close()
            if existing is not None:
                raise PurgeRequestConflictError(f"A request already exists: {existing.id}.", "DUPLICATE_LIFECYCLE")
            raise PurgeRequestConflictError("Không thể lưu yêu cầu xóa vĩnh viễn.", "PERSISTENCE_ERROR")
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _load_for_mutation(session, request_id, actor_id):
        actor = PurgeRequestService._actor(session, actor_id)
        request = session.query(WorkspacePurgeRequest).filter(WorkspacePurgeRequest.id == request_id).with_for_update().one_or_none()
        if request is None:
            raise PurgeRequestNotFoundError()
        workspace = session.query(Workspace).filter(Workspace.id == request.workspace_id).with_for_update().one_or_none()
        if workspace is None:
            raise PurgeRequestNotFoundError()
        terminal = PurgeRequestService._terminal(session, workspace.id)
        if terminal is None:
            raise PurgeRequestNotFoundError()
        return actor, request, workspace, terminal

    @staticmethod
    def approve_purge_request(*, request_id, approver_user_id, confirmation_phrase, now=None):
        now = PurgeRequestService._now(now)
        session = PurgeRequestService._new_session()
        try:
            actor, request, workspace, terminal = PurgeRequestService._load_for_mutation(session, request_id, approver_user_id)
            if request.invalidated_at is not None or request.outcome_unknown or request.status in TERMINAL_STATUSES:
                raise PurgeRequestConflictError("Yêu cầu chỉ còn chế độ xem.", "READ_ONLY")
            if now < request.eligible_at:
                raise PurgeRequestConflictError("Thời hạn lưu giữ chưa kết thúc.", "RETENTION_NOT_REACHED")
            if request.status == "PENDING_RETENTION":
                request.status = "PENDING_APPROVAL"
                request.updated_at = now
                PurgeRequestService._event(session, request, workspace, actor.id, "retention_reached", "PENDING_RETENTION", "PENDING_APPROVAL", now, "Retention window reached.")
                PurgeRequestService._event(session, request, workspace, actor.id, "pending_approval", "PENDING_RETENTION", "PENDING_APPROVAL", now, "Request promoted for approval.")
            elif request.status != APPROVABLE_STATUS:
                raise PurgeRequestConflictError("Yêu cầu chưa sẵn sàng để phê duyệt.", "INVALID_STATUS")
            if terminal["purged_at"] is not None or terminal["purge_request_id"] is not None:
                raise PurgeRequestConflictError("Cơ sở đã có dấu mốc xóa vĩnh viễn kết thúc.", "ALREADY_PURGED")
            if workspace.deleted_at != request.target_deleted_at or workspace.deleted_by_id != request.target_deleted_by_id:
                raise PurgeRequestConflictError("Nguồn gốc cơ sở đã thay đổi.", "PROVENANCE_MISMATCH")
            if PurgeRequestService._logo_present(session, workspace.id):
                raise PurgeRequestConflictError("Liên kết logo cơ sở phải được xóa trước khi phê duyệt.", "WORKSPACE_LOGO_PRESENT")
            PurgeRequestService._phrase(
                confirmation_phrase,
                f"PHÊ DUYỆT YÊU CẦU XÓA VĨNH VIỄN {request.target_workspace_slug} {request.lifecycle_id}",
                legacy=f"APPROVE PURGE {request.target_workspace_slug} {request.lifecycle_id}",
            )
            holds = session.query(PurgeLegalHold).filter(PurgeLegalHold.workspace_id == workspace.id).order_by(PurgeLegalHold.id).with_for_update().all()
            if PurgeRequestService._holds_state(session, workspace.id, holds=holds) != "CLEAR":
                raise PurgeRequestConflictError("Lệnh giữ dữ liệu pháp lý chưa được giải quyết.", "LEGAL_HOLD_UNRESOLVED")
            purge_plan = build_purge_plan(session, workspace, lock=True)
            try:
                validate_stored_manifest(session, request, workspace, purge_plan)
            except PurgeManifestError as exc:
                raise PurgeRequestConflictError("Manifest drift detected; request is stale.", "MANIFEST_MISMATCH") from exc
            before = request.status
            request.status = "APPROVED"
            request.approved_by_id = actor.id
            request.approved_by_snapshot = actor.username[:100]
            request.approved_at = now
            request.hold_check_status = "CLEAR"
            request.hold_checked_at = now
            request.hold_checked_by_id = actor.id
            request.hold_checked_by_snapshot = actor.username[:100]
            request.hold_check_source = "approval"
            request.updated_at = now
            PurgeRequestService._event(session, request, workspace, actor.id, "request_approved", before, "APPROVED", now, "Purge request approved; execution is not exposed in this task.")
            session.commit()
            return PurgeRequestService.summarize(request, now=now)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def reject_purge_request(*, request_id, rejector_user_id, reason, now=None):
        return PurgeRequestService._transition_preapproval(request_id, rejector_user_id, reason, now, "REJECTED", "request_rejected")

    @staticmethod
    def cancel_purge_request(*, request_id, requester_user_id, reason, now=None):
        now = PurgeRequestService._now(now)
        session = PurgeRequestService._new_session()
        try:
            actor, request, workspace, _ = PurgeRequestService._load_for_mutation(session, request_id, requester_user_id)
            if request.requested_by_id != actor.id:
                raise PurgeRequestAuthorizationError("Only the requester can cancel this request.")
            if request.status not in REQUESTED_STATUSES or request.invalidated_at is not None or request.outcome_unknown:
                raise PurgeRequestConflictError("Chỉ yêu cầu trước phê duyệt mới có thể hủy.", "INVALID_STATUS")
            before = request.status
            request.status = "CANCELLED"
            request.cancelled_by_id = actor.id
            request.cancelled_by_snapshot = actor.username[:100]
            request.cancelled_at = now
            request.cancellation_reason = (reason or "").strip()[:1000] or "Cancelled by requester."
            request.updated_at = now
            PurgeRequestService._event(session, request, workspace, actor.id, "request_cancelled", before, "CANCELLED", now, request.cancellation_reason)
            session.commit()
            return PurgeRequestService.summarize(request)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _transition_preapproval(request_id, actor_id, reason, now, target_status, event_type):
        now = PurgeRequestService._now(now)
        session = PurgeRequestService._new_session()
        try:
            actor, request, workspace, _ = PurgeRequestService._load_for_mutation(session, request_id, actor_id)
            if request.requested_by_id == actor.id:
                raise PurgeRequestAuthorizationError("Requester cannot reject the same request.")
            if request.status not in REQUESTED_STATUSES or request.invalidated_at is not None or request.outcome_unknown:
                raise PurgeRequestConflictError("Chỉ yêu cầu trước phê duyệt mới có thể từ chối.", "INVALID_STATUS")
            before = request.status
            request.status = target_status
            request.rejected_by_id = actor.id
            request.rejected_by_snapshot = actor.username[:100]
            request.rejected_at = now
            request.rejection_reason = (reason or "").strip()[:1000] or "Rejected by Approval Owner."
            request.updated_at = now
            PurgeRequestService._event(session, request, workspace, actor.id, event_type, before, target_status, now, request.rejection_reason)
            session.commit()
            return PurgeRequestService.summarize(request)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def invalidate_requests_for_workspace_restore(session, workspace_id, deleted_at, actor_id, now=None):
        now = PurgeRequestService._now(now)
        requests = session.query(WorkspacePurgeRequest).filter(
            WorkspacePurgeRequest.workspace_id == workspace_id,
            WorkspacePurgeRequest.target_deleted_at == deleted_at,
            WorkspacePurgeRequest.status.in_(INVALIDATABLE_STATUSES),
            WorkspacePurgeRequest.outcome_unknown.is_(False),
            WorkspacePurgeRequest.invalidated_at.is_(None),
            WorkspacePurgeRequest.invalidated_by_restore.is_(False),
        ).with_for_update().all()
        workspace = session.query(Workspace).filter(Workspace.id == workspace_id).one()
        for request in requests:
            request.invalidated_at = now
            request.invalidated_by_restore = True
            request.invalidation_reason = "Workspace restored; prior deletion lifecycle is invalidated."
            request.updated_at = now
            PurgeRequestService._event(session, request, workspace, actor_id, "manifest_invalidated", request.status, request.status, now, request.invalidation_reason)
        return len(requests)

    @staticmethod
    def list_summaries(*, page=1, per_page=20):
        session = PurgeRequestService._new_session()
        try:
            query = session.query(WorkspacePurgeRequest).order_by(WorkspacePurgeRequest.id.desc())
            total = query.count()
            items = query.offset((page - 1) * per_page).limit(per_page).all()
            return PurgeRequestPage([PurgeRequestService.summarize(item) for item in items], page, per_page, total)
        finally:
            session.close()

    @staticmethod
    def get_workspace_target(workspace_id):
        session = PurgeRequestService._new_session()
        try:
            workspace = session.query(Workspace).filter(Workspace.id == workspace_id).one_or_none()
            if workspace is None or workspace.deleted_at is None:
                raise PurgeRequestNotFoundError()
            existing = session.query(WorkspacePurgeRequest).filter(
                WorkspacePurgeRequest.workspace_id == workspace.id,
                WorkspacePurgeRequest.target_deleted_at == workspace.deleted_at,
            ).one_or_none()
            terminal = PurgeRequestService._terminal(session, workspace.id, lock=False)
            return {
                "id": workspace.id,
                "name": workspace.name,
                "slug": workspace.slug,
                "deleted_at": workspace.deleted_at,
                "deleted_by_id": workspace.deleted_by_id,
                "purged": bool(terminal and terminal["purged_at"] is not None),
                "existing_request_id": existing.id if existing else None,
            }
        finally:
            session.close()

    @staticmethod
    def get_summary(request_id):
        session = PurgeRequestService._new_session()
        try:
            request = session.query(WorkspacePurgeRequest).filter(WorkspacePurgeRequest.id == request_id).one_or_none()
            if request is None:
                raise PurgeRequestNotFoundError()
            return PurgeRequestService.summarize(request)
        finally:
            session.close()
