import os
import re
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
from utils.timezone_utils import utc_now
from flask import session
from tests.session_helpers import set_authenticated_session
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
            set_authenticated_session(sess, user)
            sess["_enable_workspace_isolation"] = True
            if workspace_id:
                sess["current_workspace_id"] = workspace_id

    def _csrf_token(self):
        response = self.client.get("/users", follow_redirects=True)
        html = response.get_data(as_text=True)
        match = re.search(r'name="csrf-token" content="([^"]+)"', html)
        if not match:
            match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match, "CSRF token not found in response HTML")
        return match.group(1)

    def _post_form_as(self, actor, workspace_id, url, payload):
        self._login_as(actor, workspace_id)
        return self.client.post(
            url,
            data=payload,
            headers={"X-CSRFToken": self._csrf_token()},
            follow_redirects=False,
        )

    def _post_json_as(self, actor, workspace_id, url, payload):
        self._login_as(actor, workspace_id)
        return self.client.post(
            url,
            json=payload,
            headers={
                "X-CSRFToken": self._csrf_token(),
                "X-Requested-With": "XMLHttpRequest",
            },
            follow_redirects=False,
        )

    def _flashed_messages(self):
        with self.client.session_transaction() as sess:
            return [message for _, message in sess.get("_flashes", [])]

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
            set_authenticated_session(session, owner)
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

    def test_soft_delete_followup_get_preserves_removed_membership(self):
        owner = self._create_user("owner_followup", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        staff = self._create_user("staff_followup", "STAFF")
        WorkspaceService.add_member_for_user(workspace.id, staff, "STAFF")
        db.session.commit()

        response = self._post_form_as(
            owner,
            workspace.id,
            f"/users/{staff.id}/soft-delete",
            {"reason": "Follow-up regression"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/users"))

        removed = WorkspaceMember.query.filter_by(
            workspace_id=workspace.id,
            user_id=staff.id,
        ).one()
        removed_state = (removed.status, removed.removed_at, removed.removed_by_id)
        self.assertEqual(removed.status, "removed")
        self.assertIsNotNone(removed.removed_at)
        self.assertEqual(removed.removed_by_id, owner.id)

        followup = self.client.get(response.headers["Location"], follow_redirects=False)
        self.assertEqual(followup.status_code, 200)
        tables = re.findall(r"<table\b.*?</table>", followup.get_data(as_text=True), re.DOTALL)
        self.assertEqual(len(tables), 2)
        active_table, removed_table = tables
        self.assertNotIn(staff.username, active_table)
        self.assertIn(staff.username, removed_table)

        db.session.expire_all()
        removed = WorkspaceMember.query.filter_by(
            workspace_id=workspace.id,
            user_id=staff.id,
        ).one()
        self.assertEqual(
            (removed.status, removed.removed_at, removed.removed_by_id),
            removed_state,
        )
        self.assertIsNotNone(User.query.get(staff.id))
        self.assertTrue(User.query.get(staff.id).is_active)
        self.assertEqual(
            ActivityLog.query.filter_by(
                action="RESTORE_USER",
                reference_id=staff.id,
            ).count(),
            0,
        )
        self.assertEqual(
            WorkspaceMember.query.filter_by(
                workspace_id=workspace.id,
                user_id=staff.id,
            ).count(),
            1,
        )
        self.assertEqual(ActivityLog.query.filter_by(action="REMOVE_USER", reference_id=staff.id).count(), 1)

    def _legacy_repair_fixture(self, username):
        owner = self._create_user(f"{username}_owner", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        target = self._create_user(f"{username}_staff", "STAFF")
        db.session.add(ActivityLog(
            module="Users",
            action="CREATE_USER",
            description="legacy repair fixture",
            reference_id=target.id,
            user_id=owner.id,
        ))
        db.session.commit()
        return owner, workspace, target

    def test_legacy_repair_preserves_removed_membership(self):
        owner, workspace, target = self._legacy_repair_fixture("repair_removed")
        membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=target.id,
            role="staff",
            status="removed",
            removed_at=utc_now(),
            removed_by_id=owner.id,
            removal_reason="explicit removal",
        )
        db.session.add(membership)
        db.session.commit()
        before = (membership.status, membership.removed_at, membership.removed_by_id, membership.removal_reason)

        self.assertEqual(WorkspaceService.repair_legacy_owner_created_memberships(owner), 0)
        db.session.expire_all()
        after = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=target.id).one()
        self.assertEqual((after.status, after.removed_at, after.removed_by_id, after.removal_reason), before)

    def test_legacy_repair_does_not_mutate_active_membership(self):
        owner, workspace, target = self._legacy_repair_fixture("repair_active")
        WorkspaceService.add_member_for_user(workspace.id, target, "STAFF")
        db.session.commit()
        before = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=target.id).one()
        before_state = (before.status, before.role, before.removed_at, before.removed_by_id)

        self.assertEqual(WorkspaceService.repair_legacy_owner_created_memberships(owner), 0)
        db.session.expire_all()
        after = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=target.id).one()
        self.assertEqual((after.status, after.role, after.removed_at, after.removed_by_id), before_state)
        self.assertEqual(WorkspaceMember.query.filter_by(user_id=target.id).count(), 1)

    def test_legacy_repair_creates_genuinely_missing_membership(self):
        owner, workspace, target = self._legacy_repair_fixture("repair_missing")

        self.assertEqual(WorkspaceService.repair_legacy_owner_created_memberships(owner), 1)
        membership = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=target.id).one()
        self.assertEqual(membership.status, "active")
        self.assertEqual(membership.role, "staff")

    def test_legacy_repair_is_idempotent(self):
        owner, workspace, target = self._legacy_repair_fixture("repair_idempotent")

        self.assertEqual(WorkspaceService.repair_legacy_owner_created_memberships(owner), 1)
        db.session.commit()
        membership = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=target.id).one()
        before = (membership.status, membership.role, membership.created_at, membership.updated_at)

        self.assertEqual(WorkspaceService.repair_legacy_owner_created_memberships(owner), 0)
        db.session.expire_all()
        after = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=target.id).one()
        self.assertEqual((after.status, after.role, after.created_at, after.updated_at), before)
        self.assertEqual(WorkspaceMember.query.filter_by(user_id=target.id).count(), 1)

    def test_owner_and_admin_role_hierarchy_matrix(self):
        owner = self._create_user("matrix_owner", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        admin = self._create_user("matrix_admin", "ADMIN")
        second_admin = self._create_user("matrix_second_admin", "ADMIN")
        staff = self._create_user("matrix_staff", "STAFF")
        second_owner = self._create_user("matrix_second_owner", "OWNER")

        for user, role in (
            (admin, "ADMIN"),
            (second_admin, "ADMIN"),
            (staff, "STAFF"),
            (second_owner, "OWNER"),
        ):
            WorkspaceService.add_member_for_user(workspace.id, user, role)
        approval_membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=self.approval_owner.id,
            role="approval_owner",
            status="active",
        )
        db.session.add(approval_membership)
        db.session.commit()

        with app.test_request_context():
            set_authenticated_session(session, owner)
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id

            UserService.toggle_active(actor=owner, user_id=admin.id, is_active=False)
            UserService.toggle_active(actor=owner, user_id=admin.id, is_active=True)
            UserService.toggle_active(actor=owner, user_id=staff.id, is_active=False)
            UserService.toggle_active(actor=owner, user_id=staff.id, is_active=True)
            UserService.soft_delete_user(actor=owner, user_id=admin.id)
            UserService.restore_user(actor=owner, user_id=admin.id)
            UserService.soft_delete_user(actor=owner, user_id=staff.id)
            UserService.restore_user(actor=owner, user_id=staff.id)

            for target in (owner, second_owner, self.approval_owner):
                with self.assertRaises(Exception):
                    UserService.soft_delete_user(actor=owner, user_id=target.id)

            with self.assertRaises(Exception):
                UserService.toggle_active(actor=owner, user_id=owner.id, is_active=False)

            set_authenticated_session(session, admin)
            for target in (owner, second_owner, second_admin, self.approval_owner, admin):
                before_active = User.query.get(target.id).is_active
                with self.assertRaises(Exception):
                    UserService.toggle_active(actor=admin, user_id=target.id, is_active=False)
                self.assertEqual(User.query.get(target.id).is_active, before_active)

            UserService.toggle_active(actor=admin, user_id=staff.id, is_active=False)
            UserService.toggle_active(actor=admin, user_id=staff.id, is_active=True)
            UserService.soft_delete_user(actor=admin, user_id=staff.id)
            UserService.restore_user(actor=admin, user_id=staff.id)

    def test_direct_post_denials_have_no_success_and_allowed_controls_work(self):
        owner = self._create_user("post_owner", "OWNER")
        workspace = WorkspaceService.ensure_workspace_for_approved_owner(owner)
        admin = self._create_user("post_admin", "ADMIN")
        admin_target = self._create_user("post_admin_target", "ADMIN")
        staff = self._create_user("post_staff", "STAFF")
        owner_target = self._create_user("post_owner_target", "OWNER")
        restore_owner = self._create_user("post_restore_owner", "OWNER")
        restore_admin = self._create_user("post_restore_admin", "ADMIN")
        other_owner = self._create_user("post_other_owner", "OWNER")
        other_workspace = WorkspaceService.ensure_workspace_for_approved_owner(other_owner)
        cross_staff = self._create_user("post_cross_staff", "STAFF")

        for user, role in (
            (admin, "ADMIN"),
            (admin_target, "ADMIN"),
            (staff, "STAFF"),
            (owner_target, "OWNER"),
            (restore_owner, "OWNER"),
            (restore_admin, "ADMIN"),
        ):
            WorkspaceService.add_member_for_user(workspace.id, user, role)
        WorkspaceService.add_member_for_user(other_workspace.id, cross_staff, "STAFF")
        WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=restore_owner.id).update({"status": "removed"})
        WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=restore_admin.id).update({"status": "removed"})
        db.session.add(WorkspaceMember(
            workspace_id=workspace.id,
            user_id=self.approval_owner.id,
            role="approval_owner",
            status="active",
        ))
        db.session.commit()

        self._login_as(admin, workspace.id)
        admin_html = self.client.get("/users").get_data(as_text=True)
        self.assertNotIn(f"/users/{owner_target.id}/soft-delete", admin_html)
        self.assertNotIn(f"/users/{admin_target.id}/soft-delete", admin_html)
        self.assertIn(f"/users/{staff.id}/soft-delete", admin_html)

        def assert_redirect_denied(response):
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers["Location"].endswith("/users"))
            follow_response = self.client.get(response.headers["Location"], follow_redirects=True)
            html = follow_response.get_data(as_text=True)
            self.assertTrue("Không" in html or "không" in html)
            self.assertNotIn("Đã xóa mềm nhân viên khỏi workspace", html)
            self.assertNotIn("Đã khôi phục nhân viên vào workspace", html)
            self.assertNotIn("Đã vô hiệu hóa người dùng thành công", html)
            self.assertNotIn("Đã kích hoạt người dùng thành công", html)

        def assert_json_denied(response, expected_status):
            self.assertEqual(response.status_code, expected_status)
            self.assertTrue(response.is_json)
            body = response.get_json()
            self.assertIsInstance(body, dict)
            self.assertTrue(body.get("error") or body.get("message"))
            self.assertIsNot(body.get("success"), True)
            body.setdefault("message", body.get("error", ""))
            self.assertNotIn("Đã ", body["message"])

        def assert_global_approval_owner_redirect(
            response,
            target,
            before_active,
            before_activity_log_count,
        ):
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers.get("Location"), "/approval/pending")
            with self.client.session_transaction() as sess:
                flashes = sess.get("_flashes", [])
            self.assertFalse(any(category == "success" for category, _ in flashes))
            self.assertEqual(User.query.get(target.id).is_active, before_active)
            self.assertEqual(ActivityLog.query.count(), before_activity_log_count)

        def assert_redirect_success(response):
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers["Location"].endswith("/users"))
            with self.client.session_transaction() as sess:
                flashes = sess.get("_flashes", [])
            self.assertTrue(any(category == "success" for category, _ in flashes))

        for target in (owner_target, admin_target, self.approval_owner):
            before = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=target.id).first()
            before_state = (before.status, before.removed_at, before.removed_by_id, before.removal_reason)
            response = self._post_form_as(admin, workspace.id, f"/users/{target.id}/soft-delete", {"reason": "denied"})
            assert_redirect_denied(response)
            after = WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=target.id).first()
            self.assertEqual((after.status, after.removed_at, after.removed_by_id, after.removal_reason), before_state)

        for target in (restore_owner, restore_admin):
            response = self._post_form_as(admin, workspace.id, f"/users/{target.id}/restore", {})
            assert_redirect_denied(response)
            self.assertEqual(
                WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=target.id).first().status,
                "removed",
            )

        for target in (admin_target, self.approval_owner):
            before_active = User.query.get(target.id).is_active
            response = self._post_json_as(admin, workspace.id, f"/users/{target.id}/toggle-active", {"is_active": "0"})
            assert_json_denied(response, 403 if target is self.approval_owner else 400)
            self.assertEqual(User.query.get(target.id).is_active, before_active)

        before_active = User.query.get(admin.id).is_active
        response = self._post_json_as(admin, workspace.id, f"/users/{admin.id}/toggle-active", {"is_active": "0"})
        assert_json_denied(response, 400)
        self.assertEqual(User.query.get(admin.id).is_active, before_active)

        response = self._post_json_as(admin, workspace.id, f"/users/{cross_staff.id}/toggle-active", {"is_active": "0"})
        assert_json_denied(response, 404)
        self.assertTrue(User.query.get(cross_staff.id).is_active)

        response = self._post_json_as(owner, workspace.id, f"/users/{owner_target.id}/toggle-active", {"is_active": "0"})
        assert_json_denied(response, 400)
        response = self._post_json_as(owner, workspace.id, f"/users/{self.approval_owner.id}/toggle-active", {"is_active": "0"})
        assert_json_denied(response, 403)
        response = self._post_json_as(owner, workspace.id, f"/users/{owner.id}/toggle-active", {"is_active": "0"})
        assert_json_denied(response, 400)

        before_active = User.query.get(staff.id).is_active
        before_activity_log_count = ActivityLog.query.count()
        response = self._post_json_as(
            self.approval_owner,
            workspace.id,
            f"/users/{staff.id}/toggle-active",
            {"is_active": "0"},
        )
        assert_global_approval_owner_redirect(
            response,
            staff,
            before_active,
            before_activity_log_count,
        )

        response = self._post_form_as(owner, workspace.id, f"/users/{staff.id}/soft-delete", {"reason": "allowed"})
        assert_redirect_success(response)
        self.assertEqual(WorkspaceMember.query.filter_by(workspace_id=workspace.id, user_id=staff.id).first().status, "removed")

        response = self._post_form_as(owner, workspace.id, f"/users/{staff.id}/restore", {})
        assert_redirect_success(response)

        response = self._post_form_as(admin, workspace.id, f"/users/{admin_target.id}/soft-delete", {"reason": "denied"})
        assert_redirect_denied(response)
        response = self._post_form_as(admin, workspace.id, f"/users/{staff.id}/soft-delete", {"reason": "allowed"})
        assert_redirect_success(response)

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
            set_authenticated_session(session, owner_1)
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
                set_authenticated_session(session, owner_2)
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
            set_authenticated_session(session, owner)
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
            set_authenticated_session(session, owner)
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
            set_authenticated_session(session, owner)
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
