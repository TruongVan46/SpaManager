"""
tests/test_approval_portal_management.py
========================================
Tests for Task 6.5.10 — Approval Portal account management.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

# ── isolated test DB ────────────────────────────────────────────────────────
TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_approval_portal.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_approval_portal_media"

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
from flask import session
from core.auth.constants import AUTH_SESSION_KEY
from core.auth.enums import UserRole
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from core.auth.google_oauth import create_or_route_google_pending_user
from services.user_service import UserService


class TestApprovalPortalManagement(unittest.TestCase):

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
        WorkspaceMember.query.delete()
        Workspace.query.delete()
        User.query.delete()
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.session.rollback()

    def _login_as(self, user):
        with self.client.session_transaction() as sess:
            sess[AUTH_SESSION_KEY] = user.id

    def _create_approval_owner(self):
        owner = User(
            username="approver",
            full_name="Quản trị duyệt",
            role=UserRole.APPROVAL_OWNER.value,
            is_active=True,
            approval_status="active"
        )
        owner.set_password("Approver123!")
        db.session.add(owner)
        db.session.commit()
        return owner

    def test_approval_owner_sees_pending_active_rejected_disabled_accounts(self):
        approver = self._create_approval_owner()
        
        # Create users for each status
        user_pending = User(username="user_pending", full_name="Pending User", role=UserRole.STAFF.value, is_active=False, approval_status="pending")
        user_pending.set_password("Password123!")
        user_active = User(username="user_active", full_name="Active User", role=UserRole.STAFF.value, is_active=True, approval_status="active")
        user_active.set_password("Password123!")
        user_rejected = User(username="user_rejected", full_name="Rejected User", role=UserRole.STAFF.value, is_active=False, approval_status="rejected")
        user_rejected.set_password("Password123!")
        user_disabled = User(username="user_disabled", full_name="Disabled User", role=UserRole.STAFF.value, is_active=False, approval_status="disabled")
        user_disabled.set_password("Password123!")
        
        db.session.add_all([user_pending, user_active, user_rejected, user_disabled])
        db.session.commit()

        self._login_as(approver)

        # Check pending tab
        resp = self.client.get('/approval/accounts?status=pending')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("user_pending", html)
        self.assertNotIn("user_active", html)
        self.assertNotIn("approver", html)

        # Check active tab
        resp = self.client.get('/approval/accounts?status=active')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("user_active", html)
        self.assertNotIn("user_pending", html)

        # Check rejected tab
        resp = self.client.get('/approval/accounts?status=rejected')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("user_rejected", html)

        # Check disabled tab
        resp = self.client.get('/approval/accounts?status=disabled')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("user_disabled", html)

    def test_pending_user_can_be_rejected_and_stays_manageable(self):
        approver = self._create_approval_owner()
        user = User(username="user_pending", full_name="Pending User", role=UserRole.STAFF.value, is_active=False, approval_status="pending")
        user.set_password("Password123!")
        db.session.add(user)
        db.session.commit()

        self._login_as(approver)

        resp = self.client.post(f'/approval/users/{user.id}/reject')
        self.assertEqual(resp.status_code, 302)

        db.session.refresh(user)
        self.assertEqual(user.approval_status, 'rejected')
        self.assertFalse(user.is_active)

        # Stays manageable: verify it is in rejected tab
        resp_tab = self.client.get('/approval/accounts?status=rejected')
        self.assertEqual(resp_tab.status_code, 200)
        self.assertIn("user_pending", resp_tab.get_data(as_text=True))

    def test_rejected_user_can_be_approved_later(self):
        approver = self._create_approval_owner()
        user = User(
            username="google_user",
            full_name="Google User",
            role=UserRole.STAFF.value,
            is_active=False,
            approval_status="rejected",
            auth_provider="google",
            oauth_id="123"
        )
        user.set_password("Password123!")
        db.session.add(user)
        db.session.commit()

        self._login_as(approver)

        # Approve the rejected user
        resp = self.client.post(f'/approval/users/{user.id}/approve')
        self.assertEqual(resp.status_code, 302)

        db.session.refresh(user)
        self.assertEqual(user.approval_status, 'active')
        self.assertTrue(user.is_active)
        self.assertEqual(user.role, UserRole.OWNER.value)

        # Workspace should be provisioned
        member = WorkspaceMember.query.filter_by(user_id=user.id, role="owner", status="active").first()
        self.assertIsNotNone(member)
        self.assertIsNotNone(member.workspace)

    def test_active_user_can_be_disabled(self):
        approver = self._create_approval_owner()
        user = User(username="user_active", full_name="Active User", role=UserRole.STAFF.value, is_active=True, approval_status="active")
        user.set_password("Password123!")
        db.session.add(user)
        db.session.commit()

        self._login_as(approver)

        resp = self.client.post(f'/approval/users/{user.id}/disable')
        self.assertEqual(resp.status_code, 302)

        db.session.refresh(user)
        self.assertEqual(user.approval_status, 'disabled')
        self.assertFalse(user.is_active)

        # Cannot login to app
        from services.auth_service import AuthService
        from core.exceptions import AuthenticationException
        with self.assertRaises(AuthenticationException) as context:
            AuthService.login("user_active", "Password123!")
        self.assertIn("không được phép đăng nhập", context.exception.message)

    def test_disabled_user_can_be_enabled(self):
        approver = self._create_approval_owner()
        user = User(username="user_disabled", full_name="Disabled User", role=UserRole.STAFF.value, is_active=False, approval_status="disabled")
        user.set_password("Password123!")
        db.session.add(user)
        db.session.commit()

        self._login_as(approver)

        resp = self.client.post(f'/approval/users/{user.id}/enable')
        self.assertEqual(resp.status_code, 302)

        db.session.refresh(user)
        self.assertEqual(user.approval_status, 'active')
        self.assertTrue(user.is_active)

    def test_approval_owner_cannot_manage_approval_owner(self):
        approver1 = self._create_approval_owner()
        approver2 = User(
            username="approver2",
            full_name="Quản trị duyệt 2",
            role=UserRole.APPROVAL_OWNER.value,
            is_active=True,
            approval_status="active"
        )
        approver2.set_password("Approver123!")
        db.session.add(approver2)
        db.session.commit()

        self._login_as(approver1)

        # Assert both current and other APPROVAL_OWNER are hidden in GET /approval/accounts
        for tab in ('pending', 'active', 'rejected', 'disabled'):
            resp = self.client.get(f'/approval/accounts?status={tab}')
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertNotIn("approver", html)
            self.assertNotIn("approver2", html)

        # Assert trying to reject other APPROVAL_OWNER is blocked
        resp_reject = self.client.post(f'/approval/users/{approver2.id}/reject')
        self.assertEqual(resp_reject.status_code, 302)
        db.session.refresh(approver2)
        self.assertEqual(approver2.approval_status, 'active')

        # Assert trying to disable other APPROVAL_OWNER is blocked
        resp_disable = self.client.post(f'/approval/users/{approver2.id}/disable')
        self.assertEqual(resp_disable.status_code, 302)
        db.session.refresh(approver2)
        self.assertEqual(approver2.approval_status, 'active')

        # Assert trying to enable other APPROVAL_OWNER is blocked
        approver2.approval_status = 'disabled'
        db.session.commit()
        resp_enable = self.client.post(f'/approval/users/{approver2.id}/enable')
        self.assertEqual(resp_enable.status_code, 302)
        db.session.refresh(approver2)
        self.assertEqual(approver2.approval_status, 'disabled')

        # Assert trying to approve other APPROVAL_OWNER is blocked
        approver2.approval_status = 'pending'
        db.session.commit()
        resp_approve = self.client.post(f'/approval/users/{approver2.id}/approve')
        self.assertEqual(resp_approve.status_code, 302)
        db.session.refresh(approver2)
        self.assertEqual(approver2.approval_status, 'pending')

    def test_non_approval_owner_cannot_access_approval_portal(self):
        user = User(
            username="owner_user",
            full_name="Spa Owner",
            role=UserRole.OWNER.value,
            is_active=True,
            approval_status="active"
        )
        user.set_password("Password123!")
        db.session.add(user)
        db.session.commit()

        self._login_as(user)

        resp = self.client.get('/approval/accounts')
        self.assertEqual(resp.status_code, 403)

    def test_rejected_google_login_renders_rejected_status_page(self):
        user = User(
            username="google_user",
            full_name="Google User",
            role=UserRole.STAFF.value,
            is_active=False,
            approval_status="rejected",
            auth_provider="google",
            oauth_id="123",
            email="google@example.com"
        )
        user.set_password("Password123!")
        db.session.add(user)
        db.session.commit()

        identity = {
            "sub": "123",
            "email": "google@example.com",
            "name": "Google User"
        }
        with app.test_request_context():
            resp = create_or_route_google_pending_user(identity)
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp.headers['Location'], '/auth/pending')

        self._login_as(user)
        resp_page = self.client.get('/auth/pending')
        self.assertEqual(resp_page.status_code, 200)
        html = resp_page.get_data(as_text=True)
        self.assertIn("Tài khoản đã bị từ chối", html)
        self.assertIn("Tài khoản Google này đã bị từ chối", html)
        # Should not get into dashboard
        resp_dash = self.client.get('/')
        self.assertEqual(resp_dash.status_code, 302)
        self.assertEqual(resp_dash.headers['Location'], '/auth/pending')

    def test_disabled_google_login_renders_disabled_status_page(self):
        user = User(
            username="google_user",
            full_name="Google User",
            role=UserRole.STAFF.value,
            is_active=False,
            approval_status="disabled",
            auth_provider="google",
            oauth_id="123",
            email="google@example.com"
        )
        user.set_password("Password123!")
        db.session.add(user)
        db.session.commit()

        identity = {
            "sub": "123",
            "email": "google@example.com",
            "name": "Google User"
        }
        with app.test_request_context():
            resp = create_or_route_google_pending_user(identity)
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp.headers['Location'], '/auth/pending')

        self._login_as(user)
        resp_page = self.client.get('/auth/pending')
        self.assertEqual(resp_page.status_code, 200)
        html = resp_page.get_data(as_text=True)
        self.assertIn("Tài khoản đã bị vô hiệu hóa", html)

    def test_pending_google_login_still_renders_pending_page(self):
        user = User(
            username="google_user",
            full_name="Google User",
            role=UserRole.STAFF.value,
            is_active=False,
            approval_status="pending",
            auth_provider="google",
            oauth_id="123",
            email="google@example.com"
        )
        user.set_password("Password123!")
        db.session.add(user)
        db.session.commit()

        self._login_as(user)
        resp_page = self.client.get('/auth/pending')
        self.assertEqual(resp_page.status_code, 200)
        html = resp_page.get_data(as_text=True)
        self.assertIn("Tài khoản chờ duyệt", html)

    def test_local_disabled_login_renders_disabled_status_or_single_message(self):
        user = User(
            username="local_disabled",
            full_name="Local Disabled",
            role=UserRole.STAFF.value,
            is_active=False,
            approval_status="disabled",
            auth_provider="local"
        )
        user.set_password("Password123!")
        db.session.add(user)
        db.session.commit()

        resp = self.client.post('/login', json={
            "username": "local_disabled",
            "password": "Password123!"
        })
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertEqual(data.get("redirect"), "/auth/pending")
        self.assertTrue(data.get("status_page"))

    def test_approved_accounts_group_owner_registered_vs_owner_created_members(self):
        approver = self._create_approval_owner()

        owner = User(
            username="google_owner",
            full_name="Anh Bảy",
            role=UserRole.OWNER.value,
            is_active=True,
            approval_status="active",
            auth_provider="google",
            oauth_id="owner_oauth"
        )
        owner.set_password("Password123!")
        db.session.add(owner)
        db.session.commit()

        from services.workspace_service import WorkspaceService
        ws = WorkspaceService.ensure_workspace_for_approved_owner(owner, approved_by=approver)
        ws.name = "Spa Của Anh Bảy"
        db.session.commit()

        staff = User(
            username="staff_user",
            full_name="Bích Trâm",
            role=UserRole.STAFF.value,
            is_active=True,
            approval_status="active",
            auth_provider="local"
        )
        staff.set_password("Password123!")
        db.session.add(staff)
        db.session.commit()

        from models.workspace import WorkspaceMember
        member = WorkspaceMember(
            workspace_id=ws.id,
            user_id=staff.id,
            role="staff",
            status="active",
            invited_by_id=owner.id
        )
        db.session.add(member)
        db.session.commit()

        self._login_as(approver)
        resp = self.client.get('/approval/accounts?status=active')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn("Nhóm 1: Chủ spa / tài khoản đăng ký", html)
        self.assertIn("google_owner", html)
        self.assertIn("Anh Bảy", html)
        self.assertIn("Spa Của Anh Bảy", html)

        self.assertIn("Nhóm 2: Nhân viên/quản lý do Chủ spa tạo", html)
        self.assertIn("staff_user", html)
        self.assertIn("Bích Trâm", html)

    def test_owner_created_members_group_by_workspace_owner(self):
        approver = self._create_approval_owner()

        owner_a = User(username="owner_a", full_name="Owner A", role=UserRole.OWNER.value, is_active=True, approval_status="active", auth_provider="google", oauth_id="oauth_a")
        owner_a.set_password("Password123!")
        db.session.add(owner_a)
        db.session.commit()
        from services.workspace_service import WorkspaceService
        ws_a = WorkspaceService.ensure_workspace_for_approved_owner(owner_a, approved_by=approver)
        ws_a.name = "Spa A"

        owner_b = User(username="owner_b", full_name="Owner B", role=UserRole.OWNER.value, is_active=True, approval_status="active", auth_provider="google", oauth_id="oauth_b")
        owner_b.set_password("Password123!")
        db.session.add(owner_b)
        db.session.commit()
        ws_b = WorkspaceService.ensure_workspace_for_approved_owner(owner_b, approved_by=approver)
        ws_b.name = "Spa B"
        db.session.commit()

        staff_a = User(username="staff_a", full_name="Staff A", role=UserRole.STAFF.value, is_active=True, approval_status="active")
        staff_a.set_password("Password123!")
        db.session.add(staff_a)
        db.session.commit()
        from models.workspace import WorkspaceMember
        db.session.add(WorkspaceMember(workspace_id=ws_a.id, user_id=staff_a.id, role="staff", status="active", invited_by_id=owner_a.id))

        staff_b = User(username="staff_b", full_name="Staff B", role=UserRole.STAFF.value, is_active=True, approval_status="active")
        staff_b.set_password("Password123!")
        db.session.add(staff_b)
        db.session.commit()
        db.session.add(WorkspaceMember(workspace_id=ws_b.id, user_id=staff_b.id, role="staff", status="active", invited_by_id=owner_b.id))
        db.session.commit()

        self._login_as(approver)
        resp = self.client.get('/approval/accounts?status=active')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn("Workspace: Spa A", html)
        self.assertIn("Chủ spa: Owner A", html)
        self.assertIn("Workspace: Spa B", html)
        self.assertIn("Chủ spa: Owner B", html)

    def test_approval_owner_not_in_any_group(self):
        approver = self._create_approval_owner()
        self._login_as(approver)
        resp = self.client.get('/approval/accounts?status=active')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertNotIn(approver.username, html)

    def test_approve_rejected_google_does_not_create_duplicate_workspace(self):
        approver = self._create_approval_owner()
        user = User(
            username="google_user",
            full_name="Google User",
            role=UserRole.STAFF.value,
            is_active=False,
            approval_status="rejected",
            auth_provider="google",
            oauth_id="123",
            email="google@example.com"
        )
        user.set_password("Password123!")
        db.session.add(user)
        db.session.commit()

        self._login_as(approver)

        # 1. First approval -> provisions workspace
        self.client.post(f'/approval/users/{user.id}/approve')
        db.session.refresh(user)
        
        # Verify 1 workspace and membership
        m1 = WorkspaceMember.query.filter_by(user_id=user.id).all()
        self.assertEqual(len(m1), 1)
        w1_id = m1[0].workspace_id

        # 2. Disable user -> membership becomes inactive
        self.client.post(f'/approval/users/{user.id}/disable')
        db.session.refresh(user)
        self.assertEqual(user.approval_status, 'disabled')

        m2 = WorkspaceMember.query.filter_by(user_id=user.id).all()
        self.assertEqual(len(m2), 1)
        self.assertEqual(m2[0].status, 'inactive')

        # 3. Enable user again -> membership becomes active, no new workspace
        self.client.post(f'/approval/users/{user.id}/enable')
        db.session.refresh(user)
        self.assertEqual(user.approval_status, 'active')

        m3 = WorkspaceMember.query.filter_by(user_id=user.id).all()
        self.assertEqual(len(m3), 1)
        self.assertEqual(m3[0].status, 'active')
        self.assertEqual(m3[0].workspace_id, w1_id)
        
        # Verify total workspace count in DB remains 1
        self.assertEqual(Workspace.query.count(), 1)

    def test_approval_accounts_template_avoids_horizontal_scroll(self):
        approver = self._create_approval_owner()
        self._login_as(approver)
        resp = self.client.get('/approval/accounts?status=active')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("table-layout: fixed", html)

    def test_approval_action_buttons_use_consistent_class(self):
        approver = self._create_approval_owner()
        self._login_as(approver)
        resp = self.client.get('/approval/accounts?status=active')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("approval-action-btn", html)
        self.assertIn("approval-action-group", html)

    def test_approval_accounts_template_wraps_long_text(self):
        approver = self._create_approval_owner()
        self._login_as(approver)
        resp = self.client.get('/approval/accounts?status=active')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("word-wrap: break-word", html)
        self.assertIn("word-break: break-word", html)

    def test_approval_accounts_mobile_card_layout_present(self):
        approver = self._create_approval_owner()
        # Create an active user to ensure the card layout renders!
        user = User(username="user_active", full_name="User Active", role=UserRole.STAFF.value, is_active=True, approval_status="active")
        user.set_password("Password123!")
        db.session.add(user)
        db.session.commit()

        self._login_as(approver)
        resp = self.client.get('/approval/accounts?status=active')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("approval-mobile-cards", html)
        self.assertIn("Tên đăng nhập", html)

    def test_approval_accounts_desktop_table_and_mobile_cards_separated(self):
        approver = self._create_approval_owner()
        self._login_as(approver)
        resp = self.client.get('/approval/accounts?status=active')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("approval-desktop-table", html)
        self.assertIn("approval-mobile-cards", html)
        self.assertIn("@media (max-width: 991.98px)", html)

    def test_approval_accounts_no_mobile_header_word_break(self):
        approver = self._create_approval_owner()
        self._login_as(approver)
        resp = self.client.get('/approval/accounts?status=active')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertNotIn("word-break: break-all", html)
        self.assertIn(".app-table th", html)
        self.assertIn("word-break: normal", html)

    def test_approval_method_badges_use_stack_class(self):
        approver = self._create_approval_owner()
        self._login_as(approver)
        resp = self.client.get('/approval/accounts?status=active')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("approval-method-stack", html)
        self.assertIn("badge-provider", html)
