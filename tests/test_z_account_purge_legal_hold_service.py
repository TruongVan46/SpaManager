import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

TEST_DB = Path(tempfile.gettempdir()) / "spamanager_account_purge_legal_hold_test.sqlite"
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("TEST_DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
from app import app
from extensions import db
from models.account_purge import AccountPurgeLegalHold, AccountPurgeLifecycleEvent, AccountPurgeRequest, UserCreationProvenance
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.account_purge_legal_hold_service import (
    AccountPurgeLegalHoldService,
    AccountPurgeLegalHoldServiceError,
)
from services.account_purge_service import AccountPurgeService


class AccountPurgeLegalHoldServiceTests(unittest.TestCase):
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
        self.workspace = Workspace(name="Managed", slug="hold-managed", status="active")
        self.owner = self._user("hold_owner", "OWNER")
        self.approver = self._user("hold_approver", "APPROVAL_OWNER")
        self.target = self._user("hold_target", "STAFF")
        db.session.add(self.workspace)
        db.session.flush()
        db.session.add_all([
            WorkspaceMember(workspace_id=self.workspace.id, user_id=self.owner.id, role="owner", status="active"),
            WorkspaceMember(workspace_id=self.workspace.id, user_id=self.target.id, role="staff", status="removed", removed_at=datetime(2026, 1, 1)),
        ])
        db.session.add(UserCreationProvenance(user_id=self.target.id, created_by_user_id=self.owner.id, created_in_workspace_id=self.workspace.id, creation_source="WORKSPACE_OWNER", created_role="STAFF", provenance_version=1))
        db.session.commit()

    def _user(self, username, role):
        user = User(username=username, email=f"{username}@example.test", full_name=username.title(), role=role, is_active=True, approval_status="active")
        user.set_password("StrongPassword123!")
        db.session.add(user)
        db.session.flush()
        return user

    def _request(self):
        return AccountPurgeService.create_request(requester_id=self.owner.id, target_user_id=self.target.id, managing_workspace_id=self.workspace.id, reason="hold request", now=datetime(2026, 2, 1))

    def _assert_code(self, callback, code):
        with self.assertRaises(AccountPurgeLegalHoldServiceError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_place_target_workspace_and_request_holds_with_snapshots_and_events(self):
        request = self._request()
        target_hold = AccountPurgeLegalHoldService.place_hold(target_user_id=self.target.id, actor_user_id=self.approver.id, managing_workspace_id=self.workspace.id, reason=" target review ")
        self.assertEqual(target_hold.state, "ACTIVE")
        self.assertEqual(target_hold.placed_by_role_snapshot, "APPROVAL_OWNER")
        self._assert_code(lambda: AccountPurgeLegalHoldService.place_hold(target_user_id=self.target.id, actor_user_id=self.approver.id, managing_workspace_id=self.workspace.id, reason="duplicate"), "DUPLICATE_ACTIVE_HOLD")
        request_hold = AccountPurgeLegalHoldService.place_hold(target_user_id=self.target.id, actor_user_id=self.approver.id, request_id=request.id, reason=" request review ")
        self.assertEqual(request_hold.managing_workspace_id, self.workspace.id)
        events = AccountPurgeLifecycleEvent.query.filter_by(request_id=request.id, event_type="LEGAL_HOLD_PLACED").all()
        self.assertEqual(len(events), 1)

    def test_place_hold_authorization_target_binding_and_list_history(self):
        self._assert_code(lambda: AccountPurgeLegalHoldService.place_hold(target_user_id=self.target.id, actor_user_id=self.owner.id, reason="no"), "ACTOR_NOT_AUTHORIZED")
        self._assert_code(lambda: AccountPurgeLegalHoldService.place_hold(target_user_id=self.approver.id, actor_user_id=self.approver.id, reason="self"), "ACTOR_TARGET_CONFLICT")
        self._assert_code(lambda: AccountPurgeLegalHoldService.place_hold(target_user_id=self.target.id, actor_user_id=self.approver.id, managing_workspace_id=99999, reason="wrong"), "WORKSPACE_NOT_FOUND")
        summary = AccountPurgeLegalHoldService.place_hold(target_user_id=self.target.id, actor_user_id=self.approver.id, managing_workspace_id=self.workspace.id, reason="history")
        self.assertEqual(len(AccountPurgeLegalHoldService.inspect_active_holds(target_user_id=self.target.id, actor_user_id=self.approver.id)), 1)
        self.assertEqual(len(AccountPurgeLegalHoldService.list_holds(target_user_id=self.target.id, actor_user_id=self.approver.id)), 1)
        return summary

    def test_release_increments_version_preserves_history_and_released_hold_does_not_block(self):
        hold = AccountPurgeLegalHoldService.place_hold(target_user_id=self.target.id, actor_user_id=self.approver.id, managing_workspace_id=self.workspace.id, reason="release test")
        released = AccountPurgeLegalHoldService.release_hold(hold_id=hold.id, actor_user_id=self.approver.id, release_reason=" cleared ", expected_version=1)
        self.assertEqual((released.state, released.version, released.release_reason), ("RELEASED", 2, "cleared"))
        self.assertEqual(AccountPurgeLegalHoldService.inspect_active_holds(target_user_id=self.target.id, actor_user_id=self.approver.id), [])
        self.assertEqual(len(AccountPurgeLegalHoldService.list_holds(target_user_id=self.target.id, actor_user_id=self.approver.id)), 1)
        self._assert_code(lambda: AccountPurgeLegalHoldService.release_hold(hold_id=hold.id, actor_user_id=self.approver.id, release_reason="again"), "HOLD_NOT_ACTIVE")

    def test_release_guards_actor_and_stale_version(self):
        hold = AccountPurgeLegalHoldService.place_hold(target_user_id=self.target.id, actor_user_id=self.approver.id, reason="guards")
        self._assert_code(lambda: AccountPurgeLegalHoldService.release_hold(hold_id=hold.id, actor_user_id=self.target.id, release_reason="no"), "ACTOR_NOT_AUTHORIZED")
        self._assert_code(lambda: AccountPurgeLegalHoldService.release_hold(hold_id=hold.id, actor_user_id=self.approver.id, release_reason="stale", expected_version=7), "HOLD_VERSION_CONFLICT")

    def test_place_and_release_audit_failure_rolls_back(self):
        with patch.object(AccountPurgeLegalHoldService, "_add_audit", side_effect=SQLAlchemyError("audit failure")):
            self._assert_code(lambda: AccountPurgeLegalHoldService.place_hold(target_user_id=self.target.id, actor_user_id=self.approver.id, reason="rollback"), "PERSISTENCE_FAILURE")
        self.assertEqual(AccountPurgeLegalHold.query.count(), 0)
        hold = AccountPurgeLegalHoldService.place_hold(target_user_id=self.target.id, actor_user_id=self.approver.id, reason="release rollback")
        with patch.object(AccountPurgeLegalHoldService, "_add_audit", side_effect=SQLAlchemyError("audit failure")):
            self._assert_code(lambda: AccountPurgeLegalHoldService.release_hold(hold_id=hold.id, actor_user_id=self.approver.id, release_reason="rollback"), "PERSISTENCE_FAILURE")
        self.assertEqual(db.session.get(AccountPurgeLegalHold, hold.id).state, "ACTIVE")


if __name__ == "__main__":
    unittest.main()
