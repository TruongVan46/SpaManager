import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

TEST_DB = Path(tempfile.gettempdir()) / "spamanager_account_purge_approval_test.sqlite"
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("TEST_DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
from app import app
from models.account_purge import (
    AccountPurgeLifecycleEvent,
    AccountPurgeRequest,
    UserCreationProvenance,
)
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.account_purge_approval_service import (
    AccountPurgeApprovalService,
    AccountPurgeApprovalServiceError,
)
from services.account_purge_service import AccountPurgeService
from extensions import db


class AccountPurgeApprovalServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context()
        cls.context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        if TEST_DB.exists():
            TEST_DB.unlink()
        cls.context.pop()

    def setUp(self):
        db.session.rollback()
        db.drop_all()
        db.create_all()
        self.workspace = Workspace(name="Managed", slug="approval-managed", status="active")
        self.owner = self._user("requester", "OWNER")
        self.approver = self._user("approver", "APPROVAL_OWNER")
        self.target = self._user("target", "STAFF")
        db.session.add(self.workspace)
        db.session.flush()
        db.session.add_all([
            WorkspaceMember(workspace_id=self.workspace.id, user_id=self.owner.id, role="owner", status="active"),
            WorkspaceMember(workspace_id=self.workspace.id, user_id=self.target.id, role="staff", status="removed", removed_at=datetime(2026, 1, 1)),
        ])
        db.session.add(UserCreationProvenance(
            user_id=self.target.id, created_by_user_id=self.owner.id,
            created_in_workspace_id=self.workspace.id, creation_source="WORKSPACE_OWNER",
            created_role="STAFF", provenance_version=1,
        ))
        db.session.commit()

    def _user(self, username, role, active=True):
        user = User(
            username=username,
            email=f"{username}@example.test",
            full_name=username.title(),
            role=role,
            is_active=active,
            approval_status="active",
        )
        user.set_password("StrongPassword123!")
        db.session.add(user)
        db.session.flush()
        return user

    def _request(self):
        return AccountPurgeService.create_request(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
            reason="requested for approved internal review",
            now=datetime(2026, 2, 1),
        )

    def _assert_code(self, callback, code):
        with self.assertRaises(AccountPurgeApprovalServiceError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_approval_success_persists_snapshots_version_event_and_no_authorization(self):
        request = self._request()
        result = AccountPurgeApprovalService.approve_request(
            request_id=request.id, approver_user_id=self.approver.id, expected_version=1,
        )
        stored = db.session.get(AccountPurgeRequest, request.id)
        event = AccountPurgeLifecycleEvent.query.filter_by(request_id=request.id, event_type="APPROVED").one()
        self.assertEqual(result.state, "APPROVED")
        self.assertEqual(stored.version, 2)
        self.assertEqual(stored.approver_id, self.approver.id)
        self.assertEqual(stored.approver_role_snapshot, "APPROVAL_OWNER")
        self.assertIsNotNone(stored.approved_at)
        self.assertEqual((event.from_state, event.to_state), ("REQUESTED", "APPROVED"))
        from models.account_purge import AccountPurgeExecutionAuthorization
        self.assertEqual(AccountPurgeExecutionAuthorization.query.count(), 0)

    def test_current_request_is_excluded_from_active_request_recheck(self):
        request = self._request()
        result = AccountPurgeApprovalService.approve_request(
            request_id=request.id, approver_user_id=self.approver.id,
        )
        self.assertEqual(result.state, "APPROVED")

    def test_approval_guards_separation_role_activity_missing_state_and_version(self):
        request = self._request()
        for actor_id, code in ((self.owner.id, "APPROVER_NOT_AUTHORIZED"), (self.target.id, "APPROVER_NOT_AUTHORIZED"), (999999, "APPROVER_NOT_AUTHORIZED")):
            self._assert_code(lambda actor_id=actor_id: AccountPurgeApprovalService.approve_request(request_id=request.id, approver_user_id=actor_id), code)
        inactive = self._user("inactive_approver", "APPROVAL_OWNER", active=False)
        db.session.commit()
        self._assert_code(lambda: AccountPurgeApprovalService.approve_request(request_id=request.id, approver_user_id=inactive.id), "APPROVER_NOT_AUTHORIZED")
        self._assert_code(lambda: AccountPurgeApprovalService.approve_request(request_id=request.id, approver_user_id=self.approver.id, expected_version=9), "REQUEST_VERSION_CONFLICT")
        AccountPurgeApprovalService.approve_request(request_id=request.id, approver_user_id=self.approver.id)
        self._assert_code(lambda: AccountPurgeApprovalService.approve_request(request_id=request.id, approver_user_id=self.approver.id), "INVALID_REQUEST_STATE")

    def test_approval_rechecks_target_restore_provenance_external_google_and_hold(self):
        cases = ("restore", "provenance", "external", "google", "hold")
        for case in cases:
            with self.subTest(case=case):
                self.setUp()
                request = self._request()
                if case == "restore":
                    membership = WorkspaceMember.query.filter_by(workspace_id=self.workspace.id, user_id=self.target.id).one()
                    membership.status = "active"
                    db.session.commit()
                elif case == "provenance":
                    UserCreationProvenance.query.delete()
                    db.session.commit()
                elif case == "external":
                    other = Workspace(name="Other", slug="other-approval", status="active")
                    db.session.add(other)
                    db.session.flush()
                    db.session.add(WorkspaceMember(workspace_id=other.id, user_id=self.target.id, role="staff", status="removed"))
                    db.session.commit()
                elif case == "google":
                    self.target.auth_provider = "google"
                    db.session.commit()
                else:
                    from models.account_purge import AccountPurgeLegalHold
                    db.session.add(AccountPurgeLegalHold(target_user_id=self.target.id, managing_workspace_id=self.workspace.id, state="ACTIVE", reason="review", placed_by_id=self.approver.id, placed_by_name_snapshot=self.approver.full_name, version=1))
                    db.session.commit()
                self._assert_code(lambda: AccountPurgeApprovalService.approve_request(request_id=request.id, approver_user_id=self.approver.id), "ACTIVE_LEGAL_HOLD" if case == "hold" else "TARGET_NO_LONGER_ELIGIBLE")

    def test_rejection_requires_reason_is_atomic_and_does_not_mutate_target(self):
        request = self._request()
        self._assert_code(lambda: AccountPurgeApprovalService.reject_request(request_id=request.id, approver_user_id=self.approver.id, rejection_reason=""), "INVALID_REASON")
        result = AccountPurgeApprovalService.reject_request(request_id=request.id, approver_user_id=self.approver.id, rejection_reason="  policy   review  ", expected_version=1)
        stored = db.session.get(AccountPurgeRequest, request.id)
        self.assertEqual(result.state, "REJECTED")
        self.assertEqual(stored.rejection_reason, "policy review")
        self.assertIsNotNone(stored.terminal_at)
        self.assertEqual(db.session.get(User, self.target.id).account_purge_state, "NOT_PURGED")
        self.assertEqual(AccountPurgeLifecycleEvent.query.filter_by(request_id=request.id, event_type="REJECTED").count(), 1)

    def test_requester_cancellation_only_before_approval_is_atomic(self):
        request = self._request()
        self._assert_code(lambda: AccountPurgeApprovalService.cancel_request(request_id=request.id, requester_user_id=self.approver.id), "REQUESTER_NOT_AUTHORIZED")
        result = AccountPurgeApprovalService.cancel_request(request_id=request.id, requester_user_id=self.owner.id, cancellation_reason=" no longer needed ")
        self.assertEqual(result.state, "CANCELLED")
        self.assertEqual(db.session.get(AccountPurgeRequest, request.id).cancellation_reason, "no longer needed")
        self.assertEqual(AccountPurgeLifecycleEvent.query.filter_by(request_id=request.id, event_type="CANCELLED").count(), 1)
        self._assert_code(lambda: AccountPurgeApprovalService.cancel_request(request_id=request.id, requester_user_id=self.owner.id), "INVALID_REQUEST_STATE")

    def test_approval_rejection_cancellation_lifecycle_failure_rolls_back(self):
        for operation in ("approve", "reject", "cancel"):
            with self.subTest(operation=operation):
                self.setUp()
                request = self._request()
                kwargs = {"request_id": request.id}
                if operation == "approve":
                    kwargs["approver_user_id"] = self.approver.id
                    callback = AccountPurgeApprovalService.approve_request
                elif operation == "reject":
                    kwargs.update(approver_user_id=self.approver.id, rejection_reason="reason")
                    callback = AccountPurgeApprovalService.reject_request
                else:
                    kwargs.update(requester_user_id=self.owner.id, cancellation_reason="reason")
                    callback = AccountPurgeApprovalService.cancel_request
                with patch.object(AccountPurgeApprovalService, "_add_lifecycle_event", side_effect=SQLAlchemyError("event failure")):
                    self._assert_code(lambda: callback(**kwargs), "PERSISTENCE_FAILURE")
                self.assertEqual(db.session.get(AccountPurgeRequest, request.id).state, "REQUESTED")
                self.assertEqual(AccountPurgeLifecycleEvent.query.filter_by(request_id=request.id).count(), 1)


if __name__ == "__main__":
    unittest.main()
