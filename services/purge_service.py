import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import sessionmaker

from core.auth.permissions import is_approval_owner
from extensions import db
from models.activity_log import ActivityLog
from models.appointment import Appointment
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from models.purge import (
    PurgeLegalHold,
    PurgeLifecycleEvent,
    WorkspacePurgeRequest,
    workspace_terminal_state_table,
)
from models.service import Service
from models.setting import Setting
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.purge_manifest import (
    PurgeManifestError,
    build_manifest,
    build_purge_plan,
    normalize_utc_timestamp,
    validate_stored_manifest,
)
from utils.timezone_utils import utc_now


REQUEST_APPROVED = "APPROVED"
REQUEST_EXECUTING = "EXECUTING"
REQUEST_COMPLETED = "COMPLETED"
REQUEST_FAILED = "FAILED"
HOLD_CLEAR = "CLEAR"
HOLD_RELEASED = "RELEASED"


class PurgeServiceError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class PurgeNotFoundError(PurgeServiceError):
    def __init__(self, message="Purge request or workspace was not found."):
        super().__init__(message, "NOT_FOUND")


class PurgeAuthorizationError(PurgeServiceError):
    def __init__(self, message="Executor is not authorized for purge."):
        super().__init__(message, "UNAUTHORIZED_EXECUTOR")


class PurgeConflictError(PurgeServiceError):
    def __init__(self, message, code="PURGE_CONFLICT"):
        super().__init__(message, code)


class PurgeExecutionError(PurgeServiceError):
    def __init__(self, message="Purge execution failed.", code="EXECUTION_FAILURE"):
        super().__init__(message, code)


class PurgeCommitOutcomeUnknownError(PurgeExecutionError):
    def __init__(self, message="Purge commit outcome is unknown; reconciliation is required.", code="OUTCOME_UNKNOWN"):
        super().__init__(message, code)


@dataclass
class PurgeResult:
    request_id: int
    lifecycle_id: str
    workspace_id: int
    status: str
    purged_at: datetime | None = None
    deleted_counts: dict = field(default_factory=dict)
    already_completed: bool = False


class PurgeService:
    """Internal-only, synchronous and fail-closed workspace purge service."""

    @staticmethod
    def _new_session():
        return sessionmaker(bind=db.engine, autoflush=False, expire_on_commit=False)()

    @staticmethod
    def execute_workspace_purge(*, request_id: int, workspace_id: int, executor_user_id: int, now=None):
        if now is not None and not isinstance(now, datetime):
            raise PurgeConflictError("Purge execution time must be a datetime.", "INVALID_NOW")
        execution_time = now or utc_now()
        session = PurgeService._new_session()
        execution_started = False
        try:
            request = (
                session.query(WorkspacePurgeRequest)
                .filter(WorkspacePurgeRequest.id == request_id, WorkspacePurgeRequest.workspace_id == workspace_id)
                .with_for_update()
                .one_or_none()
            )
            if request is None:
                raise PurgeNotFoundError()
            workspace = session.query(Workspace).filter(Workspace.id == workspace_id).with_for_update().one_or_none()
            terminal_state = session.execute(
                select(workspace_terminal_state_table)
                .where(workspace_terminal_state_table.c.id == workspace_id)
                .with_for_update()
            ).mappings().one_or_none()
            if workspace is None or terminal_state is None:
                raise PurgeNotFoundError()

            PurgeService._validate_request_contract(request, workspace_id, execution_time)
            executor = PurgeService._validate_executor(session, executor_user_id, request)
            if request.status == REQUEST_COMPLETED:
                if PurgeService._completed_state_is_consistent(request, workspace, terminal_state):
                    return PurgeResult(
                        request_id=request.id,
                        lifecycle_id=request.lifecycle_id,
                        workspace_id=workspace.id,
                        status=REQUEST_COMPLETED,
                        purged_at=terminal_state["purged_at"],
                        already_completed=True,
                    )
                raise PurgeConflictError("Completed purge request has inconsistent terminal state.", "INVALID_COMPLETED_STATE")

            if request.status != REQUEST_APPROVED:
                raise PurgeConflictError("Purge request is not approved.", "INVALID_STATUS")
            if request.approved_by_id is None or request.approved_at is None:
                raise PurgeConflictError("Purge approval is incomplete.", "INVALID_APPROVAL")
            if request.requested_by_id == request.approved_by_id:
                raise PurgeAuthorizationError("Requester cannot approve the same purge request.")
            if workspace.deleted_at is None:
                raise PurgeConflictError("Workspace is not soft-deleted.", "ACTIVE_WORKSPACE")
            if terminal_state["purged_at"] is not None or terminal_state["purge_request_id"] is not None:
                raise PurgeConflictError("Workspace is already purged or has a conflicting purge request.", "ALREADY_PURGED")

            PurgeService._validate_provenance(request, workspace)
            PurgeService._validate_retention(request, execution_time)
            holds = (
                session.query(PurgeLegalHold)
                .filter(PurgeLegalHold.workspace_id == workspace.id)
                .order_by(PurgeLegalHold.id)
                .with_for_update()
                .all()
            )
            PurgeService._validate_holds(request, holds)
            purge_plan = build_purge_plan(session, workspace, lock=True)
            try:
                validate_stored_manifest(session, request, workspace, purge_plan)
            except PurgeManifestError as exc:
                raise PurgeConflictError(str(exc), "MANIFEST_MISMATCH") from exc

            if PurgeService._logo_state(session, workspace.id) != "RESOLVED":
                raise PurgeConflictError("Workspace logo reference is still present.", "WORKSPACE_LOGO_PRESENT")

            request.status = REQUEST_EXECUTING
            request.execution_triggered_by_id = executor_user_id
            request.execution_trigger_snapshot = executor.username[:100]
            request.execution_started_at = execution_time
            request.last_attempt_at = execution_time
            request.attempt_count = (request.attempt_count or 0) + 1
            PurgeService._add_event(session, request, workspace, executor_user_id, "execution_started", REQUEST_APPROVED, REQUEST_EXECUTING, execution_time)
            session.flush()
            execution_started = True

            deleted_counts = PurgeService._delete_exact_rows(session, workspace.id, purge_plan)
            PurgeService._assert_postconditions(session, workspace.id, request.id, purge_plan)
            session.execute(
                update(workspace_terminal_state_table)
                .where(workspace_terminal_state_table.c.id == workspace.id)
                .values(purged_at=execution_time, purge_request_id=request.id)
            )
            request.status = REQUEST_COMPLETED
            request.completed_at = execution_time
            request.outcome_unknown = False
            PurgeService._add_event(session, request, workspace, executor_user_id, "completed", REQUEST_EXECUTING, REQUEST_COMPLETED, execution_time)
            session.flush()
            try:
                session.commit()
            except Exception as commit_error:
                rollback_error = PurgeService._safe_rollback(session)
                return PurgeService._reconcile_commit_outcome(request_id, workspace_id, execution_time, commit_error, rollback_error)
            return PurgeResult(
                request_id=request.id,
                lifecycle_id=request.lifecycle_id,
                workspace_id=workspace.id,
                status=REQUEST_COMPLETED,
                purged_at=execution_time,
                deleted_counts=deleted_counts,
            )
        except PurgeCommitOutcomeUnknownError:
            PurgeService._safe_rollback(session)
            raise
        except PurgeServiceError as exc:
            PurgeService._safe_rollback(session)
            if execution_started:
                PurgeService._record_failure(request_id, workspace_id, executor_user_id, execution_time, exc)
            raise
        except Exception as exc:
            PurgeService._safe_rollback(session)
            if execution_started:
                PurgeService._record_failure(request_id, workspace_id, executor_user_id, execution_time, exc)
            raise PurgeExecutionError() from exc
        finally:
            session.close()

    @staticmethod
    def _validate_request_contract(request, workspace_id, now):
        if request.workspace_id != workspace_id:
            raise PurgeConflictError("Purge request and workspace do not match.", "WORKSPACE_MISMATCH")
        if request.purge_type != "workspace":
            raise PurgeConflictError("Unsupported purge type.", "INVALID_PURGE_TYPE")
        if request.invalidated_at is not None or request.invalidated_by_restore:
            raise PurgeConflictError("Purge request was invalidated by restore.", "INVALIDATED_REQUEST")
        if request.outcome_unknown:
            raise PurgeConflictError("Purge outcome requires reconciliation.", "OUTCOME_UNKNOWN")
        if not isinstance(request.idempotency_key, str) or not request.idempotency_key.strip():
            raise PurgeConflictError("Purge idempotency key is required.", "INVALID_IDEMPOTENCY_KEY")
        if not isinstance(request.lifecycle_id, str):
            raise PurgeConflictError("Purge lifecycle ID is invalid.", "INVALID_LIFECYCLE_ID")
        try:
            uuid.UUID(request.lifecycle_id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise PurgeConflictError("Purge lifecycle ID is invalid.", "INVALID_LIFECYCLE_ID") from exc
        if not isinstance(now, datetime):
            raise PurgeConflictError("Purge execution time must be a datetime.", "INVALID_NOW")

    @staticmethod
    def _validate_executor(session, executor_user_id, request):
        executor = session.query(User).filter(User.id == executor_user_id).one_or_none()
        if executor is None or not is_approval_owner(executor) or not executor.is_active:
            raise PurgeAuthorizationError()
        if executor.deleted_at is not None or executor.approval_status != User.APPROVAL_ACTIVE:
            raise PurgeAuthorizationError()
        if request.requested_by_id == executor.id:
            raise PurgeAuthorizationError("Requester cannot execute the same purge request.")
        return executor

    @staticmethod
    def _completed_state_is_consistent(request, workspace, terminal_state, execution_time=None):
        if request.status != REQUEST_COMPLETED or not isinstance(request.completed_at, datetime):
            return False
        if not isinstance(terminal_state["purged_at"], datetime) or terminal_state["purge_request_id"] != request.id:
            return False
        try:
            if normalize_utc_timestamp(request.completed_at) != normalize_utc_timestamp(terminal_state["purged_at"]):
                return False
            if workspace is None or normalize_utc_timestamp(workspace.deleted_at) != normalize_utc_timestamp(request.target_deleted_at):
                return False
        except PurgeManifestError:
            return False
        if workspace.deleted_by_id != request.target_deleted_by_id:
            return False
        if execution_time is not None:
            try:
                if normalize_utc_timestamp(request.completed_at) != normalize_utc_timestamp(execution_time):
                    return False
                if normalize_utc_timestamp(terminal_state["purged_at"]) != normalize_utc_timestamp(execution_time):
                    return False
            except PurgeManifestError:
                return False
        return True

    @staticmethod
    def _validate_provenance(request, workspace):
        if request.lifecycle_id is None or request.workspace_id != workspace.id:
            raise PurgeConflictError("Purge lifecycle/workspace mismatch.", "LIFECYCLE_MISMATCH")
        if normalize_utc_timestamp(workspace.deleted_at) != normalize_utc_timestamp(request.target_deleted_at):
            raise PurgeConflictError("Workspace deletion timestamp does not match request snapshot.", "PROVENANCE_MISMATCH")
        if workspace.deleted_by_id != request.target_deleted_by_id:
            raise PurgeConflictError("Workspace deletion actor does not match request snapshot.", "PROVENANCE_MISMATCH")

    @staticmethod
    def _validate_retention(request, now):
        if request.eligible_at is None or request.retention_policy_version is None:
            raise PurgeConflictError("Retention contract is incomplete.", "RETENTION_INVALID")
        eligible_at = request.eligible_at.replace(tzinfo=timezone.utc) if request.eligible_at.tzinfo is None else request.eligible_at.astimezone(timezone.utc)
        current_time = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
        if current_time < eligible_at:
            raise PurgeConflictError("Retention period has not elapsed.", "RETENTION_NOT_REACHED")

    @staticmethod
    def _validate_holds(request, holds):
        if request.hold_check_status != HOLD_CLEAR:
            raise PurgeConflictError("Legal-hold check is not clear.", "LEGAL_HOLD_UNRESOLVED")
        for hold in holds:
            if hold.status != HOLD_RELEASED:
                raise PurgeConflictError("Active or unknown legal hold blocks purge.", "ACTIVE_LEGAL_HOLD")
            if hold.released_at is None or hold.released_by_snapshot is None or hold.release_reason is None:
                raise PurgeConflictError("Malformed released legal hold blocks purge.", "LEGAL_HOLD_UNRESOLVED")

    @staticmethod
    def _logo_state(session, workspace_id):
        rows = session.query(Setting).filter(Setting.workspace_id == workspace_id, Setting.key == "spa_logo").all()
        return "BLOCKED_PRESENT" if any(row.value is not None and (not isinstance(row.value, str) or row.value != "") for row in rows) else "RESOLVED"

    @staticmethod
    def _delete_exact(model, ids, workspace_id, name, session):
        if not ids:
            return 0
        count = session.query(model).filter(model.id.in_(ids), model.workspace_id == workspace_id).delete(synchronize_session=False)
        if count != len(ids):
            raise PurgeExecutionError(f"Exact purge count mismatch for {name}.")
        return count

    @staticmethod
    def _delete_exact_rows(session, workspace_id, purge_plan):
        invoice_detail_count = 0
        if purge_plan.invoice_detail_ids:
            invoice_detail_count = session.query(InvoiceDetail).filter(
                InvoiceDetail.id.in_(purge_plan.invoice_detail_ids),
                InvoiceDetail.invoice_id.in_(purge_plan.invoice_ids),
            ).delete(synchronize_session=False)
            if invoice_detail_count != len(purge_plan.invoice_detail_ids):
                raise PurgeExecutionError("Exact purge count mismatch for invoice_details.")
        return {
            "invoice_details": invoice_detail_count,
            "appointments": PurgeService._delete_exact(Appointment, purge_plan.appointment_ids, workspace_id, "appointments", session),
            "invoices": PurgeService._delete_exact(Invoice, purge_plan.invoice_ids, workspace_id, "invoices", session),
            "customers": PurgeService._delete_exact(Customer, purge_plan.customer_ids, workspace_id, "customers", session),
            "services": PurgeService._delete_exact(Service, purge_plan.service_ids, workspace_id, "services", session),
            "settings": PurgeService._delete_exact(Setting, purge_plan.setting_ids, workspace_id, "settings", session),
            "workspace_members": PurgeService._delete_exact(WorkspaceMember, purge_plan.workspace_member_ids, workspace_id, "workspace_members", session),
        }

    @staticmethod
    def _assert_postconditions(session, workspace_id, request_id, purge_plan):
        checks = (
            (InvoiceDetail, purge_plan.invoice_detail_ids, "invoice_details"),
            (Appointment, purge_plan.appointment_ids, "appointments"),
            (Invoice, purge_plan.invoice_ids, "invoices"),
            (Customer, purge_plan.customer_ids, "customers"),
            (Service, purge_plan.service_ids, "services"),
            (Setting, purge_plan.setting_ids, "settings"),
            (WorkspaceMember, purge_plan.workspace_member_ids, "workspace_members"),
        )
        for model, ids, name in checks:
            if ids and session.query(model).filter(model.id.in_(ids)).count():
                raise PurgeExecutionError(f"Purge postcondition retained approved {name} row.")
            if hasattr(model, "workspace_id") and session.query(model).filter(model.workspace_id == workspace_id).count():
                raise PurgeExecutionError(f"Purge postcondition retained target {name} row.")
        if session.query(Workspace).filter(Workspace.id == workspace_id).count() != 1:
            raise PurgeExecutionError("Workspace terminal row disappeared.")
        if session.execute(select(workspace_terminal_state_table.c.id).where(workspace_terminal_state_table.c.id == workspace_id)).scalar_one_or_none() is None:
            raise PurgeExecutionError("Workspace terminal state disappeared.")
        if session.query(WorkspacePurgeRequest).filter(WorkspacePurgeRequest.id == request_id).count() != 1:
            raise PurgeExecutionError("Purge request audit row disappeared.")
        if session.query(User).count() < purge_plan.user_count or session.query(ActivityLog).count() < purge_plan.activity_log_count:
            raise PurgeExecutionError("Preserved global audit rows changed unexpectedly.")

    @staticmethod
    def _add_event(session, request, workspace, actor_id, event_type, before, after, event_at):
        sequence = session.query(func.max(PurgeLifecycleEvent.event_sequence)).filter(PurgeLifecycleEvent.request_id == request.id).scalar() or 0
        actor = session.query(User).filter(User.id == actor_id).one_or_none()
        actor_snapshot = (actor.username if actor else "unknown")[:100]
        session.add(PurgeLifecycleEvent(
            request_id=request.id,
            lifecycle_id_snapshot=request.lifecycle_id,
            workspace_id=workspace.id,
            workspace_name_snapshot=workspace.name,
            event_sequence=sequence + 1,
            event_type=event_type,
            actor_id=actor_id,
            actor_snapshot=actor_snapshot,
            event_at=event_at,
            status_before=before,
            status_after=after,
            sanitized_summary=f"Purge lifecycle event: {event_type}",
            created_at=event_at,
        ))

    @staticmethod
    def _record_failure(request_id, workspace_id, executor_user_id, failure_time, exc):
        session = PurgeService._new_session()
        try:
            request = session.query(WorkspacePurgeRequest).filter_by(id=request_id, workspace_id=workspace_id).with_for_update().one_or_none()
            workspace = session.query(Workspace).filter_by(id=workspace_id).with_for_update().one_or_none()
            terminal_state = session.execute(
                select(workspace_terminal_state_table)
                .where(workspace_terminal_state_table.c.id == workspace_id)
                .with_for_update()
            ).mappings().one_or_none()
            if request is None or workspace is None or terminal_state is None:
                PurgeService._safe_rollback(session)
                return False
            if (
                request.status != REQUEST_APPROVED
                or request.invalidated_at is not None
                or request.invalidated_by_restore
                or request.outcome_unknown
                or terminal_state["purged_at"] is not None
                or terminal_state["purge_request_id"] is not None
            ):
                PurgeService._safe_rollback(session)
                return False
            request.status = REQUEST_FAILED
            request.failed_at = failure_time
            request.failure_code = "EXECUTION_FAILURE"
            request.failure_summary = "Purge transaction rolled back."
            request.outcome_unknown = False
            request.attempt_count = (request.attempt_count or 0) + 1
            request.last_attempt_at = failure_time
            request.execution_triggered_by_id = executor_user_id
            executor = session.query(User).filter(User.id == executor_user_id).one_or_none()
            request.execution_trigger_snapshot = (executor.username if executor else "unknown")[:100]
            PurgeService._add_event(session, request, workspace, executor_user_id, "failed", REQUEST_EXECUTING, REQUEST_FAILED, failure_time)
            session.commit()
            return True
        except Exception as audit_error:
            PurgeService._safe_rollback(session)
            raise PurgeExecutionError("Purge failure audit transaction failed.", "FAILURE_AUDIT_FAILURE") from audit_error
        finally:
            session.close()

    @staticmethod
    def _reconcile_commit_outcome(request_id, workspace_id, execution_time, commit_error, rollback_error=None):
        session = PurgeService._new_session()
        try:
            request = session.query(WorkspacePurgeRequest).filter_by(id=request_id, workspace_id=workspace_id).with_for_update().one_or_none()
            workspace = session.query(Workspace).filter_by(id=workspace_id).with_for_update().one_or_none()
            state = session.execute(
                select(workspace_terminal_state_table)
                .where(workspace_terminal_state_table.c.id == workspace_id)
                .with_for_update()
            ).mappings().one_or_none()
            if request is not None and state is not None and PurgeService._completed_state_is_consistent(request, workspace, state, execution_time):
                return PurgeResult(request_id=request.id, lifecycle_id=request.lifecycle_id, workspace_id=workspace_id, status=REQUEST_COMPLETED, purged_at=state["purged_at"])
            if request is not None:
                request.outcome_unknown = True
                session.commit()
            code = "RECONCILIATION_FAILURE" if rollback_error is not None else "OUTCOME_UNKNOWN"
            raise PurgeCommitOutcomeUnknownError("Purge commit outcome is unknown; manual reconciliation is required.", code) from commit_error
        except PurgeCommitOutcomeUnknownError:
            raise
        except Exception as reconcile_error:
            PurgeService._safe_rollback(session)
            raise PurgeCommitOutcomeUnknownError("Purge commit outcome is unknown; reconciliation failed.", "RECONCILIATION_FAILURE") from reconcile_error
        finally:
            session.close()

    @staticmethod
    def _safe_rollback(session):
        try:
            session.rollback()
            return None
        except Exception as rollback_error:
            return rollback_error
