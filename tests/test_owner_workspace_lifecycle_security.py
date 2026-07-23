import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch


TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_owner_workspace_lifecycle_security.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_owner_workspace_lifecycle_security_media"

os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["PERSISTENT_ROOT"] = TEST_MEDIA_ROOT.as_posix()
os.environ["UPLOAD_ROOT"] = (TEST_MEDIA_ROOT / "uploads").as_posix()
os.environ["LOGO_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "logos").as_posix()
os.environ["AVATAR_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "avatars").as_posix()

from flask import session
from tests.session_helpers import set_authenticated_session
from werkzeug.exceptions import Forbidden

from app import app
from core.exceptions import PermissionDeniedException, ValidationException
from extensions import db
from models.activity_log import ActivityLog
from models.customer import Customer
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.user_service import UserService
from services.workspace_service import WorkspaceService
from utils.timezone_utils import utc_now


class TestOwnerWorkspaceLifecycleSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()
        cls.original_csrf_enabled = app.config.get("CSRF_ENABLED", True)
        app.config["CSRF_ENABLED"] = False
        db.create_all()
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        if TEST_DB_FILE.exists():
            TEST_DB_FILE.unlink()
        if TEST_MEDIA_ROOT.exists():
            shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        app.config["CSRF_ENABLED"] = cls.original_csrf_enabled
        cls.app_context.pop()

    def setUp(self):
        db.session.remove()
        ActivityLog.query.delete()
        Customer.query.delete()
        WorkspaceMember.query.delete()
        Workspace.query.delete()
        User.query.delete()
        db.session.commit()

        self.approval_owner = self._create_user(
            "approval_owner_security",
            "APPROVAL_OWNER",
        )
        db.session.commit()

    def _create_user(self, username, role, approval_status="active", is_active=True):
        user = User(
            username=username,
            full_name=username.replace("_", " ").title(),
            email=f"{username}@test.com",
            role=role,
            approval_status=approval_status,
            is_active=is_active,
        )
        user.set_password("Password123!")
        db.session.add(user)
        db.session.flush()
        return user

    def _create_workspace(self, owner, name, slug, membership_status="active"):
        workspace = Workspace(
            name=name,
            slug=slug,
            status="active",
            created_by_id=owner.id,
        )
        db.session.add(workspace)
        db.session.flush()
        membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=owner.id,
            role="owner",
            status=membership_status,
            joined_at=utc_now(),
        )
        db.session.add(membership)
        db.session.flush()
        return workspace, membership

    def _login_as(self, user, workspace_id=None):
        with self.client.session_transaction() as client_session:
            set_authenticated_session(client_session, user)
            client_session["_enable_workspace_isolation"] = True
            if workspace_id is not None:
                client_session["current_workspace_id"] = workspace_id

    def test_sole_owner_full_cycle_guards_and_data_ids_are_retained(self):
        owner = self._create_user("sole_owner", "OWNER")
        workspace, membership = self._create_workspace(owner, "Sole Spa", "sole-spa")
        customer = Customer(
            name="Lifecycle Customer",
            phone="0901000001",
            email="lifecycle@test.com",
            workspace_id=workspace.id,
        )
        db.session.add(customer)
        db.session.commit()

        owner_id = owner.id
        workspace_id = workspace.id
        membership_id = membership.id
        customer_id = customer.id
        workspace_count = Workspace.query.count()

        with app.test_request_context():
            set_authenticated_session(session, owner)
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id
            self.assertEqual(WorkspaceService.get_current_workspace_id(), workspace.id)
            self.assertEqual([row.id for row in WorkspaceService.scoped_query(Customer).all()], [customer.id])

            UserService.soft_delete_owner_workspace(self.approval_owner, owner.id, "Security smoke")

            self.assertFalse(owner.can_access_app)
            self.assertIsNotNone(workspace.deleted_at)
            self.assertFalse(WorkspaceService.is_user_in_workspace(owner.id, workspace.id))
            self.assertIsNone(WorkspaceService.get_current_workspace_id())
            self.assertNotIn("current_workspace_id", session)
            self.assertEqual(WorkspaceService.scoped_query(Customer).count(), 0)

            session["current_workspace_id"] = workspace.id
            with self.assertRaises(Forbidden):
                WorkspaceService.assign_workspace(
                    Customer(name="Blocked", phone="0901000002", workspace_id=workspace.id)
                )

        UserService.restore_owner_workspace(self.approval_owner, owner.id)

        self.assertTrue(owner.can_access_app)
        self.assertTrue(WorkspaceService.is_user_in_workspace(owner.id, workspace.id))
        self.assertEqual(membership.status, "active")
        self.assertEqual(Workspace.query.count(), workspace_count)
        self.assertEqual(Customer.query.count(), 1)
        self.assertEqual(db.session.get(User, owner_id).id, owner_id)
        self.assertEqual(db.session.get(Workspace, workspace_id).id, workspace_id)
        self.assertEqual(db.session.get(WorkspaceMember, membership_id).id, membership_id)
        self.assertEqual(db.session.get(Customer, customer_id).id, customer_id)
        self.assertIsNone(db.session.get(Customer, customer_id).deleted_at)

        with app.test_request_context():
            set_authenticated_session(session, owner)
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id
            self.assertEqual([row.id for row in WorkspaceService.scoped_query(Customer).all()], [customer_id])

    def test_co_owner_workspace_stays_active_and_co_owner_keeps_access(self):
        target = self._create_user("target_co_owner", "OWNER")
        co_owner = self._create_user("remaining_co_owner", "OWNER")
        workspace, target_membership = self._create_workspace(target, "Shared Spa", "shared-spa")
        co_owner_membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=co_owner.id,
            role="owner",
            status="active",
            joined_at=utc_now(),
        )
        customer = Customer(
            name="Shared Customer",
            phone="0902000001",
            workspace_id=workspace.id,
        )
        db.session.add_all([co_owner_membership, customer])
        db.session.commit()

        UserService.soft_delete_owner_workspace(self.approval_owner, target.id, "Co-owner smoke")

        self.assertIsNotNone(target.deleted_at)
        self.assertFalse(target.can_access_app)
        self.assertIsNone(workspace.deleted_at)
        self.assertEqual(target_membership.status, "active")
        self.assertEqual(co_owner_membership.status, "active")
        self.assertTrue(WorkspaceService.is_user_in_workspace(co_owner.id, workspace.id))

        with app.test_request_context():
            set_authenticated_session(session, co_owner)
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id
            self.assertEqual([row.id for row in WorkspaceService.scoped_query(Customer).all()], [customer.id])

        with app.test_request_context():
            set_authenticated_session(session, target)
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace.id
            self.assertIsNone(WorkspaceService.get_current_workspace_id())

        log = ActivityLog.query.filter_by(action="SOFT_DELETE_OWNER_WORKSPACE").one()
        self.assertIn(target.username, log.description)
        self.assertIn(workspace.name, log.description)
        self.assertIn("còn co-owner hợp lệ", log.description)

    def test_restore_only_workspace_with_matching_deletion_provenance(self):
        owner = self._create_user("provenance_owner", "OWNER", is_active=False)
        matching_workspace, matching_membership = self._create_workspace(
            owner,
            "Matching Spa",
            "matching-spa",
        )
        older_workspace, older_membership = self._create_workspace(
            owner,
            "Older Spa",
            "older-spa",
            membership_status="removed",
        )
        matching_customer = Customer(
            name="Matching Customer",
            phone="0903000001",
            workspace_id=matching_workspace.id,
        )
        older_customer = Customer(
            name="Older Customer",
            phone="0903000002",
            workspace_id=older_workspace.id,
        )
        db.session.add_all([matching_customer, older_customer])

        lifecycle_time = utc_now()
        owner.deleted_at = lifecycle_time
        owner.deleted_by_id = self.approval_owner.id
        matching_workspace.deleted_at = lifecycle_time
        matching_workspace.deleted_by_id = self.approval_owner.id
        older_workspace.deleted_at = lifecycle_time - timedelta(days=1)
        older_workspace.deleted_by_id = self.approval_owner.id
        db.session.commit()

        UserService.restore_owner_workspace(self.approval_owner, owner.id)

        self.assertIsNone(matching_workspace.deleted_at)
        self.assertIsNotNone(older_workspace.deleted_at)
        self.assertEqual(matching_membership.status, "active")
        self.assertEqual(older_membership.status, "removed")

        with app.test_request_context():
            set_authenticated_session(session, owner)
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = matching_workspace.id
            self.assertEqual(
                [row.id for row in WorkspaceService.scoped_query(Customer).all()],
                [matching_customer.id],
            )
            session["current_workspace_id"] = older_workspace.id
            self.assertEqual(WorkspaceService.scoped_query(Customer).count(), 0)

        log = ActivityLog.query.filter_by(action="RESTORE_OWNER_WORKSPACE").one()
        self.assertIn(matching_workspace.name, log.description)
        self.assertIn(older_workspace.name, log.description)
        self.assertIn("provenance không khớp", log.description)

    def test_restore_skips_workspace_with_same_timestamp_different_actor(self):
        actor_b = self._create_user("approval_owner_actor_b", "APPROVAL_OWNER")
        owner = self._create_user("different_actor_owner", "OWNER", is_active=False)
        matching_workspace, matching_membership = self._create_workspace(
            owner,
            "Matching Actor Spa",
            "matching-actor-spa",
        )
        mismatch_workspace, mismatch_membership = self._create_workspace(
            owner,
            "Different Actor Spa",
            "different-actor-spa",
        )
        mismatch_customer = Customer(
            name="Different Actor Customer",
            phone="0903000003",
            workspace_id=mismatch_workspace.id,
        )
        db.session.add(mismatch_customer)

        lifecycle_time = utc_now()
        owner.deleted_at = lifecycle_time
        owner.deleted_by_id = self.approval_owner.id
        owner.deletion_reason = "Owner lifecycle event"
        matching_workspace.deleted_at = lifecycle_time
        matching_workspace.deleted_by_id = self.approval_owner.id
        matching_workspace.deletion_reason = "Matching lifecycle event"
        mismatch_workspace.deleted_at = lifecycle_time
        mismatch_workspace.deleted_by_id = actor_b.id
        mismatch_workspace.deletion_reason = "Different actor event"
        db.session.commit()

        initial_workspace_count = Workspace.query.count()
        mismatch_membership_id = mismatch_membership.id
        mismatch_customer_id = mismatch_customer.id

        UserService.restore_owner_workspace(self.approval_owner, owner.id)

        self.assertIsNone(owner.deleted_at)
        self.assertIsNone(owner.deleted_by_id)
        self.assertIsNone(owner.deletion_reason)
        self.assertTrue(owner.is_active)

        self.assertIsNone(matching_workspace.deleted_at)
        self.assertIsNone(matching_workspace.deleted_by_id)
        self.assertIsNone(matching_workspace.deletion_reason)
        self.assertEqual(matching_membership.status, "active")

        self.assertEqual(mismatch_workspace.deleted_at, lifecycle_time)
        self.assertEqual(mismatch_workspace.deleted_by_id, actor_b.id)
        self.assertEqual(mismatch_workspace.deletion_reason, "Different actor event")
        self.assertEqual(db.session.get(WorkspaceMember, mismatch_membership_id).status, "active")
        self.assertEqual(Workspace.query.count(), initial_workspace_count)
        self.assertIsNotNone(db.session.get(Workspace, mismatch_workspace.id))
        self.assertIsNotNone(db.session.get(Customer, mismatch_customer_id))
        self.assertFalse(WorkspaceService.is_user_in_workspace(owner.id, mismatch_workspace.id))

        with app.test_request_context():
            set_authenticated_session(session, owner)
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = mismatch_workspace.id
            self.assertEqual(WorkspaceService.scoped_query(Customer).count(), 0)

        log = ActivityLog.query.filter_by(action="RESTORE_OWNER_WORKSPACE").one()
        self.assertIn(matching_workspace.name, log.description)
        self.assertIn(mismatch_workspace.name, log.description)
        self.assertIn("provenance không khớp", log.description)

    def test_multiple_sole_owner_workspaces_restore_without_touching_unrelated_workspace(self):
        target = self._create_user("multi_owner", "OWNER")
        unrelated_owner = self._create_user("unrelated_owner", "OWNER")
        workspace_a, membership_a = self._create_workspace(target, "Spa A", "spa-a")
        workspace_b, membership_b = self._create_workspace(target, "Spa B", "spa-b")
        unrelated_workspace, unrelated_membership = self._create_workspace(
            unrelated_owner,
            "Unrelated Spa",
            "unrelated-spa",
        )
        unrelated_customer = Customer(
            name="Unrelated Customer",
            phone="0904000001",
            workspace_id=unrelated_workspace.id,
        )
        db.session.add(unrelated_customer)
        db.session.commit()

        UserService.soft_delete_owner_workspace(self.approval_owner, target.id)

        self.assertIsNotNone(workspace_a.deleted_at)
        self.assertIsNotNone(workspace_b.deleted_at)
        self.assertIsNone(unrelated_workspace.deleted_at)
        self.assertIsNone(unrelated_owner.deleted_at)

        UserService.restore_owner_workspace(self.approval_owner, target.id)

        self.assertIsNone(workspace_a.deleted_at)
        self.assertIsNone(workspace_b.deleted_at)
        self.assertIsNone(unrelated_workspace.deleted_at)
        self.assertEqual(membership_a.status, "active")
        self.assertEqual(membership_b.status, "active")
        self.assertEqual(unrelated_membership.status, "active")
        self.assertEqual(db.session.get(Customer, unrelated_customer.id).id, unrelated_customer.id)

        with app.test_request_context():
            set_authenticated_session(session, target)
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace_a.id
            self.assertNotIn(
                unrelated_customer.id,
                [row.id for row in WorkspaceService.scoped_query(Customer).all()],
            )

    def test_owner_without_workspace_delete_restore_does_not_create_workspace(self):
        owner = self._create_user("owner_without_workspace", "OWNER")
        db.session.commit()
        initial_workspace_count = Workspace.query.count()

        UserService.soft_delete_owner_workspace(self.approval_owner, owner.id)
        self.assertIsNotNone(owner.deleted_at)
        UserService.restore_owner_workspace(self.approval_owner, owner.id)

        self.assertIsNone(owner.deleted_at)
        self.assertEqual(Workspace.query.count(), initial_workspace_count)
        delete_log = ActivityLog.query.filter_by(action="SOFT_DELETE_OWNER_WORKSPACE").one()
        restore_log = ActivityLog.query.filter_by(action="RESTORE_OWNER_WORKSPACE").one()
        self.assertIn("Không tìm thấy workspace active liên quan", delete_log.description)
        self.assertIn("Không có workspace deleted khớp provenance", restore_log.description)

    def test_restore_respects_all_approval_statuses(self):
        expected_active = {
            "active": True,
            "pending": False,
            "rejected": False,
            "disabled": False,
        }
        for index, (approval_status, is_active) in enumerate(expected_active.items(), start=1):
            owner = self._create_user(
                f"approval_status_owner_{index}",
                "OWNER",
                approval_status=approval_status,
                is_active=False,
            )
            owner.deleted_at = utc_now()
            owner.deleted_by_id = self.approval_owner.id
            db.session.commit()

            UserService.restore_owner_workspace(self.approval_owner, owner.id)

            self.assertEqual(owner.approval_status, approval_status)
            self.assertEqual(owner.is_active, is_active)
            self.assertEqual(owner.can_access_app, is_active)

    def test_soft_delete_and_restore_transactions_roll_back_atomically(self):
        owner = self._create_user("rollback_owner", "OWNER")
        workspace, _ = self._create_workspace(owner, "Rollback Spa", "rollback-spa")
        db.session.commit()

        with patch.object(UserService, "_log_user_action", side_effect=RuntimeError("log failure")):
            with self.assertRaises(RuntimeError):
                UserService.soft_delete_owner_workspace(self.approval_owner, owner.id)

        db.session.expire_all()
        self.assertIsNone(db.session.get(User, owner.id).deleted_at)
        self.assertIsNone(db.session.get(Workspace, workspace.id).deleted_at)
        self.assertIsNone(ActivityLog.query.filter_by(action="SOFT_DELETE_OWNER_WORKSPACE").first())

        UserService.soft_delete_owner_workspace(self.approval_owner, owner.id)
        with patch.object(UserService, "_log_user_action", side_effect=RuntimeError("log failure")):
            with self.assertRaises(RuntimeError):
                UserService.restore_owner_workspace(self.approval_owner, owner.id)

        db.session.expire_all()
        self.assertIsNotNone(db.session.get(User, owner.id).deleted_at)
        self.assertIsNotNone(db.session.get(Workspace, workspace.id).deleted_at)
        self.assertIsNone(ActivityLog.query.filter_by(action="RESTORE_OWNER_WORKSPACE").first())

    def test_security_boundaries_repeated_calls_and_get_routes(self):
        owner = self._create_user("security_target", "OWNER")
        normal_owner = self._create_user("normal_owner_actor", "OWNER")
        staff = self._create_user("staff_security_target", "STAFF")
        another_approval_owner = self._create_user("another_approval_owner", "APPROVAL_OWNER")
        db.session.commit()

        with self.assertRaises(PermissionDeniedException):
            UserService.soft_delete_owner_workspace(normal_owner, owner.id)
        with self.assertRaises(PermissionDeniedException):
            UserService.restore_owner_workspace(normal_owner, owner.id)
        with self.assertRaises(ValidationException):
            UserService.soft_delete_owner_workspace(self.approval_owner, staff.id)
        staff.deleted_at = utc_now()
        with self.assertRaises(ValidationException):
            UserService.restore_owner_workspace(self.approval_owner, staff.id)
        with self.assertRaises(ValidationException):
            UserService.soft_delete_owner_workspace(self.approval_owner, self.approval_owner.id)
        with self.assertRaises(ValidationException):
            UserService.soft_delete_owner_workspace(self.approval_owner, another_approval_owner.id)

        UserService.soft_delete_owner_workspace(self.approval_owner, owner.id)
        with self.assertRaises(ValidationException):
            UserService.soft_delete_owner_workspace(self.approval_owner, owner.id)
        UserService.restore_owner_workspace(self.approval_owner, owner.id)
        with self.assertRaises(ValidationException):
            UserService.restore_owner_workspace(self.approval_owner, owner.id)

        self._login_as(self.approval_owner)
        self.assertEqual(
            self.client.get(f"/approval/users/{owner.id}/soft-delete-owner-workspace").status_code,
            405,
        )
        self.assertEqual(
            self.client.get(f"/approval/users/{owner.id}/restore-owner-workspace").status_code,
            405,
        )

        self._login_as(normal_owner)
        response = self.client.post(f"/approval/users/{owner.id}/soft-delete-owner-workspace")
        self.assertEqual(response.status_code, 403)

    def test_route_ajax_listing_csrf_and_permanent_delete_guards(self):
        owner = self._create_user("route_security_owner", "OWNER")
        self._create_workspace(owner, "Route Security Spa", "route-security-spa")
        db.session.commit()
        self._login_as(self.approval_owner)

        delete_response = self.client.post(
            f"/approval/users/{owner.id}/soft-delete-owner-workspace",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(delete_response.get_json()["success"])
        self.assertIn(owner, UserService.list_approval_accounts(status="deleted").items)

        deleted_page = self.client.get("/approval/accounts?status=deleted")
        self.assertIn(b'name="csrf_token"', deleted_page.data)
        self.assertIn(b"restore-owner-workspace", deleted_page.data)
        self.assertIn(b"disabled", deleted_page.data)

        restore_response = self.client.post(
            f"/approval/users/{owner.id}/restore-owner-workspace",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(restore_response.status_code, 200)
        self.assertTrue(restore_response.get_json()["success"])
        self.assertIn(owner, UserService.list_approval_accounts(status="active").items)
        self.assertNotIn(owner, UserService.list_approval_accounts(status="deleted").items)

        # Task 6.6.8c permits execution routes only inside the gated Approval
        # Portal boundary; focused purge-route tests cover runtime access.
        approval_routes = {
            rule.rule: rule
            for rule in app.url_map.iter_rules()
            if rule.rule.startswith("/approval/")
        }
        confirmation_rule = approval_routes["/approval/purge-requests/<int:request_id>/execute/confirm"]
        execution_rule = approval_routes["/approval/purge-requests/<int:request_id>/execute"]
        self.assertEqual(confirmation_rule.endpoint, "approval.confirm_purge_request")
        self.assertIn("GET", confirmation_rule.methods)
        self.assertNotIn("POST", confirmation_rule.methods)
        self.assertEqual(execution_rule.endpoint, "approval.execute_purge_request")
        self.assertIn("POST", execution_rule.methods)
        self.assertNotIn("GET", execution_rule.methods)

        non_approval_execution_routes = [
            rule.rule
            for rule in app.url_map.iter_rules()
            if ("purge" in rule.rule and ("execute" in rule.rule or "confirm" in rule.rule))
            and not rule.rule.startswith("/approval/")
        ]
        self.assertEqual(non_approval_execution_routes, [])

    def test_staff_admin_account_lifecycle_remains_separate(self):
        staff = self._create_user("separate_staff", "STAFF")
        admin = self._create_user("separate_admin", "ADMIN")
        db.session.commit()

        for user in (staff, admin):
            with self.assertRaises(ValidationException):
                UserService.soft_delete_owner_workspace(self.approval_owner, user.id)
            UserService.soft_delete_account(self.approval_owner, user.id)
            with self.assertRaises(ValidationException):
                UserService.restore_owner_workspace(self.approval_owner, user.id)
            UserService.restore_account(self.approval_owner, user.id)
            self.assertIsNone(user.deleted_at)
            self.assertTrue(user.is_active)
