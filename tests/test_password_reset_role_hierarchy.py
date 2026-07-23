import re
import unittest
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4
from unittest.mock import patch

from app import app
from core.auth.constants import AUTH_SESSION_KEY
from tests.session_helpers import set_authenticated_session
from extensions import db
from models.activity_log import ActivityLog
from models.user import User
from models.workspace import Workspace, WorkspaceMember


class PasswordResetRoleHierarchyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context()
        cls.context.push()
        db.drop_all()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        cls.context.pop()

    def setUp(self):
        db.session.rollback()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()

    def tearDown(self):
        db.session.rollback()

    def _user(self, username, role, password="OldPassword123!"):
        user = User(
            username=username,
            full_name=username,
            role=role,
            approval_status="active",
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        return user

    def _workspace(self, users):
        workspace = Workspace(
            name=f"Reset Test {uuid4().hex}",
            slug=f"reset-{uuid4().hex}",
            status="active",
        )
        db.session.add(workspace)
        db.session.flush()
        for user in users:
            db.session.add(
                WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role=user.role.lower(),
                    status="active",
                )
            )
        db.session.commit()
        return workspace

    def _login(self, user, workspace, csrf_token=None):
        with self.client.session_transaction() as session:
            set_authenticated_session(session, user, workspace_id=workspace.id if workspace else None)
            session["_enable_workspace_isolation"] = True
            if csrf_token is not None:
                session["_csrf_token"] = csrf_token
            if workspace is None:
                session.pop("current_workspace_id", None)
            else:
                session["current_workspace_id"] = workspace.id

    def _csrf_token(self, response):
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
        if not match:
            match = re.search(r'name="csrf-token" content="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(match)
        return match.group(1)

    def test_management_reset_enforces_full_role_matrix(self):
        owner = self._user("owner", "OWNER")
        admin = self._user("admin", "ADMIN")
        other_admin = self._user("other-admin", "ADMIN")
        staff = self._user("staff", "STAFF")
        other_owner = self._user("other-owner", "OWNER")
        approval_owner = self._user("approval-owner", "APPROVAL_OWNER")
        workspace = self._workspace([owner, admin, other_admin, staff, other_owner, approval_owner])

        cases = [
            (admin, staff, 200),
            (admin, other_admin, 403),
            (admin, other_owner, 403),
            (admin, approval_owner, 403),
            (owner, staff, 200),
            (owner, admin, 200),
            (owner, other_owner, 403),
            (owner, approval_owner, 403),
        ]
        for actor, target, expected in cases:
            with self.subTest(actor=actor.role, target=target.role):
                self._login(actor, workspace)
                response = self.client.get(f"/users/{target.id}/reset-password")
                self.assertEqual(response.status_code, expected)

    def test_allowed_reset_updates_password_and_audits(self):
        owner = self._user("owner", "OWNER")
        target = self._user("target", "STAFF")
        workspace = self._workspace([owner, target])
        self._login(owner, workspace)

        form = self.client.get(f"/users/{target.id}/reset-password")
        token = self._csrf_token(form)
        response = self.client.post(
            f"/users/{target.id}/reset-password",
            data={
                "csrf_token": token,
                "new_password": "NewPassword123!",
                "confirm_password": "NewPassword123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        db.session.expire_all()
        target = db.session.get(User, target.id)
        self.assertTrue(target.check_password("NewPassword123!"))
        self.assertEqual(
            ActivityLog.query.filter_by(action="RESET_USER_PASSWORD").count(), 1
        )

    def test_self_and_cross_workspace_reset_fail_closed(self):
        owner = self._user("owner", "OWNER")
        remote = self._user("remote", "STAFF")
        local_workspace = self._workspace([owner])
        remote_workspace = self._workspace([remote])
        self._login(owner, local_workspace)

        self.assertEqual(
            self.client.get(f"/users/{owner.id}/reset-password").status_code,
            403,
        )
        self.assertEqual(
            self.client.get(f"/users/{remote.id}/reset-password").status_code,
            404,
        )

    def test_approval_owner_is_denied_without_workspace_context(self):
        approval_owner = self._user("approval-owner", "APPROVAL_OWNER")
        target = self._user("target", "STAFF")
        db.session.commit()

        # The canonical permission denial is raised before target/workspace lookup.
        from core.exceptions import PermissionDeniedException
        from services.user_service import UserService
        with self.assertRaises(PermissionDeniedException):
            UserService.reset_password(
                approval_owner, target.id, "ShouldNotApply123!"
            )

    def test_protected_target_and_actor_are_denied_before_workspace_lookup(self):
        owner = self._user("owner", "OWNER")
        admin = self._user("admin", "ADMIN")
        approval_owner = self._user("approval-owner", "APPROVAL_OWNER")
        staff = self._user("staff", "STAFF")
        owner_workspace = self._workspace([owner])
        admin_workspace = self._workspace([admin])
        db.session.commit()
        protected_hash = approval_owner.password_hash
        staff_hash = staff.password_hash
        audit_count = ActivityLog.query.filter_by(action="RESET_USER_PASSWORD").count()

        csrf_token = self._csrf_token(self.client.get("/login"))
        for actor, workspace in ((owner, owner_workspace), (admin, admin_workspace)):
            self._login(actor, None, csrf_token)
            with self.client.session_transaction() as session:
                self.assertIsNone(session.get("current_workspace_id"))
            self.assertEqual(
                WorkspaceMember.query.filter_by(
                    workspace_id=workspace.id,
                    user_id=actor.id,
                    status="active",
                ).count(),
                1,
            )

            from services.user_service import UserService
            with patch.object(
                UserService,
                "_ensure_reset_target_is_not_protected",
                wraps=UserService._ensure_reset_target_is_not_protected,
            ) as protected_helper:
                get_response = self.client.get(
                    f"/users/{approval_owner.id}/reset-password"
                )
                protected_helper.assert_called_once_with(approval_owner.id)

            self.assertEqual(get_response.status_code, 403)
            self.assertIsNone(get_response.location)
            with self.client.session_transaction() as session:
                self.assertEqual(session.get("current_workspace_id"), workspace.id)

            response = self.client.post(
                f"/users/{approval_owner.id}/reset-password",
                data={
                    "csrf_token": csrf_token,
                    "new_password": "ShouldNotApply123!",
                    "confirm_password": "ShouldNotApply123!",
                },
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.location, None)
            db.session.expire_all()
            self.assertEqual(db.session.get(User, approval_owner.id).password_hash, protected_hash)

        self._login(approval_owner, None, csrf_token)
        with self.client.session_transaction() as session:
            self.assertIsNone(session.get("current_workspace_id"))
        self.assertEqual(
            WorkspaceMember.query.filter_by(user_id=approval_owner.id).count(),
            0,
        )
        workspace_count = Workspace.query.count()
        from services.user_service import UserService
        with patch.object(
            UserService,
            "_ensure_reset_target_is_not_protected",
            wraps=UserService._ensure_reset_target_is_not_protected,
        ) as protected_helper:
            get_response = self.client.get(
                f"/users/{staff.id}/reset-password",
                follow_redirects=False,
            )
            protected_helper.assert_not_called()
        self.assertEqual(get_response.status_code, 302)
        self.assertEqual(get_response.location, "/approval/pending")
        with self.client.session_transaction() as session:
            self.assertIsNone(session.get("current_workspace_id"))
        with patch.object(
            UserService,
            "_ensure_reset_target_is_not_protected",
            wraps=UserService._ensure_reset_target_is_not_protected,
        ) as protected_helper:
            response = self.client.post(
                f"/users/{staff.id}/reset-password",
                data={
                    "csrf_token": csrf_token,
                    "new_password": "ShouldNotApply123!",
                    "confirm_password": "ShouldNotApply123!",
                },
                follow_redirects=False,
            )
            protected_helper.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/approval/pending")
        db.session.expire_all()
        self.assertEqual(db.session.get(User, staff.id).password_hash, staff_hash)
        self.assertEqual(Workspace.query.count(), workspace_count)
        self.assertEqual(
            WorkspaceMember.query.filter_by(user_id=approval_owner.id).count(),
            0,
        )
        self.assertEqual(
            ActivityLog.query.filter_by(action="RESET_USER_PASSWORD").count(),
            audit_count,
        )

    def test_user_index_uses_reset_policy_for_visibility(self):
        owner = self._user("owner", "OWNER")
        admin = self._user("admin", "ADMIN")
        staff = self._user("staff", "STAFF")
        workspace = self._workspace([owner, admin, staff])
        self._login(owner, workspace)
        owner_page = self.client.get("/users").get_data(as_text=True)

        self.assertIn(f'/users/{admin.id}/reset-password', owner_page)
        self.assertIn(f'/users/{staff.id}/reset-password', owner_page)
        self.assertNotIn(f'/users/{owner.id}/reset-password', owner_page)

        self._login(admin, workspace)
        admin_page = self.client.get("/users").get_data(as_text=True)
        self.assertIn(f'/users/{staff.id}/reset-password', admin_page)
        self.assertNotIn(f'/users/{admin.id}/reset-password', admin_page)
        self.assertNotIn(f'/users/{owner.id}/reset-password', admin_page)

    def test_forbidden_post_preserves_hash_audit_and_membership(self):
        owner = self._user("owner", "OWNER")
        target = self._user("target-owner", "OWNER")
        workspace = self._workspace([owner, target])
        self._login(owner, workspace)
        original_hash = target.password_hash
        original_membership = WorkspaceMember.query.filter_by(
            workspace_id=workspace.id, user_id=target.id
        ).one()
        token = self._csrf_token(self.client.get("/users"))

        response = self.client.post(
            f"/users/{target.id}/reset-password",
            data={
                "csrf_token": token,
                "new_password": "ShouldNotApply123!",
                "confirm_password": "ShouldNotApply123!",
            },
        )

        self.assertEqual(response.status_code, 403)
        db.session.expire_all()
        target_after = db.session.get(User, target.id)
        membership_after = WorkspaceMember.query.filter_by(
            workspace_id=workspace.id, user_id=target.id
        ).one()
        self.assertEqual(target_after.password_hash, original_hash)
        self.assertEqual(ActivityLog.query.filter_by(action="RESET_USER_PASSWORD").count(), 0)
        self.assertEqual(membership_after.status, original_membership.status)
