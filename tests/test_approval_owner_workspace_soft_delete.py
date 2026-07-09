import os
import shutil
import tempfile
import unittest
from pathlib import Path
from datetime import datetime

# Setup unique database file for approval soft delete tests
TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_approval_owner_workspace_soft_delete_test.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_media_approval_owner_workspace_soft_delete_test"

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
from core.exceptions import PermissionDeniedException, ValidationException


class TestApprovalOwnerWorkspaceSoftDelete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()
        app.config["CSRF_ENABLED"] = False
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
        app.config["CSRF_ENABLED"] = True
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

    def _login_as(self, user):
        with self.client.session_transaction() as sess:
            sess["auth_user_id"] = user.id
            sess["_enable_workspace_isolation"] = True

    def test_approval_owner_soft_delete_owner_success(self):
        owner = self._create_user("owner_1", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        
        # Add Customer to business data
        customer = Customer(name="Customer 1", phone="0912345678", email="cust1@test.com", workspace_id=workspace.id)
        db.session.add(customer)
        db.session.commit()

        # Check pre-conditions
        self.assertTrue(owner.is_active)
        self.assertEqual(owner.approval_status, "active")
        self.assertIsNone(owner.deleted_at)
        self.assertIsNone(workspace.deleted_at)

        # Call service
        UserService.soft_delete_owner_workspace(self.approval_owner, owner.id, reason="Vi phạm điều khoản")

        # 1. Check OWNER target
        self.assertIsNotNone(owner.deleted_at)
        self.assertEqual(owner.deleted_by_id, self.approval_owner.id)
        self.assertEqual(owner.deletion_reason, "Vi phạm điều khoản")
        self.assertFalse(owner.is_active)
        self.assertEqual(owner.approval_status, "active")  # Approval status unchanged

        # 2. Check Workspace owned target
        self.assertIsNotNone(workspace.deleted_at)
        self.assertEqual(workspace.deleted_by_id, self.approval_owner.id)
        self.assertEqual(workspace.deletion_reason, "Vi phạm điều khoản")

        # 3. Check WorkspaceMember status not touched
        membership = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=owner.id).first()
        self.assertEqual(membership.status, "active")

        # 4. Check Business data not soft/hard deleted
        db.session.refresh(customer)
        self.assertIsNotNone(customer)
        # customer doesn't have deleted_at set by this task
        self.assertIsNone(customer.deleted_at)

        # 5. Check guards check
        self.assertFalse(WorkspaceService.is_user_in_workspace(owner.id, workspace.id))

        with app.test_request_context():
            session["auth_user_id"] = owner.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id
            custs = WorkspaceService.scoped_query(Customer).all()
            self.assertEqual(len(custs), 0)

    def test_soft_delete_owner_with_multiple_workspaces(self):
        owner = self._create_user("owner_2", "OWNER")
        workspace_1 = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        
        # Manually create another active workspace membership for same owner
        workspace_2 = Workspace(name="Spa Chi Nhánh 2", slug="spa-branch-2", status="active", created_by_id=owner.id)
        db.session.add(workspace_2)
        db.session.flush()
        db.session.add(WorkspaceMember(workspace_id=workspace_2.id, user_id=owner.id, role="owner", status="active"))
        db.session.commit()

        # Verify both active
        self.assertIsNone(workspace_1.deleted_at)
        self.assertIsNone(workspace_2.deleted_at)

        # Call soft delete
        UserService.soft_delete_owner_workspace(self.approval_owner, owner.id, reason="Xóa chuỗi chi nhánh")

        # Verify both soft-deleted
        self.assertIsNotNone(workspace_1.deleted_at)
        self.assertIsNotNone(workspace_2.deleted_at)

    def test_soft_delete_owner_without_workspaces(self):
        owner = self._create_user("owner_3", "OWNER")
        db.session.commit()

        # Call soft delete
        UserService.soft_delete_owner_workspace(self.approval_owner, owner.id, reason="Không có workspace")

        # Verify owner soft-deleted
        self.assertIsNotNone(owner.deleted_at)
        self.assertFalse(owner.is_active)

    def test_post_route_soft_delete_owner_workspace(self):
        owner = self._create_user("owner_4", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        db.session.commit()

        self._login_as(self.approval_owner)

        # POST call to route
        response = self.client.post(
            f"/approval/users/{owner.id}/soft-delete-owner-workspace",
            data={"reason": "Lý do route test"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/approval/accounts?status=deleted"))

        # Verify soft-delete completed
        db.session.refresh(owner)
        db.session.refresh(workspace)
        self.assertIsNotNone(owner.deleted_at)
        self.assertIsNotNone(workspace.deleted_at)

    def test_role_restrictions_on_owner_workspace_soft_delete(self):
        owner = self._create_user("owner_5", "OWNER")
        db.session.commit()

        regular_owner = self._create_user("owner_other", "OWNER")
        staff = self._create_user("staff_1", "STAFF")
        
        # 1. Non-approval owner cannot call service
        with self.assertRaises(PermissionDeniedException):
            UserService.soft_delete_owner_workspace(regular_owner, owner.id)

        with self.assertRaises(PermissionDeniedException):
            UserService.soft_delete_owner_workspace(staff, owner.id)

        # 2. Cannot self-delete APPROVAL_OWNER
        with self.assertRaises(ValidationException):
            UserService.soft_delete_owner_workspace(self.approval_owner, self.approval_owner.id)

        # 3. Cannot delete another APPROVAL_OWNER
        another_ao = self._create_user("ao_2", "APPROVAL_OWNER")
        db.session.commit()
        with self.assertRaises(ValidationException):
            UserService.soft_delete_owner_workspace(self.approval_owner, another_ao.id)

        # 4. Cannot delete already deleted OWNER
        owner_deleted = self._create_user("owner_del", "OWNER")
        owner_deleted.deleted_at = datetime.utcnow()
        db.session.commit()
        with self.assertRaises(ValidationException):
            UserService.soft_delete_owner_workspace(self.approval_owner, owner_deleted.id)

    def test_list_approval_accounts_filtering(self):
        owner = self._create_user("owner_6", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        db.session.commit()

        # Before deletion: OWNER in active listing
        active_list = UserService.list_approval_accounts(status="active").items
        self.assertIn(owner, active_list)

        # Call soft delete
        UserService.soft_delete_owner_workspace(self.approval_owner, owner.id)

        # After deletion: OWNER not in active listing, but in deleted listing
        active_list_after = UserService.list_approval_accounts(status="active").items
        deleted_list = UserService.list_approval_accounts(status="deleted").items

        self.assertNotIn(owner, active_list_after)
        self.assertIn(owner, deleted_list)
