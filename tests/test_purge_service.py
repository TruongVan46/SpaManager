import os
import hashlib
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import inspect, select, update
from sqlalchemy.orm import Session
from core.exceptions import ValidationException


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
from models.purge import workspace_terminal_state_table, workspace_purge_execution_authorizations_table
from models.workspace import Workspace, WorkspaceMember
from services.purge_manifest import build_manifest, build_purge_plan, manifest_hash
from services.purge_service import (
    PurgeConflictError,
    PurgeCommitOutcomeUnknownError,
    PurgeExecutionDisabledError,
    PurgeExecutionError,
    PurgeService,
)
from services.purge_reauth_service import (
    PurgeReauthError,
    PurgeReauthInvalidCredentialError,
    PurgeReauthRateLimitedError,
    PurgeReauthRequiredError,
    PurgeReauthRequestIneligibleError,
    PurgeReauthService,
)
from services.auth_service import AuthService
from services.user_service import UserService
from services.purge_legal_hold_service import (
    PurgeLegalHoldAuthorizationError,
    PurgeLegalHoldConflictError,
    PurgeLegalHoldNotFoundError,
    PurgeLegalHoldService,
)


class PurgeServiceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global PurgeLifecycleEvent, PurgeLegalHold, WorkspacePurgeRequest, WorkspacePurgeExecutionAuthorization, WorkspacePurgeReauthActorThrottle
        from models.purge import (
            PurgeLegalHold,
            PurgeLifecycleEvent,
            WorkspacePurgeExecutionAuthorization,
            WorkspacePurgeReauthActorThrottle,
            WorkspacePurgeRequest,
        )
        cls.app_context = app.app_context()
        cls.app_context.push()
        if not inspect(db.engine).has_table("workspace_purge_requests"):
            db.create_all()
            import importlib
            importlib.import_module("migrations.versions.0007_permanent_purge_workflow").upgrade()
        if not inspect(db.engine).has_table("workspace_purge_execution_authorizations"):
            import importlib
            importlib.import_module("migrations.versions.0008_durable_purge_reauth_state").upgrade()

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
        self.previous_execution_flag = app.config.get("PERMANENT_PURGE_EXECUTION_ENABLED")
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = False
        db.session.remove()
        for model in (WorkspacePurgeExecutionAuthorization, WorkspacePurgeReauthActorThrottle, PurgeLifecycleEvent, PurgeLegalHold, WorkspacePurgeRequest, ActivityLog, InvoiceDetail, Appointment, Invoice, Customer, Service, Setting, WorkspaceMember, Workspace, User):
            db.session.query(model).delete(synchronize_session=False)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = self.previous_execution_flag

    def _fixture(self, *, logo=None, execution_enabled=True):
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = execution_enabled
        requester = User(username=f"requester_{uuid.uuid4().hex[:8]}", full_name="Requester", role="APPROVAL_OWNER", approval_status="active", is_active=True)
        approver = User(username=f"approver_{uuid.uuid4().hex[:8]}", full_name="Approver", role="APPROVAL_OWNER", approval_status="active", is_active=True)
        executor = User(username=f"executor_{uuid.uuid4().hex[:8]}", full_name="Executor", role="APPROVAL_OWNER", approval_status="active", is_active=True)
        requester.set_password("TestPassword123!")
        approver.set_password("TestPassword123!")
        executor.set_password("TestPassword123!")
        db.session.add_all([requester, approver, executor])
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
            approved_by_id=approver.id,
            approved_by_snapshot=approver.username,
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

    def _execute_workspace_purge(self, **kwargs):
        kwargs = dict(kwargs)
        generation = kwargs.pop("authorization_generation", None)
        nonce = kwargs.pop("authorization_nonce", None)
        if generation is None or nonce is None:
            issuance = PurgeReauthService.issue_local_authorization(
                kwargs["request_id"], kwargs["executor_user_id"], "TestPassword123!"
            )
            generation = issuance.generation
            nonce = issuance.raw_nonce
        return PurgeService.execute_workspace_purge(
            **kwargs,
            authorization_generation=generation,
            authorization_nonce=nonce,
        )

    def _preclaim(self, request, executor):
        issuance = PurgeReauthService.issue_local_authorization(
            request.id, executor.id, "TestPassword123!"
        )
        claim = PurgeReauthService.claim_for_execution(
            request.id, request.workspace_id, executor.id,
            issuance.generation, issuance.raw_nonce,
        )
        return issuance, claim

    def _active_authorization(self, actor, request, raw_nonce=None, generation=1):
        raw_nonce = raw_nonce or f"nonce-{uuid.uuid4().hex}"
        now = datetime(2026, 1, 5)
        db.session.execute(
            workspace_purge_execution_authorizations_table.insert().values(
                purge_request_id=request.id,
                actor_user_id=actor.id,
                method="local_password",
                generation=generation,
                state="ACTIVE",
                nonce_hash=hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest(),
                authenticated_at=now,
                expires_at=now + timedelta(minutes=5),
            )
        )
        db.session.commit()
        authorization = (
            db.session.query(WorkspacePurgeExecutionAuthorization)
            .filter_by(purge_request_id=request.id, actor_user_id=actor.id)
            .one()
        )
        return authorization, raw_nonce

    def test_disabled_execution_gate_blocks_before_destructive_mutation(self):
        requester, executor, workspace, request = self._fixture(execution_enabled=False)
        with self.assertRaises(PurgeExecutionDisabledError) as context:
            self._execute_workspace_purge(
                request_id=request.id,
                workspace_id=workspace.id,
                executor_user_id=executor.id,
                now=datetime(2026, 2, 1),
            )
        self.assertEqual(context.exception.code, "EXECUTION_DISABLED")
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 1)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).count(), 0)
        stored_request = db.session.get(WorkspacePurgeRequest, request.id)
        self.assertEqual(stored_request.status, "APPROVED")
        self.assertFalse(stored_request.outcome_unknown)

    def test_ui_flag_does_not_enable_execution_gate(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        requester, executor, workspace, request = self._fixture(execution_enabled=False)
        with self.assertRaises(PurgeExecutionDisabledError):
            self._execute_workspace_purge(
                request_id=request.id,
                workspace_id=workspace.id,
                executor_user_id=executor.id,
                now=datetime(2026, 2, 1),
            )

    def test_enabled_execution_gate_reaches_existing_contract_validation(self):
        requester, executor, workspace, request = self._fixture(execution_enabled=True)
        request.status = "REQUESTED"
        db.session.commit()
        with self.assertRaises(PurgeReauthError) as context:
            self._execute_workspace_purge(
                request_id=request.id,
                workspace_id=workspace.id,
                executor_user_id=executor.id,
                now=datetime(2026, 2, 1),
            )
        self.assertEqual(context.exception.code, "REAUTH_REQUEST_INELIGIBLE")

    def test_happy_path_deletes_only_target_business_rows_and_preserves_audit(self):
        requester, executor, workspace, request = self._fixture()
        result = self._execute_workspace_purge(
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
        self.assertEqual(db.session.query(User).count(), 3)
        self.assertEqual(db.session.query(ActivityLog).count(), 3)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).count(), 2)
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 0)
        self.assertEqual(db.session.query(WorkspaceMember).filter_by(workspace_id=workspace.id).count(), 0)

    def test_logo_reference_blocks_before_mutation(self):
        requester, executor, workspace, request = self._fixture(logo="logos/present.png")
        with self.assertRaises(PurgeConflictError) as context:
            self._execute_workspace_purge(
                request_id=request.id,
                workspace_id=workspace.id,
                executor_user_id=executor.id,
                now=datetime(2026, 2, 1),
            )
        self.assertEqual(context.exception.code, "WORKSPACE_LOGO_PRESENT")
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 1)

    def test_single_owner_can_execute_and_staff_cannot_execute(self):
        requester, executor, workspace, request = self._fixture()
        result = self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=requester.id, now=datetime(2026, 2, 1))
        self.assertEqual(result.status, "COMPLETED")
        # A non-Approval Owner remains ineligible for execution.
        staff = User(username=f"staff_{uuid.uuid4().hex[:8]}", full_name="Staff", role="STAFF", approval_status="active", is_active=True)
        staff.set_password("TestPassword123!")
        db.session.add(staff)
        db.session.commit()
        with self.assertRaises(PurgeReauthError):
            self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=staff.id, now=datetime(2026, 2, 1))

    def test_three_distinct_active_local_actors_execute(self):
        requester, executor, workspace, request = self._fixture()
        approver = db.session.get(User, request.approved_by_id)

        self.assertNotEqual(requester.id, approver.id)
        self.assertNotEqual(requester.id, executor.id)
        self.assertNotEqual(approver.id, executor.id)
        self.assertEqual(executor.auth_provider, "local")

        result = self._execute_workspace_purge(
            request_id=request.id,
            workspace_id=workspace.id,
            executor_user_id=executor.id,
            now=datetime(2026, 2, 1),
        )

        self.assertEqual(result.status, "COMPLETED")

    def test_single_approval_owner_can_reauth_and_execute_own_request(self):
        requester, _executor, workspace, request = self._fixture()
        request.approved_by_id = requester.id
        request.approved_by_snapshot = requester.username
        db.session.commit()

        issuance = PurgeReauthService.issue_local_authorization(
            request.id, requester.id, "TestPassword123!"
        )
        result = PurgeService.execute_workspace_purge(
            request_id=request.id,
            workspace_id=workspace.id,
            executor_user_id=requester.id,
            authorization_generation=issuance.generation,
            authorization_nonce=issuance.raw_nonce,
            now=datetime(2026, 2, 1),
        )

        self.assertEqual(result.status, "COMPLETED")
        db.session.expire_all()
        stored = db.session.get(WorkspacePurgeRequest, request.id)
        self.assertEqual(stored.requested_by_id, requester.id)
        self.assertEqual(stored.approved_by_id, requester.id)
        self.assertEqual(stored.execution_triggered_by_id, requester.id)

    def test_eligible_approver_can_execute_as_executor(self):
        _requester, _executor, workspace, request = self._fixture()
        result = self._execute_workspace_purge(
            request_id=request.id,
            workspace_id=workspace.id,
            executor_user_id=request.approved_by_id,
            now=datetime(2026, 2, 1),
        )
        self.assertEqual(result.status, "COMPLETED")

    def test_malformed_missing_actor_fails_closed(self):
        requester, executor, workspace, request = self._fixture()
        request.approved_by_id = None
        db.session.commit()

        with self.assertRaises(PurgeReauthError) as context:
            self._execute_workspace_purge(
                request_id=request.id,
                workspace_id=workspace.id,
                executor_user_id=executor.id,
                now=datetime(2026, 2, 1),
            )

        self.assertEqual(context.exception.code, "REAUTH_REQUEST_INELIGIBLE")
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 1)

    def test_google_only_executor_is_rejected_even_with_generated_password_hash(self):
        _requester, executor, workspace, request = self._fixture()
        executor.auth_provider = "google"
        db.session.commit()

        with self.assertRaises(PurgeReauthError) as context:
            self._execute_workspace_purge(
                request_id=request.id,
                workspace_id=workspace.id,
                executor_user_id=executor.id,
                now=datetime(2026, 2, 1),
            )

        self.assertEqual(context.exception.code, "REAUTH_PROVIDER_UNSUPPORTED")
        self.assertTrue(executor.password_hash)
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 1)

    def test_google_requester_and_approver_do_not_block_local_executor(self):
        requester, executor, workspace, request = self._fixture()
        approver = db.session.get(User, request.approved_by_id)
        requester.auth_provider = "google"
        approver.auth_provider = "google"
        db.session.commit()

        result = self._execute_workspace_purge(
            request_id=request.id,
            workspace_id=workspace.id,
            executor_user_id=executor.id,
            now=datetime(2026, 2, 1),
        )

        self.assertEqual(result.status, "COMPLETED")

    def test_missing_approver_blocks_execution(self):
        _requester, executor, workspace, request = self._fixture()
        request.approved_by_id = None
        db.session.commit()

        with self.assertRaises(PurgeReauthError) as context:
            self._execute_workspace_purge(
                request_id=request.id,
                workspace_id=workspace.id,
                executor_user_id=executor.id,
                now=datetime(2026, 2, 1),
            )

        self.assertEqual(context.exception.code, "REAUTH_REQUEST_INELIGIBLE")
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 1)

    def test_requester_approver_and_executor_eligibility_are_rechecked(self):
        actor_cases = (
            ("requester", "role", "STAFF", "REQUESTER_ACTOR_INELIGIBLE"),
            ("approver", "approval_status", User.APPROVAL_REJECTED, "APPROVER_ACTOR_INELIGIBLE"),
            ("executor", "is_active", False, "EXECUTOR_ACTOR_INELIGIBLE"),
            ("executor", "deleted_at", datetime(2026, 1, 3), "EXECUTOR_ACTOR_INELIGIBLE"),
        )
        for actor_name, field, value, expected_code in actor_cases:
            with self.subTest(actor=actor_name, field=field):
                requester, executor, workspace, request = self._fixture()
                actor_id = {
                    "requester": requester.id,
                    "approver": request.approved_by_id,
                    "executor": executor.id,
                }[actor_name]
                actor = db.session.get(User, actor_id)
                setattr(actor, field, value)
                db.session.commit()

                with self.assertRaises(PurgeReauthError) as context:
                    self._execute_workspace_purge(
                        request_id=request.id,
                        workspace_id=workspace.id,
                        executor_user_id=executor.id,
                        now=datetime(2026, 2, 1),
                    )

                self.assertEqual(context.exception.code, "REAUTH_ACTOR_INELIGIBLE")
                self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 1)

    def test_runtime_failure_rolls_back_and_records_failed_event(self):
        requester, executor, workspace, request = self._fixture()
        execution_time = datetime(2026, 2, 1)
        executor_username = executor.username
        with patch.object(PurgeService, "_delete_exact_rows", side_effect=RuntimeError("injected")):
            with self.assertRaises(PurgeExecutionError):
                self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=execution_time)
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
        first = self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        with self.assertRaises(PurgeReauthError) as context:
            self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 2))
        self.assertEqual(context.exception.code, "REAUTH_REQUEST_INELIGIBLE")
        self.assertFalse(first.already_completed)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).count(), 2)

    def test_completed_retry_requires_authorized_executor(self):
        requester, executor, workspace, request = self._fixture()
        self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        with self.assertRaises(PurgeReauthError):
            self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=requester.id, now=datetime(2026, 2, 2))
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
                expected_error = PurgeConflictError if field == "idempotency_key" else PurgeReauthError
                with self.assertRaises(expected_error) as context:
                    self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
                expected_code = "INVALID_IDEMPOTENCY_KEY" if field == "idempotency_key" else "REAUTH_REQUEST_INELIGIBLE"
                self.assertEqual(context.exception.code, expected_code)

    def test_service_does_not_commit_or_rollback_caller_session(self):
        requester, executor, workspace, request = self._fixture()
        request_id = request.id
        workspace_id = workspace.id
        requester_id = requester.id
        unrelated = User(username=f"pending_{uuid.uuid4().hex[:8]}", full_name="Pending", role="STAFF", approval_status="active", is_active=True)
        unrelated.set_password("PendingPassword123!")
        db.session.add(unrelated)
        result = self._execute_workspace_purge(request_id=request_id, workspace_id=workspace_id, executor_user_id=requester_id, now=datetime(2026, 2, 1))
        self.assertEqual(result.status, "COMPLETED")
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
        result = self._execute_workspace_purge(request_id=request_id, workspace_id=workspace_id, executor_user_id=executor_id, now=datetime(2026, 2, 1))
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
        result = self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
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
            self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now="not-a-datetime")
        self.assertEqual(context.exception.code, "INVALID_NOW")
        request.status = "REQUESTED"
        db.session.commit()
        with self.assertRaises(PurgeReauthError) as context:
            self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        self.assertEqual(context.exception.code, "REAUTH_REQUEST_INELIGIBLE")

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
            self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        self.assertEqual(context.exception.code, "ACTIVE_LEGAL_HOLD")
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 1)

    def test_legal_hold_create_release_and_atomic_audit_contract(self):
        requester, executor, workspace, _request = self._fixture()
        created = PurgeLegalHoldService.create_legal_hold(
            workspace_id=workspace.id, actor_user_id=requester.id,
            hold_type="LEGAL", reason="Litigation preservation",
            confirmation_phrase=f"HOLD {workspace.slug}",
        )
        stored = db.session.query(PurgeLegalHold).filter_by(hold_id=created.hold_id).one()
        self.assertEqual(stored.status, "ACTIVE")
        self.assertEqual(stored.placed_by_id, requester.id)
        self.assertIsNone(stored.released_at)
        self.assertEqual(db.session.query(ActivityLog).filter_by(action="LEGAL_HOLD_CREATE").count(), 1)

        released = PurgeLegalHoldService.release_legal_hold(
            hold_id=created.hold_id, actor_user_id=executor.id,
            release_reason="Matter resolved", confirmation_phrase=f"RELEASE {created.hold_id}",
        )
        self.assertEqual(released.status, "RELEASED")
        db.session.expire_all()
        stored = db.session.query(PurgeLegalHold).filter_by(hold_id=created.hold_id).one()
        self.assertEqual(stored.placed_by_id, requester.id)
        self.assertEqual(stored.released_by_id, executor.id)
        self.assertEqual(db.session.query(ActivityLog).filter_by(action="LEGAL_HOLD_RELEASE").count(), 1)

        with self.assertRaises(PurgeLegalHoldConflictError) as second_release:
            PurgeLegalHoldService.release_legal_hold(
                hold_id=created.hold_id, actor_user_id=executor.id,
                release_reason="Overwrite", confirmation_phrase=f"RELEASE {created.hold_id}",
            )
        self.assertEqual(second_release.exception.code, "ALREADY_RELEASED")

    def test_legal_hold_create_does_not_require_purge_request(self):
        requester, _executor, _workspace, _request = self._fixture()
        standalone = Workspace(
            name="Standalone Hold Target",
            slug=f"standalone-hold-{uuid.uuid4().hex}",
            status="active",
            deleted_at=datetime(2026, 1, 1),
            deleted_by_id=requester.id,
        )
        db.session.add(standalone)
        db.session.commit()

        created = PurgeLegalHoldService.create_legal_hold(
            workspace_id=standalone.id,
            actor_user_id=requester.id,
            hold_type="LEGAL",
            reason="Before a purge request exists",
            confirmation_phrase=f"HOLD {standalone.slug}",
        )

        stored = db.session.query(PurgeLegalHold).filter_by(hold_id=created.hold_id).one()
        self.assertEqual(stored.workspace_id, standalone.id)
        self.assertEqual(stored.status, "ACTIVE")
        self.assertEqual(
            db.session.query(WorkspacePurgeRequest).filter_by(workspace_id=standalone.id).count(), 0
        )

    def test_legal_hold_authorization_binding_and_audit_failure_fail_closed(self):
        requester, executor, workspace, _request = self._fixture()
        staff = User(username=f"hold_staff_{uuid.uuid4().hex[:8]}", full_name="Staff", role="STAFF", approval_status="active", is_active=True)
        staff.set_password("StaffPassword123!")
        db.session.add(staff)
        db.session.commit()
        with self.assertRaises(PurgeLegalHoldAuthorizationError):
            PurgeLegalHoldService.create_legal_hold(
                workspace_id=workspace.id, actor_user_id=staff.id, hold_type="LEGAL",
                reason="No", confirmation_phrase=f"HOLD {workspace.slug}",
            )
        with self.assertRaises(PurgeLegalHoldConflictError):
            PurgeLegalHoldService.create_legal_hold(
                workspace_id=workspace.id, actor_user_id=requester.id, hold_type="bad type",
                reason="No", confirmation_phrase=f"HOLD {workspace.slug}",
            )
        with patch.object(PurgeLegalHoldService, "_audit", side_effect=RuntimeError("audit failure")):
            with self.assertRaises(RuntimeError):
                PurgeLegalHoldService.create_legal_hold(
                    workspace_id=workspace.id, actor_user_id=requester.id, hold_type="LEGAL",
                    reason="Rollback", confirmation_phrase=f"HOLD {workspace.slug}",
                )
        self.assertEqual(db.session.query(PurgeLegalHold).count(), 0)

    def test_legal_hold_mutations_preserve_workspace_first_atomic_lock_contract(self):
        import inspect
        create_source = inspect.getsource(PurgeLegalHoldService.create_legal_hold)
        release_source = inspect.getsource(PurgeLegalHoldService.release_legal_hold)
        self.assertLess(create_source.index("_workspace_for_mutation"), create_source.index("session.add(hold)"))
        self.assertLess(create_source.index("session.add(hold)"), create_source.index("_audit"))
        self.assertEqual(create_source.count("session.commit()"), 1)
        self.assertLess(release_source.index("hold_identity"), release_source.index("_workspace_for_mutation"))
        self.assertLess(release_source.index("_workspace_for_mutation"), release_source.index("with_for_update"))
        self.assertIn("populate_existing()", release_source)
        self.assertLess(release_source.index("populate_existing()"), release_source.index("if hold.status"))
        self.assertLess(release_source.index("_audit"), release_source.index("session.commit()"))
        self.assertEqual(release_source.count("session.commit()"), 1)

    def test_release_execution_contract_keeps_active_hold_before_first_delete(self):
        import inspect
        execution_source = inspect.getsource(PurgeService.execute_workspace_purge)
        self.assertLess(execution_source.index("_validate_holds"), execution_source.index("_delete_exact_rows"))
        self.assertNotIn("status = \"COMPLETED\"", execution_source[:execution_source.index("_validate_holds")])

    def test_tenant_rows_are_not_deleted(self):
        requester, executor, workspace, request = self._fixture()
        other_workspace = Workspace(name="Other", slug=f"other-{uuid.uuid4().hex}", status="active")
        db.session.add(other_workspace)
        db.session.flush()
        other_customer = Customer(name="Other Customer", workspace_id=other_workspace.id)
        db.session.add(other_customer)
        db.session.commit()
        self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
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
        with self.assertRaises(PurgeReauthError) as context:
            self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=second)
        self.assertEqual(context.exception.code, "REAUTH_REQUEST_INELIGIBLE")
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
        issuance, claim = self._preclaim(request, executor)
        real_commit = Session.commit
        state = {"raised": False}

        def commit_then_raise(session, *args, **kwargs):
            real_commit(session, *args, **kwargs)
            if not state["raised"]:
                state["raised"] = True
                raise RuntimeError("acknowledgement lost")

        with patch.object(PurgeReauthService, "claim_for_execution", return_value=claim), patch.object(Session, "commit", new=commit_then_raise):
            result = self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, authorization_generation=issuance.generation, authorization_nonce=issuance.raw_nonce, now=datetime(2026, 2, 1))
        self.assertTrue(result.status == "COMPLETED")
        db.session.expire_all()
        self.assertEqual(db.session.get(WorkspacePurgeRequest, request.id).status, "COMPLETED")
        self.assertFalse(db.session.get(WorkspacePurgeRequest, request.id).outcome_unknown)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="failed").count(), 0)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="completed").count(), 1)

    def test_commit_unknown_blocks_retry_without_failed_event(self):
        requester, executor, workspace, request = self._fixture()
        issuance, claim = self._preclaim(request, executor)
        real_commit = Session.commit
        state = {"raised": False}

        def fail_first_commit(session, *args, **kwargs):
            if not state["raised"]:
                state["raised"] = True
                raise RuntimeError("commit result unknown")
            return real_commit(session, *args, **kwargs)

        with patch.object(PurgeReauthService, "claim_for_execution", return_value=claim), patch.object(Session, "commit", new=fail_first_commit):
            with self.assertRaises(PurgeCommitOutcomeUnknownError):
                self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, authorization_generation=issuance.generation, authorization_nonce=issuance.raw_nonce, now=datetime(2026, 2, 1))
        db.session.expire_all()
        stored = db.session.get(WorkspacePurgeRequest, request.id)
        self.assertTrue(stored.outcome_unknown)
        self.assertNotEqual(stored.status, "FAILED")
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="failed").count(), 0)
        with self.assertRaises(PurgeReauthError) as context:
            self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 2))
        self.assertEqual(context.exception.code, "REAUTH_REQUEST_INELIGIBLE")

    def test_reconciliation_failure_bypasses_failure_audit(self):
        requester, executor, workspace, request = self._fixture()
        issuance, claim = self._preclaim(request, executor)
        def fail_commit(session, *args, **kwargs):
            raise RuntimeError("commit acknowledgement failure")

        with patch.object(PurgeReauthService, "claim_for_execution", return_value=claim), patch.object(Session, "commit", new=fail_commit), patch.object(PurgeService, "_reconcile_commit_outcome", side_effect=PurgeCommitOutcomeUnknownError()), patch.object(PurgeService, "_record_failure") as record_failure:
            with self.assertRaises(PurgeCommitOutcomeUnknownError):
                self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, authorization_generation=issuance.generation, authorization_nonce=issuance.raw_nonce, now=datetime(2026, 2, 1))
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
                    self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
                self.assertEqual(context.exception.code, expected_code)

    def test_manifest_validation_rejects_row_and_logo_drift(self):
        requester, executor, workspace, request = self._fixture()
        db.session.add(Customer(name="Drift", phone="0909999999", workspace_id=workspace.id))
        db.session.commit()
        with self.assertRaises(PurgeConflictError) as context:
            self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        self.assertEqual(context.exception.code, "MANIFEST_MISMATCH")

        requester, executor, workspace, request = self._fixture()
        db.session.add(Setting(workspace_id=workspace.id, key="spa_logo", value="logo.png"))
        db.session.commit()
        with self.assertRaises(PurgeConflictError) as context:
            self._execute_workspace_purge(request_id=request.id, workspace_id=workspace.id, executor_user_id=executor.id, now=datetime(2026, 2, 1))
        self.assertEqual(context.exception.code, "MANIFEST_MISMATCH")

    def test_reauth_issue_success_persists_only_hash_and_resets_throttle(self):
        requester, executor, workspace, request = self._fixture()
        issuance = PurgeReauthService.issue_local_authorization(request.id, executor.id, "TestPassword123!")
        self.assertEqual(issuance.generation, 1)
        self.assertGreaterEqual(len(issuance.raw_nonce), 43)
        self.assertNotIn(issuance.raw_nonce, repr(issuance))
        authorization = db.session.query(WorkspacePurgeExecutionAuthorization).one()
        self.assertNotEqual(authorization.nonce_hash, issuance.raw_nonce)
        self.assertEqual(len(authorization.nonce_hash), 64)
        self.assertEqual(authorization.state, "ACTIVE")
        self.assertLessEqual(issuance.expires_at - issuance.authenticated_at, timedelta(minutes=5))
        throttle = db.session.query(WorkspacePurgeReauthActorThrottle).one()
        self.assertEqual(throttle.failed_attempt_count, 0)
        self.assertEqual(db.session.query(ActivityLog).count(), 2)

    def test_reauth_bad_password_is_durable_and_actor_global_rate_limited(self):
        requester, executor, workspace, request = self._fixture()
        for _ in range(4):
            with self.assertRaises(PurgeReauthInvalidCredentialError):
                PurgeReauthService.issue_local_authorization(request.id, executor.id, "wrong")
        with self.assertRaises(PurgeReauthInvalidCredentialError):
            PurgeReauthService.issue_local_authorization(request.id, executor.id, "wrong")
        with self.assertRaises(PurgeReauthRateLimitedError):
            PurgeReauthService.issue_local_authorization(request.id, executor.id, "TestPassword123!")
        throttle = db.session.query(WorkspacePurgeReauthActorThrottle).one()
        self.assertEqual(throttle.failed_attempt_count, 5)
        self.assertIsNotNone(throttle.locked_until)

    def test_direct_execution_requires_durable_reauth(self):
        requester, executor, workspace, request = self._fixture()
        with self.assertRaises(PurgeReauthRequiredError):
            PurgeService.execute_workspace_purge(
                request_id=request.id,
                workspace_id=workspace.id,
                executor_user_id=executor.id,
                now=datetime(2026, 2, 1),
            )
        self.assertEqual(db.session.query(Customer).filter_by(workspace_id=workspace.id).count(), 1)

    def test_claim_before_purge_and_success_transition(self):
        requester, executor, workspace, request = self._fixture()
        issuance = PurgeReauthService.issue_local_authorization(request.id, executor.id, "TestPassword123!")
        result = self._execute_workspace_purge(
            request_id=request.id,
            workspace_id=workspace.id,
            executor_user_id=executor.id,
            authorization_generation=issuance.generation,
            authorization_nonce=issuance.raw_nonce,
            now=datetime(2026, 2, 1),
        )
        self.assertEqual(result.status, "COMPLETED")
        authorization = db.session.query(WorkspacePurgeExecutionAuthorization).one()
        self.assertEqual(authorization.state, "CONSUMED_SUCCESS")
        self.assertIsNone(authorization.nonce_hash)
        self.assertIsNotNone(authorization.execution_started_event_id)

    def test_claim_locks_request_workspace_actors_before_authorization_audit(self):
        requester, executor, workspace, request = self._fixture()
        issuance = PurgeReauthService.issue_local_authorization(request.id, executor.id, "TestPassword123!")
        events = []
        original_load_request = PurgeReauthService._load_request
        original_lock_workspace = PurgeReauthService._lock_workspace_for_claim
        original_load_actors = PurgeReauthService._load_actors
        original_audit = PurgeReauthService._audit

        def load_request(session, purge_request_id):
            events.append("request")
            return original_load_request(session, purge_request_id)

        def lock_workspace(session, workspace_id):
            events.append("workspace")
            return original_lock_workspace(session, workspace_id)

        def load_actors(session, purge_request, executor_user_id):
            authorization = (
                session.query(WorkspacePurgeExecutionAuthorization)
                .filter_by(purge_request_id=purge_request.id)
                .one()
            )
            self.assertEqual(authorization.state, "ACTIVE")
            events.append("actors")
            return original_load_actors(session, purge_request, executor_user_id)

        def audit(session, **kwargs):
            authorization = (
                session.query(WorkspacePurgeExecutionAuthorization)
                .filter_by(purge_request_id=request.id)
                .one()
            )
            self.assertEqual(authorization.state, "CLAIMED")
            events.append("audit")
            return original_audit(session, **kwargs)

        with patch.object(PurgeReauthService, "_load_request", side_effect=load_request), \
             patch.object(PurgeReauthService, "_lock_workspace_for_claim", side_effect=lock_workspace), \
             patch.object(PurgeReauthService, "_load_actors", side_effect=load_actors), \
             patch.object(PurgeReauthService, "_audit", side_effect=audit):
            PurgeReauthService.claim_for_execution(
                request.id, workspace.id, executor.id, issuance.generation, issuance.raw_nonce
            )

        self.assertEqual(events, ["request", "workspace", "actors", "audit"])

    def test_claim_workspace_lock_failure_rolls_back_without_authorization_mutation_or_audit(self):
        requester, executor, workspace, request = self._fixture()
        issuance = PurgeReauthService.issue_local_authorization(request.id, executor.id, "TestPassword123!")
        with patch.object(PurgeReauthService, "_lock_workspace_for_claim", return_value=None), \
             patch.object(PurgeReauthService, "_audit") as audit:
            with self.assertRaises(PurgeReauthRequestIneligibleError) as context:
                PurgeReauthService.claim_for_execution(
                    request.id, workspace.id, executor.id, issuance.generation, issuance.raw_nonce
                )

        self.assertEqual(context.exception.code, "REAUTH_REQUEST_INELIGIBLE")
        db.session.expire_all()
        authorization = (
            db.session.query(WorkspacePurgeExecutionAuthorization)
            .filter_by(purge_request_id=request.id)
            .one()
        )
        self.assertEqual(authorization.state, "ACTIVE")
        self.assertEqual(authorization.nonce_hash, hashlib.sha256(issuance.raw_nonce.encode("utf-8")).hexdigest())
        self.assertEqual(db.session.query(ActivityLog).filter_by(action="CLAIM").count(), 0)
        audit.assert_not_called()

    def test_password_change_revokes_authorization_atomically_when_flags_disabled(self):
        requester, executor, workspace, request = self._fixture(execution_enabled=False)
        authorization, raw_nonce = self._active_authorization(executor, request)

        result = AuthService.change_password(
            executor, "TestPassword123!", "NewPassword456!", "NewPassword456!"
        )

        self.assertTrue(result[0])
        db.session.expire_all()
        executor = db.session.get(User, executor.id)
        authorization = db.session.get(WorkspacePurgeExecutionAuthorization, authorization.id)
        self.assertTrue(executor.check_password("NewPassword456!"))
        self.assertFalse(executor.check_password("TestPassword123!"))
        self.assertEqual(authorization.state, "REVOKED")
        self.assertEqual(authorization.revocation_reason, "PASSWORD_CHANGED")
        self.assertIsNone(authorization.nonce_hash)
        with self.assertRaises(PurgeReauthError):
            PurgeReauthService.claim_for_execution(
                request.id, workspace.id, executor.id, authorization.generation, raw_nonce
            )

    def test_password_reset_revokes_target_authorization_not_admin(self):
        requester, executor, workspace, request = self._fixture(execution_enabled=False)
        manager = User(username=f"manager_{uuid.uuid4().hex[:8]}", full_name="Manager", role="OWNER")
        manager.set_password("ManagerPassword123!")
        target = User(username=f"target_{uuid.uuid4().hex[:8]}", full_name="Target", role="STAFF")
        target.set_password("TargetPassword123!")
        db.session.add_all([manager, target])
        db.session.commit()
        target_auth, raw_nonce = self._active_authorization(target, request)

        UserService.reset_password(manager, target.id, "ResetPassword456!")

        db.session.expire_all()
        target = db.session.get(User, target.id)
        target_auth = db.session.get(WorkspacePurgeExecutionAuthorization, target_auth.id)
        self.assertTrue(target.check_password("ResetPassword456!"))
        self.assertFalse(target.check_password("TargetPassword123!"))
        self.assertEqual(target_auth.state, "REVOKED")
        self.assertEqual(target_auth.revocation_reason, "PASSWORD_RESET")
        self.assertIsNone(target_auth.nonce_hash)
        with self.assertRaises(PurgeReauthError):
            PurgeReauthService.claim_for_execution(
                request.id, workspace.id, target.id, target_auth.generation, raw_nonce
            )

    def test_password_mutation_revocation_failure_rolls_back_change(self):
        requester, executor, workspace, request = self._fixture(execution_enabled=False)
        authorization, _raw_nonce = self._active_authorization(executor, request)

        with patch(
            "services.purge_reauth_service.PurgeReauthService._revoke_active_authorizations_for_actor_in_session",
            side_effect=RuntimeError("synthetic revocation failure"),
        ):
            with self.assertRaises(RuntimeError):
                AuthService.change_password(
                    executor, "TestPassword123!", "NewPassword456!", "NewPassword456!"
                )

        db.session.expire_all()
        executor = db.session.get(User, executor.id)
        authorization = db.session.get(WorkspacePurgeExecutionAuthorization, authorization.id)
        self.assertTrue(executor.check_password("TestPassword123!"))
        self.assertFalse(executor.check_password("NewPassword456!"))
        self.assertEqual(authorization.state, "ACTIVE")

    def test_invalid_password_change_does_not_revoke_authorization(self):
        requester, executor, workspace, request = self._fixture(execution_enabled=False)
        authorization, _raw_nonce = self._active_authorization(executor, request)

        with self.assertRaises(ValidationException):
            AuthService.change_password(
                executor, "wrong-password", "NewPassword456!", "NewPassword456!"
            )

        db.session.expire_all()
        authorization = db.session.get(WorkspacePurgeExecutionAuthorization, authorization.id)
        self.assertEqual(authorization.state, "ACTIVE")
        self.assertIsNone(authorization.revocation_reason)

    def test_password_mutations_succeed_without_authorization_rows(self):
        requester, executor, workspace, request = self._fixture(execution_enabled=False)
        result = AuthService.change_password(
            executor, "TestPassword123!", "NewPassword456!", "NewPassword456!"
        )
        self.assertTrue(result[0])

        target = User(username=f"target_{uuid.uuid4().hex[:8]}", full_name="Target", role="STAFF")
        target.set_password("TargetPassword123!")
        manager = User(username=f"manager_{uuid.uuid4().hex[:8]}", full_name="Manager", role="OWNER")
        manager.set_password("ManagerPassword123!")
        db.session.add_all([target, manager])
        db.session.commit()
        self.assertIsNotNone(UserService.reset_password(manager, target.id, "ResetPassword456!"))

    def test_password_reset_revocation_failure_rolls_back_change(self):
        requester, executor, workspace, request = self._fixture(execution_enabled=False)
        target = User(username=f"target_{uuid.uuid4().hex[:8]}", full_name="Target", role="STAFF")
        target.set_password("TargetPassword123!")
        manager = User(username=f"manager_{uuid.uuid4().hex[:8]}", full_name="Manager", role="OWNER")
        manager.set_password("ManagerPassword123!")
        db.session.add_all([target, manager])
        db.session.commit()
        authorization, _raw_nonce = self._active_authorization(target, request)

        with patch(
            "services.purge_reauth_service.PurgeReauthService._revoke_active_authorizations_for_actor_in_session",
            side_effect=RuntimeError("synthetic revocation failure"),
        ):
            with self.assertRaises(RuntimeError):
                UserService.reset_password(manager, target.id, "ResetPassword456!")

        db.session.expire_all()
        target = db.session.get(User, target.id)
        authorization = db.session.get(WorkspacePurgeExecutionAuthorization, authorization.id)
        self.assertTrue(target.check_password("TargetPassword123!"))
        self.assertFalse(target.check_password("ResetPassword456!"))
        self.assertEqual(authorization.state, "ACTIVE")

    def test_password_change_revokes_only_the_affected_actor(self):
        requester, executor, workspace, request = self._fixture(execution_enabled=False)
        own_authorization, _raw_nonce = self._active_authorization(executor, request)
        other_workspace = Workspace(
            name="Other Purge Target",
            slug=f"other-purge-{uuid.uuid4().hex}",
            status="active",
            deleted_at=datetime(2026, 1, 1),
            deleted_by_id=requester.id,
        )
        db.session.add(other_workspace)
        db.session.commit()
        request_values = {
            column.name: getattr(request, column.name)
            for column in WorkspacePurgeRequest.__table__.columns
            if column.name not in {"id", "lifecycle_id", "idempotency_key"}
        }
        request_values.update(
            workspace_id=other_workspace.id,
            target_workspace_name=other_workspace.name,
            target_workspace_slug=other_workspace.slug,
            lifecycle_id=str(uuid.uuid4()),
            idempotency_key=f"purge-{uuid.uuid4().hex}",
        )
        db.session.execute(WorkspacePurgeRequest.__table__.insert().values(**request_values))
        db.session.commit()
        other_request = (
            db.session.query(WorkspacePurgeRequest)
            .filter(WorkspacePurgeRequest.lifecycle_id == request_values["lifecycle_id"])
            .one()
        )
        other_authorization, _other_nonce = self._active_authorization(requester, other_request)

        AuthService.change_password(
            executor, "TestPassword123!", "NewPassword456!", "NewPassword456!"
        )

        db.session.expire_all()
        own_authorization = db.session.get(WorkspacePurgeExecutionAuthorization, own_authorization.id)
        other_authorization = db.session.get(WorkspacePurgeExecutionAuthorization, other_authorization.id)
        self.assertEqual(own_authorization.state, "REVOKED")
        self.assertEqual(own_authorization.revocation_reason, "PASSWORD_CHANGED")
        self.assertEqual(other_authorization.state, "ACTIVE")
