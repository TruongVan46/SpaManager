import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Setup unique database file for regression tests
TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_ws_context_regression_test.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_media_ws_context_regression_test"

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


class TestWorkspaceContextRegression(unittest.TestCase):
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

    def _create_user(self, username, role, email=None, is_active=True, auth_provider="local", approval_status="active", full_name=None):
        email = email or f"{username}@test.com"
        full_name = full_name or username.title()
        user = User(
            username=username,
            email=email,
            role=role,
            full_name=full_name,
            is_active=is_active,
            auth_provider=auth_provider,
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

    def test_owner_user_page_shows_staff_created_in_same_workspace(self):
        owner = self._create_user("owner_a", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        staff = self._create_user("staff_a", "STAFF")
        WorkspaceService.add_member_for_user(workspace.id, staff, "STAFF")
        db.session.commit()

        staff_b_user = self._create_user("staff_b", "STAFF")
        db.session.commit()

        with app.test_request_context():
            session["auth_user_id"] = owner.id
            session["current_workspace_id"] = workspace.id
            session["_enable_workspace_isolation"] = True
            
            # Retrieve users scoped to workspace
            users = UserService.search_paginated().items
            usernames = [u.username for u in users]
            self.assertIn("staff_a", usernames)
            self.assertNotIn("staff_b", usernames)

    def test_staff_created_by_owner_logs_into_owner_workspace(self):
        owner = self._create_user("owner_a", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        db.session.commit()

        with app.test_request_context():
            session["auth_user_id"] = owner.id
            session["current_workspace_id"] = workspace.id
            session["_enable_workspace_isolation"] = True
            
            # Owner A creates staff A via UserService
            staff = UserService.create_user(
                actor=owner,
                username="staff_a",
                full_name="Staff A",
                password="Password123!",
                role="STAFF",
                is_active=True
            )
            
        db.session.commit()

        # Staff A logs in
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = staff.id
            WorkspaceService.ensure_current_workspace_session(staff)
            self.assertEqual(session.get("current_workspace_id"), workspace.id)

    def test_legacy_local_owner_with_workspace_can_access_statistics(self):
        owner = self._create_user("owner_local", "OWNER", auth_provider="local")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        db.session.commit()

        self._login_as(owner)
        resp = self.client.get('/statistics')
        self.assertEqual(resp.status_code, 200)

    def test_owner_without_workspace_gets_safe_repair_or_clear_error(self):
        owner = self._create_user("owner_legacy", "OWNER", auth_provider="local")
        db.session.commit()

        # Verify no workspace exists initially
        owner_membership = WorkspaceMember.query.filter_by(user_id=owner.id).first()
        self.assertIsNone(owner_membership)

        # Login and verify workspace is auto-provisioned/repaired via request client flow
        self._login_as(owner)
        resp = self.client.get('/statistics')
        self.assertEqual(resp.status_code, 200)

        # Check DB to confirm workspace and membership are created
        owner_membership = WorkspaceMember.query.filter_by(user_id=owner.id, role="owner", status="active").first()
        self.assertIsNotNone(owner_membership)
        workspace = owner_membership.workspace
        self.assertIsNotNone(workspace)
        self.assertEqual(workspace.name, "Spa của Owner_Legacy")

    def test_disabling_user_does_not_break_unrelated_owner_memberships(self):
        owner_a = self._create_user("owner_a", "OWNER")
        workspace_a = WorkspaceService.ensure_workspace_for_approved_owner(owner_a)
        staff_a = self._create_user("staff_a", "STAFF")
        WorkspaceService.add_member_for_user(workspace_a.id, staff_a, "STAFF")

        owner_b = self._create_user("owner_b", "OWNER")
        workspace_b = WorkspaceService.ensure_workspace_for_approved_owner(owner_b)
        staff_b = self._create_user("staff_b", "STAFF")
        WorkspaceService.add_member_for_user(workspace_b.id, staff_b, "STAFF")
        db.session.commit()

        # Disable staff_a
        UserService.disable_user(actor=self.approval_owner, user_id=staff_a.id)
        db.session.commit()

        # Assert staff_a is inactive
        m_a = WorkspaceMember.query.filter_by(user_id=staff_a.id).first()
        self.assertEqual(m_a.status, "inactive")

        # Assert staff_b and owners are still active
        m_b = WorkspaceMember.query.filter_by(user_id=staff_b.id).first()
        self.assertEqual(m_b.status, "active")
        m_owner_a = WorkspaceMember.query.filter_by(user_id=owner_a.id).first()
        self.assertEqual(m_owner_a.status, "active")

    def test_approval_portal_grouping_does_not_change_memberships(self):
        owner_a = self._create_user("owner_a", "OWNER")
        workspace_a = WorkspaceService.ensure_workspace_for_approved_owner(owner_a)
        db.session.commit()

        # Check membership status initially
        m_before = WorkspaceMember.query.filter_by(user_id=owner_a.id).first()
        self.assertEqual(m_before.status, "active")

        # List approval accounts (simulates loading portal tabs)
        UserService.list_approval_accounts()

        # Verify no status mutation occurred
        m_after = WorkspaceMember.query.filter_by(user_id=owner_a.id).first()
        self.assertEqual(m_after.status, "active")

    def test_enabling_disabled_staff_reactivates_membership(self):
        owner = self._create_user("owner_a", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        staff = self._create_user("staff_a", "STAFF")
        WorkspaceService.add_member_for_user(workspace.id, staff, "STAFF")
        db.session.commit()

        # Check membership status is active initially
        m = WorkspaceMember.query.filter_by(user_id=staff.id).first()
        self.assertEqual(m.status, "active")

        # Disable staff
        UserService.disable_user(actor=self.approval_owner, user_id=staff.id)
        db.session.commit()
        
        # Membership must be inactive
        m = WorkspaceMember.query.filter_by(user_id=staff.id).first()
        self.assertEqual(m.status, "inactive")

        # Enable staff again
        UserService.enable_user(actor=self.approval_owner, user_id=staff.id)
        db.session.commit()

        # Membership must be active again!
        m = WorkspaceMember.query.filter_by(user_id=staff.id).first()
        self.assertEqual(m.status, "active")

    def test_local_owner_grouping_in_approval_portal(self):
        owner = self._create_user("owner_local", "OWNER", auth_provider="local")
        db.session.commit()

        # List approval accounts
        pagination = UserService.list_approval_accounts(status="active")
        
        # Retrieve the owner from pagination
        owner_item = [u for u in pagination.items if u.username == "owner_local"][0]
        # Must be grouped under owner_registration (Group 1), not owner_created_member (Group 2)
        self.assertEqual(owner_item.group_type, "owner_registration")

    def test_legacy_owner_created_staff_without_membership_is_repaired_if_creator_known(self):
        # Create Owner A + Workspace A
        owner_a = self._create_user("owner_a", "OWNER")
        workspace_a = WorkspaceService.ensure_workspace_for_approved_owner(owner_a)

        # Create Staff legacy without membership
        staff = self._create_user("staff_legacy", "STAFF")

        # Verify no membership exists initially
        m = WorkspaceMember.query.filter_by(user_id=staff.id).first()
        self.assertIsNone(m)

        # Log trace indicating owner_a created staff
        from models.activity_log import ActivityLog
        log = ActivityLog(
            module="Users",
            action="CREATE_USER",
            user_id=owner_a.id,
            reference_id=staff.id,
            description="Created user",
            severity="INFO"
        )
        db.session.add(log)
        db.session.commit()

        # Login as owner_a (which triggers repair in /users)
        self._login_as(owner_a)
        resp = self.client.get('/users')
        self.assertEqual(resp.status_code, 200)

        # Verify WorkspaceMember is created and active
        m = WorkspaceMember.query.filter_by(user_id=staff.id).first()
        self.assertIsNotNone(m)
        self.assertEqual(m.workspace_id, workspace_a.id)
        self.assertEqual(m.status, "active")

        # Staff logs in -> auto-selects workspace_a
        self._login_as(staff)
        with self.client.session_transaction() as sess:
            # Clear workspace session to check auto-select
            sess.pop("current_workspace_id", None)

        # Try to ensure current workspace session for staff
        with app.test_request_context():
            from flask import session
            session["auth_user_id"] = staff.id
            ws = WorkspaceService.ensure_current_workspace_session(staff)
            self.assertIsNotNone(ws)
            self.assertEqual(ws.id, workspace_a.id)

    def test_orphan_staff_without_creator_is_not_auto_linked(self):
        owner_a = self._create_user("owner_a", "OWNER")
        WorkspaceService.ensure_workspace_for_approved_owner(owner_a)

        staff = self._create_user("staff_orphan", "STAFF")
        db.session.commit()

        # Repair call
        WorkspaceService.repair_legacy_owner_created_memberships(owner_a)

        # Verify no membership was created
        m = WorkspaceMember.query.filter_by(user_id=staff.id).first()
        self.assertIsNone(m)

    def test_orphan_staff_with_multiple_possible_owners_is_not_auto_linked(self):
        owner_a = self._create_user("owner_a", "OWNER")
        WorkspaceService.ensure_workspace_for_approved_owner(owner_a)

        owner_b = self._create_user("owner_b", "OWNER")
        WorkspaceService.ensure_workspace_for_approved_owner(owner_b)

        staff = self._create_user("staff_ambig", "STAFF")
        db.session.commit()

        # Only owner_a is the creator according to ActivityLog
        from models.activity_log import ActivityLog
        log = ActivityLog(
            module="Users",
            action="CREATE_USER",
            user_id=owner_a.id,
            reference_id=staff.id,
            description="Created user",
            severity="INFO"
        )
        db.session.add(log)
        db.session.commit()

        # Repair call for owner_b
        WorkspaceService.repair_legacy_owner_created_memberships(owner_b)

        # Verify no membership in owner_b workspace
        m = WorkspaceMember.query.filter_by(user_id=staff.id).first()
        self.assertIsNone(m)

    def test_repair_does_not_cross_workspace(self):
        owner_a = self._create_user("owner_a", "OWNER")
        workspace_a = WorkspaceService.ensure_workspace_for_approved_owner(owner_a)

        owner_b = self._create_user("owner_b", "OWNER")
        WorkspaceService.ensure_workspace_for_approved_owner(owner_b)

        staff_a = self._create_user("staff_a", "STAFF")

        from models.activity_log import ActivityLog
        log = ActivityLog(
            module="Users",
            action="CREATE_USER",
            user_id=owner_a.id,
            reference_id=staff_a.id,
            description="Created user",
            severity="INFO"
        )
        db.session.add(log)
        db.session.commit()

        # Repair call for owner_b
        WorkspaceService.repair_legacy_owner_created_memberships(owner_b)

        # Verify staff_a is not linked to owner_b
        m_b = WorkspaceMember.query.filter_by(user_id=staff_a.id).first()
        self.assertIsNone(m_b)

        # Repair call for owner_a
        WorkspaceService.repair_legacy_owner_created_memberships(owner_a)

        # Verify staff_a is correctly linked to owner_a
        m_a = WorkspaceMember.query.filter_by(user_id=staff_a.id).first()
        self.assertIsNotNone(m_a)
        self.assertEqual(m_a.workspace_id, workspace_a.id)
