import os
import shutil
import tempfile
import unittest
from unittest.mock import patch
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
        db.session.remove()
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

    def test_restore_owner_workspace_success_and_business_data_visible_again(self):
        owner = self._create_user("owner_restore", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        customer = Customer(
            name="Customer Restore",
            phone="0912345690",
            email="restore@test.com",
            workspace_id=workspace.id,
        )
        db.session.add(customer)
        db.session.commit()

        membership = WorkspaceMember.query.filter_by(
            workspace_id=workspace.id,
            user_id=owner.id,
        ).first()
        original_approval_status = owner.approval_status

        UserService.soft_delete_owner_workspace(
            self.approval_owner,
            owner.id,
            reason="Kiểm thử khôi phục",
        )
        restored_owner = UserService.restore_owner_workspace(self.approval_owner, owner.id)

        self.assertEqual(restored_owner.id, owner.id)
        self.assertIsNone(owner.deleted_at)
        self.assertIsNone(owner.deleted_by_id)
        self.assertIsNone(owner.deletion_reason)
        self.assertTrue(owner.is_active)
        self.assertEqual(owner.approval_status, original_approval_status)
        self.assertIsNone(workspace.deleted_at)
        self.assertIsNone(workspace.deleted_by_id)
        self.assertIsNone(workspace.deletion_reason)
        self.assertEqual(membership.status, "active")
        self.assertTrue(WorkspaceService.is_user_in_workspace(owner.id, workspace.id))

        with app.test_request_context():
            session["auth_user_id"] = owner.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id
            self.assertEqual(WorkspaceService.scoped_query(Customer).all(), [customer])

        self.assertIsNotNone(db.session.get(User, owner.id))
        self.assertIsNotNone(db.session.get(Workspace, workspace.id))
        self.assertIsNotNone(db.session.get(Customer, customer.id))
        self.assertNotIn(owner, UserService.list_approval_accounts(status="deleted").items)
        self.assertIn(owner, UserService.list_approval_accounts(status="active").items)

        log = ActivityLog.query.filter_by(action="RESTORE_OWNER_WORKSPACE").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user_id, self.approval_owner.id)
        self.assertEqual(log.reference_id, owner.id)
        self.assertIn(workspace.name, log.description)

    def test_restore_owner_restores_all_deleted_workspaces_without_changing_memberships(self):
        owner = self._create_user("owner_many_restore", "OWNER")
        workspace_1 = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        workspace_2 = Workspace(
            name="Spa Restore 2",
            slug="spa-restore-2",
            status="active",
            created_by_id=owner.id,
        )
        db.session.add(workspace_2)
        db.session.flush()
        membership_2 = WorkspaceMember(
            workspace_id=workspace_2.id,
            user_id=owner.id,
            role="owner",
            status="removed",
        )
        db.session.add(membership_2)
        db.session.commit()

        membership_1 = WorkspaceMember.query.filter_by(
            workspace_id=workspace_1.id,
            user_id=owner.id,
        ).first()
        deleted_at = datetime.utcnow()
        owner.deleted_at = deleted_at
        owner.is_active = False
        workspace_1.deleted_at = deleted_at
        workspace_2.deleted_at = deleted_at
        db.session.commit()

        UserService.restore_owner_workspace(self.approval_owner, owner.id)

        self.assertIsNone(workspace_1.deleted_at)
        self.assertIsNone(workspace_2.deleted_at)
        self.assertEqual(membership_1.status, "active")
        self.assertEqual(membership_2.status, "removed")

    def test_restore_owner_without_deleted_workspace_does_not_create_workspace(self):
        owner = self._create_user("owner_without_ws_restore", "OWNER", is_active=False)
        owner.deleted_at = datetime.utcnow()
        db.session.commit()
        workspace_count = Workspace.query.count()

        UserService.restore_owner_workspace(self.approval_owner, owner.id)

        self.assertIsNone(owner.deleted_at)
        self.assertTrue(owner.is_active)
        self.assertEqual(Workspace.query.count(), workspace_count)
        log = ActivityLog.query.filter_by(action="RESTORE_OWNER_WORKSPACE").first()
        self.assertIn("Không có workspace deleted khớp provenance", log.description)

    def test_restore_owner_keeps_non_active_approval_status_inactive(self):
        for index, approval_status in enumerate(("pending", "rejected", "disabled"), start=1):
            owner = self._create_user(
                f"owner_status_{index}",
                "OWNER",
                is_active=False,
                approval_status=approval_status,
            )
            owner.deleted_at = datetime.utcnow()
            db.session.commit()

            UserService.restore_owner_workspace(self.approval_owner, owner.id)

            self.assertEqual(owner.approval_status, approval_status)
            self.assertFalse(owner.is_active)
            self.assertIsNone(owner.deleted_at)

    def test_restore_owner_service_restrictions(self):
        owner = self._create_user("owner_target_restore", "OWNER")
        regular_owner = self._create_user("owner_actor_restore", "OWNER")
        staff = self._create_user("staff_target_restore", "STAFF")
        another_approval_owner = self._create_user("approval_owner_restore", "APPROVAL_OWNER")
        owner.deleted_at = datetime.utcnow()
        staff.deleted_at = datetime.utcnow()
        another_approval_owner.deleted_at = datetime.utcnow()
        db.session.commit()

        with self.assertRaises(PermissionDeniedException):
            UserService.restore_owner_workspace(regular_owner, owner.id)
        with self.assertRaises(ValidationException):
            UserService.restore_owner_workspace(self.approval_owner, self.approval_owner.id)
        with self.assertRaises(ValidationException):
            UserService.restore_owner_workspace(self.approval_owner, another_approval_owner.id)
        with self.assertRaises(ValidationException) as non_owner_error:
            UserService.restore_owner_workspace(self.approval_owner, staff.id)
        self.assertIn("STAFF/ADMIN", non_owner_error.exception.message)

        owner.deleted_at = None
        db.session.commit()
        with self.assertRaises(ValidationException) as not_deleted_error:
            UserService.restore_owner_workspace(self.approval_owner, owner.id)
        self.assertEqual(
            not_deleted_error.exception.message,
            "Tài khoản owner này chưa bị xóa mềm.",
        )

    def test_restore_owner_route_redirects_and_deleted_tab_ui(self):
        owner = self._create_user("owner_route_restore", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        db.session.commit()
        UserService.soft_delete_owner_workspace(self.approval_owner, owner.id)
        self._login_as(self.approval_owner)
        previous_purge_ui = app.config.get("PERMANENT_PURGE_UI_ENABLED")
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True

        try:
            deleted_page = self.client.get("/approval/accounts?status=deleted")
        finally:
            app.config["PERMANENT_PURGE_UI_ENABLED"] = previous_purge_ui
        self.assertEqual(deleted_page.status_code, 200)
        self.assertIn(b"restore-owner-workspace", deleted_page.data)
        self.assertIn("Khôi phục chủ cơ sở và cơ sở".encode("utf-8"), deleted_page.data)
        self.assertIn("Xóa vĩnh viễn qua yêu cầu".encode("utf-8"), deleted_page.data)

        response = self.client.post(f"/approval/users/{owner.id}/restore-owner-workspace")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/approval/accounts?status=active"))
        db.session.refresh(owner)
        db.session.refresh(workspace)
        self.assertIsNone(owner.deleted_at)
        self.assertIsNone(workspace.deleted_at)

    def test_restore_owner_route_redirects_to_non_active_approval_status(self):
        owner = self._create_user(
            "owner_disabled_restore",
            "OWNER",
            is_active=False,
            approval_status="disabled",
        )
        owner.deleted_at = datetime.utcnow()
        db.session.commit()
        self._login_as(self.approval_owner)

        response = self.client.post(f"/approval/users/{owner.id}/restore-owner-workspace")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/approval/accounts?status=disabled"))
        self.assertFalse(owner.is_active)

    def test_non_approval_owner_route_cannot_restore_owner_workspace(self):
        owner = self._create_user("owner_denied_target", "OWNER")
        actor = self._create_user("staff_denied_actor", "OWNER")
        workspace = Workspace(
            name="Denied Owner Workspace",
            slug="denied-owner-workspace",
            status="active",
        )
        db.session.add(workspace)
        db.session.flush()
        db.session.add(WorkspaceMember(
            workspace_id=workspace.id,
            user_id=actor.id,
            role="owner",
            status="active",
        ))
        owner.deleted_at = datetime.utcnow()
        db.session.commit()
        self._login_as(actor)

        response = self.client.post(f"/approval/users/{owner.id}/restore-owner-workspace")

        self.assertEqual(response.status_code, 403)
        db.session.refresh(owner)
        self.assertIsNotNone(owner.deleted_at)

    def test_restore_owner_rolls_back_owner_workspace_and_log_on_error(self):
        owner = self._create_user("owner_rollback_restore", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        deleted_at = datetime.utcnow()
        owner.deleted_at = deleted_at
        owner.deleted_by_id = self.approval_owner.id
        owner.is_active = False
        workspace.deleted_at = deleted_at
        workspace.deleted_by_id = self.approval_owner.id
        db.session.commit()

        with patch.object(UserService, "_log_user_action", side_effect=RuntimeError("log failed")):
            with self.assertRaises(RuntimeError):
                UserService.restore_owner_workspace(self.approval_owner, owner.id)

        db.session.expire_all()
        persisted_owner = db.session.get(User, owner.id)
        persisted_workspace = db.session.get(Workspace, workspace.id)
        self.assertIsNotNone(persisted_owner.deleted_at)
        self.assertFalse(persisted_owner.is_active)
        self.assertIsNotNone(persisted_workspace.deleted_at)
        self.assertIsNone(ActivityLog.query.filter_by(action="RESTORE_OWNER_WORKSPACE").first())

    def test_restore_account_still_handles_staff_and_owner_method_does_not(self):
        staff = self._create_user("staff_existing_restore", "STAFF")
        UserService.soft_delete_account(self.approval_owner, staff.id)

        with self.assertRaises(ValidationException):
            UserService.restore_owner_workspace(self.approval_owner, staff.id)

        UserService.restore_account(self.approval_owner, staff.id)
        self.assertIsNone(staff.deleted_at)
        self.assertTrue(staff.is_active)

    def test_permanent_delete_remains_unimplemented(self):
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertFalse(any("permanent" in rule and "/approval/" in rule for rule in rules))
