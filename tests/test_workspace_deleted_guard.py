import os
import shutil
import tempfile
import unittest
from pathlib import Path
from datetime import datetime

# Setup unique database file for guard tests
TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_workspace_deleted_guard_test.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_media_workspace_deleted_guard_test"

if TEST_DB_FILE.exists():
    try:
        TEST_DB_FILE.unlink()
    except Exception:
        pass
if TEST_MEDIA_ROOT.exists():
    shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["PERSISTENT_ROOT"] = TEST_MEDIA_ROOT.as_posix()
os.environ["UPLOAD_ROOT"] = (TEST_MEDIA_ROOT / "uploads").as_posix()
os.environ["LOGO_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "logos").as_posix()
os.environ["AVATAR_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "avatars").as_posix()

from app import app
from extensions import db
from models.user import User
from models.activity_log import ActivityLog
from models.workspace import Workspace, WorkspaceMember
from models.customer import Customer
from services.user_service import UserService
from services.workspace_service import WorkspaceService
from services.auth_service import AuthService
from flask import session
from core.auth.enums import UserRole


class TestWorkspaceDeletedGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()
        db.create_all()
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        if TEST_DB_FILE.exists():
            try:
                TEST_DB_FILE.unlink()
            except Exception:
                pass
        if TEST_MEDIA_ROOT.exists():
            shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        cls.app_context.pop()

    def setUp(self):
        db.session.rollback()
        WorkspaceMember.query.delete()
        User.query.delete()
        Workspace.query.delete()
        ActivityLog.query.delete()
        Customer.query.delete()
        db.session.commit()

        # Seed an APPROVAL_OWNER
        self.approval_owner = User(
            username="approval_owner",
            full_name="Approval Owner",
            email="ao@test.com",
            is_active=True,
            role="APPROVAL_OWNER"
        )
        self.approval_owner.set_password("Password123!")
        db.session.add(self.approval_owner)
        db.session.commit()

    def _create_user(self, username, role, email=None, is_active=True, approval_status="active"):
        email = email or f"{username}@test.com"
        user = User(
            username=username,
            email=email,
            role=role,
            full_name=username.title(),
            is_active=is_active,
            approval_status=approval_status
        )
        user.set_password("Password123!")
        db.session.add(user)
        db.session.flush()
        return user

    def _login_as(self, user, workspace_id=None):
        with self.client.session_transaction() as sess:
            sess["auth_user_id"] = user.id
            sess["_enable_workspace_isolation"] = True
            if workspace_id:
                sess["current_workspace_id"] = workspace_id

    def test_is_user_in_workspace_with_deleted_workspace(self):
        owner = self._create_user("owner_1", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        db.session.commit()

        # Active workspace
        self.assertTrue(WorkspaceService.is_user_in_workspace(owner.id, workspace.id))

        # Deleted workspace
        workspace.deleted_at = datetime.utcnow()
        db.session.commit()
        self.assertFalse(WorkspaceService.is_user_in_workspace(owner.id, workspace.id))

    def test_user_workspace_list_source_excludes_deleted(self):
        owner = self._create_user("owner_1", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        db.session.commit()

        # Workspace active: ensure_current_workspace_session auto-selects it
        with app.test_request_context():
            ws = WorkspaceService.ensure_current_workspace_session(owner)
            self.assertIsNotNone(ws)
            self.assertEqual(ws.id, workspace.id)

        # Workspace deleted
        workspace.deleted_at = datetime.utcnow()
        db.session.commit()

        # Re-evaluating workspace session should yield None
        with app.test_request_context():
            session["current_workspace_id"] = workspace.id
            ws_after = WorkspaceService.ensure_current_workspace_session(owner)
            self.assertIsNone(ws_after)

    def test_session_current_workspace_id_deleted_cleared(self):
        owner = self._create_user("owner_1", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        db.session.commit()

        self._login_as(owner, workspace.id)

        with app.test_request_context():
            # Setup session manually
            session["auth_user_id"] = owner.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id

            # Active workspace: get_current_workspace_id returns it
            self.assertEqual(WorkspaceService.get_current_workspace_id(), workspace.id)

            # Manually delete workspace in DB
            workspace.deleted_at = datetime.utcnow()
            db.session.commit()

            # Now helper must pop session and return None
            self.assertIsNone(WorkspaceService.get_current_workspace_id())
            self.assertNotIn("current_workspace_id", session)

    def test_scoped_query_fail_closed_with_deleted_workspace(self):
        owner = self._create_user("owner_1", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        db.session.commit()

        # Create business data
        customer = Customer(name="Customer 1", phone="0912345678", email="cust1@test.com", workspace_id=workspace.id)
        db.session.add(customer)
        db.session.commit()

        self._login_as(owner, workspace.id)

        with app.test_request_context():
            session["auth_user_id"] = owner.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id

            # When workspace is active
            active_custs = WorkspaceService.scoped_query(Customer).all()
            self.assertEqual(len(active_custs), 1)

            # Delete workspace
            workspace.deleted_at = datetime.utcnow()
            db.session.commit()

            # Query should fail closed
            deleted_custs = WorkspaceService.scoped_query(Customer).all()
            self.assertEqual(len(deleted_custs), 0)

    def test_cross_workspace_isolation_unaffected(self):
        owner_a = self._create_user("owner_a", "OWNER")
        workspace_a = WorkspaceService.ensure_workspace_for_approved_owner(owner_a)
        
        owner_b = self._create_user("owner_b", "OWNER")
        workspace_b = WorkspaceService.ensure_workspace_for_approved_owner(owner_b)
        db.session.commit()

        cust_a = Customer(name="Customer A", phone="0912345671", email="a@test.com", workspace_id=workspace_a.id)
        cust_b = Customer(name="Customer B", phone="0912345672", email="b@test.com", workspace_id=workspace_b.id)
        db.session.add_all([cust_a, cust_b])
        db.session.commit()

        # Logged into workspace A, should see customer A but not B
        self._login_as(owner_a, workspace_a.id)
        with app.test_request_context():
            session["auth_user_id"] = owner_a.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace_a.id
            custs = WorkspaceService.scoped_query(Customer).all()
            self.assertEqual(len(custs), 1)
            self.assertEqual(custs[0].id, cust_a.id)

        # Logged into workspace B, should see customer B but not A
        self._login_as(owner_b, workspace_b.id)
        with app.test_request_context():
            session["auth_user_id"] = owner_b.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace_b.id
            custs = WorkspaceService.scoped_query(Customer).all()
            self.assertEqual(len(custs), 1)
            self.assertEqual(custs[0].id, cust_b.id)

    def test_no_hard_deletion(self):
        owner = self._create_user("owner_1", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        db.session.commit()

        # Let's soft delete workspace manually
        workspace.deleted_at = datetime.utcnow()
        db.session.commit()

        # Workspace is still in database (not hard deleted)
        db_ws = db.session.get(Workspace, workspace.id)
        self.assertIsNotNone(db_ws)

    def test_assign_workspace_harden_testing_path(self):
        owner = self._create_user("owner_1", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        db.session.commit()

        # 1. Active workspace: assign_workspace gán workspace_id đúng
        with app.test_request_context():
            session["auth_user_id"] = owner.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id

            customer = Customer(name="Test Cust", phone="0911222333", email="tc@test.com")
            WorkspaceService.assign_workspace(customer)
            self.assertEqual(customer.workspace_id, workspace.id)

        # 2. Deleted workspace: assign_workspace raises 403 / aborts
        workspace.deleted_at = datetime.utcnow()
        db.session.commit()

        with app.test_request_context():
            session["auth_user_id"] = owner.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id

            customer_deleted = Customer(name="Test Cust Deleted", phone="0911222334", email="tcd@test.com")
            from werkzeug.exceptions import Forbidden
            with self.assertRaises(Forbidden):
                WorkspaceService.assign_workspace(customer_deleted)
