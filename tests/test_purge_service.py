import os
import hashlib
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import inspect, select, update
from sqlalchemy.orm import Session


TEST_DB_FILE = Path(tempfile.gettempdir()) / f"spamanager_purge_service_{uuid.uuid4().hex}.sqlite"
os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["SPAMANAGER_TEST_PROCESS"] = "1"

from app import app
from extensions import db
from models.activity_log import ActivityLog
from models.appointment import Appointment
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from models.service import Service
from models.setting import Setting
from models.user import User
from models.purge import workspace_terminal_state_table
from models.workspace import Workspace, WorkspaceMember
from services.purge_manifest import build_manifest, build_purge_plan, manifest_hash
from services.purge_service import (
    PurgeAuthorizationError,
    PurgeConflictError,
    PurgeCommitOutcomeUnknownError,
    PurgeExecutionError,
    PurgeService,
)


class PurgeServiceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global PurgeLifecycleEvent, PurgeLegalHold, WorkspacePurgeRequest
        from models.purge import PurgeLegalHold, PurgeLifecycleEvent, WorkspacePurgeRequest
        cls.app_context = app.app_context()
        cls.app_context.push()
        if not inspect(db.engine).has_table("workspace_purge_requests"):
            db.create_all()
            import importlib
            importlib.import_module("migrations.versions.0007_permanent_purge_workflow").upgrade()

    @classmethod
    def tearDownClass(cls):
        try:
            db.session.remove()
            db.engine.dispose()
        finally:
            cls.app_context.pop()
            if TEST_DB_FILE.exists():
                TEST_DB_FILE.unlink()

    def setUp(self):
        db.session.remove()
        for model in (PurgeLifecycleEvent, PurgeLegalHold, WorkspacePurgeRequest, ActivityLog, InvoiceDetail, Appointment, Invoice, Customer, Service, Setting, WorkspaceMember, Workspace, User):
            db.session.query(model).delete(synchronize_session=False)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()

    def _fixture(self, *, logo=None):
        requester = User(username=f"requester_{uuid.uuid4().hex[:8]}", full_name="Requester", role="APPROVAL_OWNER", approval_status="active", is_active=True)
        executor = User(username=f"executor_{uuid.uuid4().hex[:8]}", full_name="Executor", role="APPROVAL_OWNER", approval_status="active", is_active=True)
        requester.set_password("TestPassword123!")
        executor.set_password("TestPassword123!")
        db.session.add_all([requester, executor])
        db.session.flush()
        workspace = Workspace(name="Purge Target", slug=f"purge-{uuid.uuid4().hex}", status="active", deleted_at=datetime(2026, 1, 1), deleted_by_id=requester.id)
        db.session.add(workspace)
        db.session.flush()
        db.session.add(WorkspaceMember(workspace_id=workspace.id, user_id=requester.id, role="owner", status="active"))
        db.session.add(Customer(name="Target Customer", workspace_id=workspace.id))
        service = Service(name="Target Service", price=100, workspace_id=workspace.id)
        db.session.add(service)
        db.session.flush()
        customer = db.session.query(Customer).filter_by(workspace_id=workspace.id).one()
        invoice = Invoice(customer_id=customer.id, total_amount=100, workspace_id=workspace.id)
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceDetail(invoice_id=invoice.id, service_id=service.id, price=100, quantity=1))
        db.session.add(Appointment(customer_id=customer.id, service_id=service.id, appointment_time=datetime(2026, 1, 2), workspace_id=workspace.id))
        if logo is not None:
            db.session.add(Setting(key="spa_logo", value=logo, workspace_id=workspace.id))
        db.session.add(ActivityLog(module="Test", action="CREATE", description="preserve", workspace_id=workspace.id))
        request = WorkspacePurgeRequest(
            lifecycle_id=f"00000000-0000-0000-0000-{uuid.uuid4().hex[:12]}",
            workspace_id=workspace.id,
            status="APPROVED",
            target_deleted_at=workspace.deleted_at,
            target_deleted_by_id=requester.id,
            target_deleted_by_snapshot=requester.username,
            target_workspace_name=workspace.name,
            target_workspace_slug=workspace.slug,
            requested_by_id=requester.id,
            requested_by_snapshot=requester.username,
            eligible_at=datetime(2025, 12, 1),
            retention_policy_version="retention-v1",
            approved_by_id=executor.id,
            approved_by_snapshot=executor.username,
            approved_at=datetime(2026, 1, 2),
            hold_check_status="CLEAR",
            manifest_version="purge-manifest-v1",
            manifest_canonical_text="{}",
            manifest_hash="0" * 64,
            idempotency_key=f"purge-{uuid.uuid4().hex}",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        db.session.add(request)
        db.session.flush()
        canonical_text, digest = build_manifest(db.session, request, workspace, build_purge_plan(db.session, workspace))
        request.manifest_canonical_text = canonical_text
        request.manifest_hash = digest
        db.session.commit()
        return requester, executor, workspace, request

    def test_happy_path_deletes_only_target_business_rows_and_preserves_audit(self):
        requester, executor, workspace, request = self._fixture()
        result = PurgeService.execute_workspace_purge(
            request_id=request.id,
            workspace_id=workspace.id,
            executor_user_id=executor.id,
            now=datetime(2026, 2, 1),
        )
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(result.deleted_counts["invoice_details"], 1)
        terminal_state = db.session.execute(select(workspace_terminal_state_table).where(workspace_terminal_state_table.c.id == workspace.id)).mappings().one()
        self.assertIsNotNone(terminal_state["purged_at"])
        self.assertIsNotNone(terminal_state["purge_request_id"])
        self.assertIsNotNone(db.session.get(WorkspacePurgeRequest, request.id))
        self.assertEqual(db.session.query(User).count(), 2)
        self.assertEqual(db.session.query(ActivityLog).count(), 1)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).count(), 2)
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 0)
        self.assertEqual(db.session.query(WorkspaceMember).filter_by(workspace_id=workspace.id).count(), 0)

    def test_logo_reference_blocks_before_mutation(self):
        requester, executor, workspace, request = self._fixture(logo="logos/present.png")
        with self.assertRaises(PurgeConflictError) as context:
            PurgeService.execute_workspace_purge(
                request_id=request.id,
                workspace_id=workspace.id,
                executor_user_id=executor.id,
                now=datetime(2026, 2, 1),
            )
        self.assertEqual(context.exception.code, "WORKSPACE_LOGO_PRESENT")
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 1)

    def test_requester_cannot_execute_and_staff_cannot_execute(self):
        requester, executor, workspace, request = self._fixture()
        with self.assertRaises(PurgeAuthorizationError):
            PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=requester.id, now=datetime(2026, 2, 1))
        staff = User(username=f"staff_{uuid.uuid4().hex[:8]}", full_name="Staff", role="STAFF", approval_status="active", is_active=True)
        staff.set_password("TestPassword123!")
        db.session.add(staff)
        db.session.commit()
        with self.assertRaises(PurgeAuthorizationError):
            PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=staff.id, now=datetime(2026, 2, 1))

    def test_runtime_failure_rolls_back_and_records_failed_event(self):
        requester, executor, workspace, request = self._fixture()
        execution_time = datetime(2026, 2, 1)
        executor_username = executor.username
        with patch.object(PurgeService, "_delete_exact_rows", side_effect=RuntimeError("injected")):
            with self.assertRaises(PurgeExecutionError):
                PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=execution_time)
        db.session.expire_all()
        stored_request = db.session.get(WorkspacePurgeRequest, request.id)
        self.assertEqual(stored_request.status, "FAILED")
        self.assertEqual(stored_request.failed_at, execution_time)
        self.assertEqual(stored_request.attempt_count, 1)
        self.assertEqual(stored_request.last_attempt_at, execution_time)
        self.assertEqual(stored_request.execution_triggered_by_id, executor.id)
        self.assertEqual(stored_request.execution_trigger_snapshot, executor_username)
        terminal_state = db.session.execute(select(workspace_terminal_state_table).where(workspace_terminal_state_table.c.id == workspace.id)).mappings().one()
        self.assertIsNone(terminal_state["purged_at"])
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 1)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).count(), 1)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="failed").count(), 1)
        self.assertFalse(stored_request.outcome_unknown)

    def test_completed_request_is_idempotent_no_op(self):
        requester, executor, workspace, request = self._fixture()
        first = PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        second = PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 2))
        self.assertFalse(first.already_completed)
        self.assertTrue(second.already_completed)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).count(), 2)

    def test_completed_retry_requires_authorized_executor(self):
        requester, executor, workspace, request = self._fixture()
        PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        with self.assertRaises(PurgeAuthorizationError):
            PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=requester.id, now=datetime(2026, 2, 2))
        self.assertEqual(db.session.query(PurgeLifecycleEvent).count(), 2)

    def test_request_gates_fail_closed(self):
        for field, value, code in (
            ("invalidated_at", datetime(2026, 1, 2), "INVALIDATED_REQUEST"),
            ("invalidated_by_restore", True, "INVALIDATED_REQUEST"),
            ("outcome_unknown", True, "OUTCOME_UNKNOWN"),
            ("idempotency_key", "   ", "INVALID_IDEMPOTENCY_KEY"),
        ):
            with self.subTest(field=field):
                requester, executor, workspace, request = self._fixture()
                setattr(request, field, value)
                db.session.commit()
                with self.assertRaises(PurgeConflictError) as context:
                    PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
                self.assertEqual(context.exception.code, code)

    def test_service_does_not_commit_or_rollback_caller_session(self):
        requester, executor, workspace, request = self._fixture()
        request_id = request.id
        workspace_id = workspace.id
        requester_id = requester.id
        unrelated = User(username=f"pending_{uuid.uuid4().hex[:8]}", full_name="Pending", role="STAFF", approval_status="active", is_active=True)
        unrelated.set_password("PendingPassword123!")
        db.session.add(unrelated)
        with self.assertRaises(PurgeAuthorizationError):
            PurgeService.execute_workspace_purge(request_id=request_id, workspace_id=workspace_id, executor_user_id=requester_id, now=datetime(2026, 2, 1))
        self.assertIn(unrelated, db.session.new)
        db.session.rollback()

    def test_successful_purge_does_not_commit_caller_pending_object(self):
        requester, executor, workspace, request = self._fixture()
        request_id = request.id
        workspace_id = workspace.id
        executor_id = executor.id
        pending_user = User(username=f"pending_success_{uuid.uuid4().hex[:8]}", full_name="Pending", role="STAFF", approval_status="active", is_active=True)
        pending_user.set_password("PendingPassword123!")
        db.session.add(pending_user)
        result = PurgeService.execute_workspace_purge(request_id=request_id, workspace_id=workspace_id, executor_user_id=executor_id, now=datetime(2026, 2, 1))
        self.assertEqual(result.status, "COMPLETED")
        self.assertIn(pending_user, db.session.new)
        db.session.rollback()

    def test_released_hold_permits_progress_and_malformed_release_blocks(self):
        requester, executor, workspace, request = self._fixture()
        db.session.add(PurgeLegalHold(
            hold_id=str(uuid.uuid4()), workspace_id=workspace.id, hold_type="LEGAL", source="test", reason="released",
            placed_by_snapshot=requester.username, status="RELEASED", released_at=datetime(2026, 1, 3),
            released_by_snapshot=executor.username, release_reason="released",
        ))
        db.session.commit()
        result = PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        self.assertEqual(result.status, "COMPLETED")

        for missing in ("released_at", "released_by_snapshot", "release_reason"):
            with self.subTest(missing=missing):
                requester, executor, workspace, request = self._fixture()
                values = {"released_at": datetime(2026, 1, 3), "released_by_snapshot": executor.username, "release_reason": "released"}
                values[missing] = None
                with self.assertRaises(PurgeConflictError) as context:
                    PurgeService._validate_holds(request, [SimpleNamespace(status="RELEASED", **values)])
                self.assertEqual(context.exception.code, "LEGAL_HOLD_UNRESOLVED")

    def test_invalid_now_and_non_approved_status_are_rejected(self):
        requester, executor, workspace, request = self._fixture()
        with self.assertRaises(PurgeConflictError) as context:
            PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now="not-a-datetime")
        self.assertEqual(context.exception.code, "INVALID_NOW")
        request.status = "REQUESTED"
        db.session.commit()
        with self.assertRaises(PurgeConflictError) as context:
            PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        self.assertEqual(context.exception.code, "INVALID_STATUS")

    def test_active_legal_hold_blocks_without_deleting_rows(self):
        requester, executor, workspace, request = self._fixture()
        db.session.add(PurgeLegalHold(
            hold_id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            hold_type="LEGAL",
            source="test",
            reason="active",
            placed_by_snapshot=requester.username,
            status="ACTIVE",
        ))
        db.session.commit()
        with self.assertRaises(PurgeConflictError) as context:
            PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        self.assertEqual(context.exception.code, "ACTIVE_LEGAL_HOLD")
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 1)

    def test_tenant_rows_are_not_deleted(self):
        requester, executor, workspace, request = self._fixture()
        other_workspace = Workspace(name="Other", slug=f"other-{uuid.uuid4().hex}", status="active")
        db.session.add(other_workspace)
        db.session.flush()
        other_customer = Customer(name="Other Customer", workspace_id=other_workspace.id)
        db.session.add(other_customer)
        db.session.commit()
        PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(Customer, other_customer.id))

    def test_commit_uncertainty_marks_unknown_without_failed_overwrite(self):
        requester, executor, workspace, request = self._fixture()
        request.status = "EXECUTING"
        db.session.commit()
        with self.assertRaises(PurgeExecutionError) as context:
            PurgeService._reconcile_commit_outcome(request.id, workspace.id, datetime(2026, 2, 1), RuntimeError("commit uncertain"))
        self.assertEqual(context.exception.code, "OUTCOME_UNKNOWN")

    def test_completed_timestamp_mismatch_blocks_idempotent_retry(self):
        requester, executor, workspace, request = self._fixture()
        first = datetime(2026, 2, 1)
        second = datetime(2026, 2, 2)
        request.status = "COMPLETED"
        request.completed_at = first
        db.session.execute(update(workspace_terminal_state_table).where(workspace_terminal_state_table.c.id == workspace.id).values(purged_at=second, purge_request_id=request.id))
        db.session.commit()
        with self.assertRaises(PurgeConflictError) as context:
            PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=second)
        self.assertEqual(context.exception.code, "INVALID_COMPLETED_STATE")
        self.assertEqual(db.session.query(PurgeLifecycleEvent).count(), 0)

    def test_inconsistent_completed_reconciliation_marks_unknown_without_failed(self):
        requester, executor, workspace, request = self._fixture()
        execution_time = datetime(2026, 2, 1)
        request.status = "COMPLETED"
        request.completed_at = datetime(2026, 2, 2)
        db.session.execute(update(workspace_terminal_state_table).where(workspace_terminal_state_table.c.id == workspace.id).values(purged_at=datetime(2026, 2, 3), purge_request_id=request.id))
        db.session.commit()
        with self.assertRaises(PurgeCommitOutcomeUnknownError) as context:
            PurgeService._reconcile_commit_outcome(request.id, workspace.id, execution_time, RuntimeError("ack lost"))
        self.assertEqual(context.exception.code, "OUTCOME_UNKNOWN")
        db.session.expire_all()
        stored_request = db.session.get(WorkspacePurgeRequest, request.id)
        self.assertEqual(stored_request.status, "COMPLETED")
        self.assertTrue(stored_request.outcome_unknown)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="failed").count(), 0)
        db.session.expire_all()
        self.assertTrue(db.session.get(WorkspacePurgeRequest, request.id).outcome_unknown)

    def test_commit_ack_loss_after_real_commit_reconciles_completed(self):
        requester, executor, workspace, request = self._fixture()
        real_commit = Session.commit
        state = {"raised": False}

        def commit_then_raise(session, *args, **kwargs):
            real_commit(session, *args, **kwargs)
            if not state["raised"]:
                state["raised"] = True
                raise RuntimeError("acknowledgement lost")

        with patch.object(Session, "commit", new=commit_then_raise):
            result = PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        self.assertTrue(result.status == "COMPLETED")
        db.session.expire_all()
        self.assertEqual(db.session.get(WorkspacePurgeRequest, request.id).status, "COMPLETED")
        self.assertFalse(db.session.get(WorkspacePurgeRequest, request.id).outcome_unknown)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="failed").count(), 0)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="completed").count(), 1)

    def test_commit_unknown_blocks_retry_without_failed_event(self):
        requester, executor, workspace, request = self._fixture()
        real_commit = Session.commit
        state = {"raised": False}

        def fail_first_commit(session, *args, **kwargs):
            if not state["raised"]:
                state["raised"] = True
                raise RuntimeError("commit result unknown")
            return real_commit(session, *args, **kwargs)

        with patch.object(Session, "commit", new=fail_first_commit):
            with self.assertRaises(PurgeCommitOutcomeUnknownError):
                PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        db.session.expire_all()
        stored = db.session.get(WorkspacePurgeRequest, request.id)
        self.assertTrue(stored.outcome_unknown)
        self.assertNotEqual(stored.status, "FAILED")
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="failed").count(), 0)
        with self.assertRaises(PurgeConflictError) as context:
            PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 2))
        self.assertEqual(context.exception.code, "OUTCOME_UNKNOWN")

    def test_reconciliation_failure_bypasses_failure_audit(self):
        requester, executor, workspace, request = self._fixture()
        def fail_commit(session, *args, **kwargs):
            raise RuntimeError("commit acknowledgement failure")

        with patch.object(Session, "commit", new=fail_commit), patch.object(PurgeService, "_reconcile_commit_outcome", side_effect=PurgeCommitOutcomeUnknownError()), patch.object(PurgeService, "_record_failure") as record_failure:
            with self.assertRaises(PurgeCommitOutcomeUnknownError):
                PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        record_failure.assert_not_called()

    def test_failure_audit_does_not_overwrite_terminal_states(self):
        for status, fields in (
            ("COMPLETED", {}),
            ("CANCELLED", {"cancelled_at": datetime(2026, 1, 3)}),
            ("REJECTED", {"rejected_at": datetime(2026, 1, 3)}),
            ("EXPIRED", {}),
            ("BLOCKED", {}),
            ("APPROVED", {"invalidated_at": datetime(2026, 1, 3)}),
            ("APPROVED", {"invalidated_by_restore": True}),
            ("APPROVED", {"outcome_unknown": True}),
        ):
            with self.subTest(status=status, fields=fields):
                requester, executor, workspace, request = self._fixture()
                request.status = status
                if status == "COMPLETED":
                    request.completed_at = datetime(2026, 1, 3)
                for key, value in fields.items():
                    setattr(request, key, value)
                try:
                    db.session.commit()
                    changed = PurgeService._record_failure(request.id, workspace.id, executor.id, datetime(2026, 2, 1), RuntimeError("test"))
                    self.assertFalse(changed)
                    db.session.expire_all()
                    self.assertEqual(db.session.get(WorkspacePurgeRequest, request.id).status, status)
                    self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="failed").count(), 0)
                finally:
                    db.session.rollback()

    def test_manifest_validation_rejects_malformed_and_drifted_inputs(self):
        mutations = (
            ("malformed_json", lambda request, workspace: setattr(request, "manifest_canonical_text", "[]"), "MANIFEST_MISMATCH"),
            ("hash_mismatch", lambda request, workspace: setattr(request, "manifest_hash", "0" * 64), "MANIFEST_MISMATCH"),
            ("unsupported_version", lambda request, workspace: setattr(request, "manifest_version", "purge-manifest-v0"), "MANIFEST_MISMATCH"),
            ("lifecycle_drift", lambda request, workspace: setattr(request, "lifecycle_id", str(uuid.uuid4())), "MANIFEST_MISMATCH"),
            ("provenance_drift", lambda request, workspace: setattr(workspace, "deleted_by_id", request.approved_by_id), "PROVENANCE_MISMATCH"),
        )
        for name, mutate, expected_code in mutations:
            with self.subTest(name=name):
                requester, executor, workspace, request = self._fixture()
                mutate(request, workspace)
                if name == "malformed_json":
                    request.manifest_hash = hashlib.sha256(b"[]").hexdigest()
                db.session.commit()
                with self.assertRaises(PurgeConflictError) as context:
                    PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
                self.assertEqual(context.exception.code, expected_code)

    def test_manifest_validation_rejects_row_and_logo_drift(self):
        requester, executor, workspace, request = self._fixture()
        db.session.add(Customer(name="Drift", phone="0909999999", workspace_id=workspace.id))
        db.session.commit()
        with self.assertRaises(PurgeConflictError) as context:
            PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        self.assertEqual(context.exception.code, "MANIFEST_MISMATCH")

        requester, executor, workspace, request = self._fixture()
        db.session.add(Setting(workspace_id=workspace.id, key="spa_logo", value="logo.png"))
        db.session.commit()
        with self.assertRaises(PurgeConflictError) as context:
            PurgeService.execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        self.assertEqual(context.exception.code, "MANIFEST_MISMATCH")
