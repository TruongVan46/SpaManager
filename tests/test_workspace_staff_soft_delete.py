import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Setup unique database file for soft delete tests
TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_staff_soft_delete_test.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_media_staff_soft_delete_test"

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
from services.user_service import UserService
from services.workspace_service import WorkspaceService
from flask import session
from core.auth.enums import UserRole


class TestWorkspaceStaffSoftDelete(unittest.TestCase):
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

    def test_soft_delete_and_restore_workflow(self):
        # 1. Create OWNER + workspace + STAFF
        owner = self._create_user("owner_1", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        
        staff = self._create_user("staff_1", "STAFF")
        WorkspaceService.add_member_for_user(workspace.id, staff, "STAFF")
        db.session.commit()

        # Log in as owner
        self._login_as(owner, workspace.id)

        with app.test_request_context():
            session["auth_user_id"] = owner.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id

            # Verify staff is in active users list
            active_users = UserService.search_paginated().items
            self.assertIn(staff.id, [u.id for u in active_users])

            # Verify staff is active in workspace
            self.assertTrue(WorkspaceService.is_user_in_workspace(staff.id, workspace.id))

            # OWNER soft deletes STAFF (Test 1 & 10: soft delete + activity log)
            UserService.soft_delete_user(actor=owner, user_id=staff.id, reason="Performance issues")
            
            # Verify STAFF is NOT hard deleted from DB (Test 9)
            db_user = User.query.get(staff.id)
            self.assertIsNotNone(db_user)

            # Verify membership status changed
            membership = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=staff.id).first()
            self.assertEqual(membership.status, "removed")
            self.assertEqual(membership.removal_reason, "Performance issues")
            self.assertEqual(membership.removed_by_id, owner.id)
            self.assertIsNotNone(membership.removed_at)

            # Verify STAFF is active globally (we no longer disable globally on soft-delete)
            self.assertTrue(db_user.is_active)

            # Verify STAFF is not in active workspace query anymore (Test 3)
            self.assertFalse(WorkspaceService.is_user_in_workspace(staff.id, workspace.id))

            # Verify STAFF does not appear in active users, but appears in removed users (Test 2)
            active_users = UserService.search_paginated().items
            self.assertNotIn(staff.id, [u.id for u in active_users])

            removed_users = UserService.search_removed_paginated().items
            self.assertIn(staff.id, [u.id for u in removed_users])
            self.assertEqual(removed_users[0].removal_reason, "Performance issues")

            # Verify Activity Log for soft delete (Test 10)
            logs = ActivityLog.query.filter_by(action="REMOVE_USER").all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].reference_id, staff.id)

            # OWNER restores STAFF (Test 4 & 5)
            UserService.restore_user(actor=owner, user_id=staff.id)

            # Verify membership restored to active
            membership = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=staff.id).first()
            self.assertEqual(membership.status, "active")
            self.assertIsNone(membership.removed_at)
            self.assertIsNone(membership.removed_by_id)

            # Verify STAFF is active globally again
            self.assertTrue(staff.is_active)

            # Verify STAFF back in active users, gone from removed (Test 5)
            active_users = UserService.search_paginated().items
            self.assertIn(staff.id, [u.id for u in active_users])

            removed_users = UserService.search_removed_paginated().items
            self.assertNotIn(staff.id, [u.id for u in removed_users])

            # Verify Activity Log for restore (Test 10)
            logs = ActivityLog.query.filter_by(action="RESTORE_USER").all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].reference_id, staff.id)

    def test_soft_delete_restrictions(self):
        # Create OWNER + workspace + STAFF + another OWNER/workspace
        owner_1 = self._create_user("owner_1", "OWNER")
        workspace_1 = WorkspaceService.ensure_workspace_for_approved_owner(owner_1)
        staff_1 = self._create_user("staff_1", "STAFF")
        WorkspaceService.add_member_for_user(workspace_1.id, staff_1, "STAFF")

        owner_2 = self._create_user("owner_2", "OWNER")
        workspace_2 = WorkspaceService.ensure_workspace_for_approved_owner(owner_2)
        staff_2 = self._create_user("staff_2", "STAFF")
        WorkspaceService.add_member_for_user(workspace_2.id, staff_2, "STAFF")

        db.session.commit()

        # Log in as owner_1
        self._login_as(owner_1, workspace_1.id)

        with app.test_request_context():
            session["auth_user_id"] = owner_1.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace_1.id

            # 1. OWNER cannot delete themselves (Test 6)
            with self.assertRaises(Exception):
                UserService.soft_delete_user(actor=owner_1, user_id=owner_1.id)

            # 2. OWNER cannot delete another OWNER (Test 7)
            with self.assertRaises(Exception):
                UserService.soft_delete_user(actor=owner_1, user_id=owner_2.id)

            # 3. OWNER cannot delete APPROVAL_OWNER (Test 7)
            with self.assertRaises(Exception):
                UserService.soft_delete_user(actor=owner_1, user_id=self.approval_owner.id)

            # 4. OWNER cannot delete a user from another workspace (Test 8)
            with self.assertRaises(Exception):
                UserService.soft_delete_user(actor=owner_1, user_id=staff_2.id)

            # 5. Non-OWNER (STAFF) cannot delete anyone (Test 5 / permissions)
            with self.assertRaises(Exception):
                UserService.soft_delete_user(actor=staff_1, user_id=staff_1.id)

            # 6. OWNER cannot restore a user from another workspace (Test 11)
            # First, owner_2 soft deletes staff_2 in workspace_2
            with app.test_request_context():
                session["auth_user_id"] = owner_2.id
                session["_enable_workspace_isolation"] = True
                session["current_workspace_id"] = workspace_2.id
                UserService.soft_delete_user(actor=owner_2, user_id=staff_2.id)

            # Then, owner_1 tries to restore staff_2 in workspace_1 context
            with self.assertRaises(Exception):
                UserService.restore_user(actor=owner_1, user_id=staff_2.id)

            # 7. Non-OWNER (STAFF) cannot restore anyone (Test 11)
            with self.assertRaises(Exception):
                UserService.restore_user(actor=staff_1, user_id=staff_1.id)

            # 8. Removed users list must be workspace scoped, not leak (Test 12)
            # owner_1 searching removed users in workspace_1 should NOT see staff_2 (who is removed from workspace_2)
            removed_ws1 = UserService.search_removed_paginated().items
            self.assertNotIn(staff_2.id, [u.id for u in removed_ws1])

    def test_restore_does_not_activate_disabled_user(self):
        # 1. Create OWNER + workspace + STAFF
        owner = self._create_user("owner_1", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        
        staff = self._create_user("staff_1", "STAFF", is_active=True)
        WorkspaceService.add_member_for_user(workspace.id, staff, "STAFF")
        db.session.commit()

        # Log in as owner
        self._login_as(owner, workspace.id)

        with app.test_request_context():
            session["auth_user_id"] = owner.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id

            # OWNER soft deletes STAFF
            UserService.soft_delete_user(actor=owner, user_id=staff.id, reason="Performance")
            
            # Now, simulate that the staff account gets disabled via another flow (e.g. manually or approval)
            staff.is_active = False
            staff.approval_status = "disabled"
            db.session.commit()

            # OWNER restores STAFF
            UserService.restore_user(actor=owner, user_id=staff.id)

            # Verify membership status is active
            membership = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=staff.id).first()
            self.assertEqual(membership.status, "active")

            # Verify that user.is_active is STILL False (not automatically unlocked)
            self.assertFalse(staff.is_active)
            self.assertEqual(staff.approval_status, "disabled")

    def test_workspace_soft_delete_and_restore_no_global_active_side_effects(self):
        owner = self._create_user("owner_1", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)

        # 1. Staff starting with is_active = False (disabled)
        staff_inactive = self._create_user("staff_inactive", "STAFF", is_active=False, approval_status="disabled")
        WorkspaceService.add_member_for_user(workspace.id, staff_inactive, "STAFF")
        db.session.commit()

        self._login_as(owner, workspace.id)
        with app.test_request_context():
            session["auth_user_id"] = owner.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id

            # Soft delete inactive staff
            UserService.soft_delete_user(actor=owner, user_id=staff_inactive.id)
            # Global is_active must remain False
            db_user_inactive = User.query.get(staff_inactive.id)
            self.assertFalse(db_user_inactive.is_active)

            # Restore inactive staff
            UserService.restore_user(actor=owner, user_id=staff_inactive.id)
            # Global is_active must remain False
            self.assertFalse(db_user_inactive.is_active)

        # 2. Staff starting with is_active = True (active)
        staff_active = self._create_user("staff_active", "STAFF", is_active=True, approval_status="active")
        WorkspaceService.add_member_for_user(workspace.id, staff_active, "STAFF")
        db.session.commit()

        with app.test_request_context():
            session["auth_user_id"] = owner.id
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id

            # Soft delete active staff
            UserService.soft_delete_user(actor=owner, user_id=staff_active.id)
            # Global is_active must remain True
            db_user_active = User.query.get(staff_active.id)
            self.assertTrue(db_user_active.is_active)

            # Restore active staff
            UserService.restore_user(actor=owner, user_id=staff_active.id)
            # Global is_active must remain True
            self.assertTrue(db_user_active.is_active)
