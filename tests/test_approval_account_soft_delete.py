"""
tests/test_approval_account_soft_delete.py
==========================================
Tests for TASK 6.5.16 — Approval Portal Account Soft Delete for Staff/Admin.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from datetime import datetime

# isolated test DB
TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_approval_soft_delete.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_approval_soft_delete_media"

for _p in (TEST_DB_FILE,):
    if _p.exists():
        try:
            _p.unlink()
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
from core.auth.constants import AUTH_SESSION_KEY
from core.auth.enums import UserRole
from core.exceptions import ValidationException, PermissionDeniedException
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from models.activity_log import ActivityLog
from services.user_service import UserService
from services.auth_service import AuthService


class TestApprovalAccountSoftDelete(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.config["CSRF_ENABLED"] = False
        cls.app_context = app.app_context()
        cls.app_context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        app.config["CSRF_ENABLED"] = True
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
        db.session.remove()
        db.session.rollback()
        ActivityLog.query.delete()
        WorkspaceMember.query.delete()
        Workspace.query.delete()
        User.query.delete()
        db.session.commit()
        self.client = app.test_client()

    def _login_as(self, user):
        with self.client.session_transaction() as sess:
            sess[AUTH_SESSION_KEY] = user.id

    def _create_user(self, username, role, is_active=True, approval_status="active"):
        user = User(
            username=username,
            full_name=f"Full Name {username}",
            role=role.value if hasattr(role, 'value') else role,
            is_active=is_active,
            approval_status=approval_status
        )
        user.set_password("Secret123!")
        db.session.add(user)
        db.session.commit()
        return user

    def test_approval_owner_can_soft_delete_staff_and_admin(self):
        approver = self._create_user("approver", UserRole.APPROVAL_OWNER)
        staff = self._create_user("staff_to_del", UserRole.STAFF)
        admin = self._create_user("admin_to_del", UserRole.ADMIN)

        # Test service: soft delete staff
        UserService.soft_delete_account(actor=approver, user_id=staff.id, reason="Lý do xóa nhân viên")

        # Verify database fields
        deleted_staff = User.query.get(staff.id)
        self.assertIsNotNone(deleted_staff.deleted_at)
        self.assertEqual(deleted_staff.deleted_by_id, approver.id)
        self.assertEqual(deleted_staff.deletion_reason, "Lý do xóa nhân viên")
        self.assertFalse(deleted_staff.is_active)
        self.assertEqual(deleted_staff.approval_status, "active") # approval_status is preserved
        self.assertFalse(deleted_staff.can_access_app)

        # Test service: soft delete admin
        UserService.soft_delete_account(actor=approver, user_id=admin.id, reason="Lý do xóa admin")

        deleted_admin = User.query.get(admin.id)
        self.assertIsNotNone(deleted_admin.deleted_at)
        self.assertEqual(deleted_admin.deleted_by_id, approver.id)
        self.assertEqual(deleted_admin.deletion_reason, "Lý do xóa admin")
        self.assertFalse(deleted_admin.is_active)
        self.assertFalse(deleted_admin.can_access_app)

    def test_soft_deleted_user_not_hard_deleted(self):
        approver = self._create_user("approver", UserRole.APPROVAL_OWNER)
        staff = self._create_user("staff_to_del", UserRole.STAFF)

        UserService.soft_delete_account(actor=approver, user_id=staff.id)

        # Verify still in DB
        db_user = db.session.get(User, staff.id)
        self.assertIsNotNone(db_user)
        self.assertIsNotNone(db_user.deleted_at)

    def test_soft_deleted_user_excluded_from_active_list_but_present_in_deleted_list(self):
        approver = self._create_user("approver", UserRole.APPROVAL_OWNER)
        staff_active = self._create_user("staff_active", UserRole.STAFF)
        staff_del = self._create_user("staff_del", UserRole.STAFF)

        UserService.soft_delete_account(actor=approver, user_id=staff_del.id)

        # List active accounts
        active_res = UserService.list_approval_accounts(status="active")
        active_ids = [u.id for u in active_res.items]
        self.assertIn(staff_active.id, active_ids)
        self.assertNotIn(staff_del.id, active_ids)

        # List deleted accounts
        deleted_res = UserService.list_approval_accounts(status="deleted")
        deleted_ids = [u.id for u in deleted_res.items]
        self.assertIn(staff_del.id, deleted_ids)
        self.assertNotIn(staff_active.id, deleted_ids)

    def test_cannot_delete_approval_owner_or_self(self):
        approver = self._create_user("approver", UserRole.APPROVAL_OWNER)
        another_approver = self._create_user("approver2", UserRole.APPROVAL_OWNER)

        # Self-deletion restriction
        with self.assertRaises(ValidationException) as context:
            UserService.soft_delete_account(actor=approver, user_id=approver.id)
        self.assertIn("Không thể tự xóa chính mình", context.exception.message)

        # Delete another approval owner restriction
        with self.assertRaises(ValidationException) as context:
            UserService.soft_delete_account(actor=approver, user_id=another_approver.id)
        self.assertIn("Không thể xóa tài khoản quản trị hệ thống", context.exception.message)

    def test_cannot_delete_owner_in_this_step(self):
        approver = self._create_user("approver", UserRole.APPROVAL_OWNER)
        owner = self._create_user("owner_user", UserRole.OWNER)

        with self.assertRaises(ValidationException) as context:
            UserService.soft_delete_account(actor=approver, user_id=owner.id)
        self.assertIn("Xóa owner sẽ được xử lý ở bước workspace lifecycle riêng", context.exception.message)

    def test_cannot_delete_already_soft_deleted_user(self):
        approver = self._create_user("approver", UserRole.APPROVAL_OWNER)
        staff = self._create_user("staff_to_del", UserRole.STAFF)

        UserService.soft_delete_account(actor=approver, user_id=staff.id)

        with self.assertRaises(ValidationException) as context:
            UserService.soft_delete_account(actor=approver, user_id=staff.id)
        self.assertIn("Tài khoản này đã bị xóa mềm trước đó", context.exception.message)

    def test_non_approval_owner_cannot_call_service_soft_delete(self):
        staff_actor = self._create_user("staff_actor", UserRole.STAFF)
        staff_target = self._create_user("staff_target", UserRole.STAFF)

        with self.assertRaises(PermissionDeniedException):
            UserService.soft_delete_account(actor=staff_actor, user_id=staff_target.id)

    def test_activity_log_recorded_on_soft_delete(self):
        approver = self._create_user("approver", UserRole.APPROVAL_OWNER)
        staff = self._create_user("staff_to_del", UserRole.STAFF)

        UserService.soft_delete_account(actor=approver, user_id=staff.id, reason="Lý do xóa")

        log = ActivityLog.query.filter_by(action="SOFT_DELETE_ACCOUNT").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user_id, approver.id)
        self.assertEqual(log.reference_id, staff.id)
        self.assertIn("đã xóa mềm tài khoản staff_to_del", log.description)

    def test_soft_delete_route_execution_and_access_block(self):
        approver = self._create_user("approver", UserRole.APPROVAL_OWNER)
        staff = self._create_user("staff_to_del", UserRole.STAFF)

        # Login as approver and call route
        self._login_as(approver)
        resp = self.client.post(
            f"/approval/users/{staff.id}/soft-delete",
            data={"reason": "Lý do qua HTTP route"}
        )
        self.assertEqual(resp.status_code, 302) # Redirect to deleted list
        self.assertIn("/approval/accounts?status=deleted", resp.headers["Location"])

        # Check DB updated
        db_user = User.query.get(staff.id)
        self.assertIsNotNone(db_user.deleted_at)
        self.assertEqual(db_user.deletion_reason, "Lý do qua HTTP route")

        # Try to login as soft-deleted user (should fail because can_access_app is False)
        # Login is checked by looking at AuthService
        from flask import session
        with app.test_request_context():
            session[AUTH_SESSION_KEY] = db_user.id
            self.assertFalse(db_user.can_access_app)
            self.assertIsNone(AuthService.get_current_active_user())

    def test_deleted_tab_routing_and_views(self):
        approver = self._create_user("approver", UserRole.APPROVAL_OWNER)
        staff_del = self._create_user("staff_del", UserRole.STAFF)
        UserService.soft_delete_account(actor=approver, user_id=staff_del.id, reason="Reason deleted")

        self._login_as(approver)

        # 1. GET /approval/accounts?status=deleted renders deleted status, not falling back to pending
        resp = self.client.get("/approval/accounts?status=deleted")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Tài khoản đã xóa mềm", html)
        self.assertIn("staff_del", html)

        # 2. Check pending, active, rejected, disabled still work as before
        for st in ["pending", "active", "rejected", "disabled"]:
            r = self.client.get(f"/approval/accounts?status={st}")
            self.assertEqual(r.status_code, 200)
