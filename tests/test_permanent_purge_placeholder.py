import os
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path


TEST_DB_FILE = Path(tempfile.gettempdir()) / f"spamanager_permanent_purge_placeholder_{uuid.uuid4().hex}.sqlite"
os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["SPAMANAGER_TEST_PROCESS"] = "1"

from app import app
from core.auth.constants import AUTH_SESSION_KEY
from core.exceptions import ValidationException
from extensions import db
from models.customer import Customer
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.appointment_service import AppointmentService
from services.customer_service import CustomerService
from services.invoice_service import InvoiceService
from services.recycle_bin_service import RecycleBinService
from services.service_service import ServiceService
from services.user_service import UserService
from services.workspace_service import WorkspaceService


class PermanentPurgePlaceholderTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        try:
            db.session.remove()
            db.engine.dispose()
        finally:
            cls.app_context.pop()
            if TEST_DB_FILE.exists():
                TEST_DB_FILE.unlink()

    def test_non_purge_ui_placeholders_remain_disabled_without_mutation_urls(self):
        for path in (
            "templates/user/index.html",
            "templates/recycle_bin/index.html",
        ):
            source = Path(path).read_text(encoding="utf-8")
            self.assertIn("Xóa vĩnh viễn", source)
            self.assertIn("disabled", source)
            self.assertNotIn("/purge", source)
            self.assertNotIn("/permanent-delete", source)
            self.assertNotIn("form action=\"/purge", source)
            self.assertNotIn("href=\"/purge", source)

        approval_source = Path("templates/approval/accounts.html").read_text(encoding="utf-8")
        self.assertIn("Xóa vĩnh viễn qua yêu cầu", approval_source)
        self.assertNotIn("Xóa vĩnh viễn (Chưa triển khai)", approval_source)

    def test_common_account_workspace_and_business_purge_routes_are_unavailable(self):
        client = app.test_client()
        for path in (
            "/approval/users/1/purge",
            "/approval/users/1/permanent-delete",
            "/approval/workspaces/1/purge",
            "/users/1/purge",
            "/recycle-bin/delete/Customer/1",
        ):
            with self.subTest(path=path):
                self.assertEqual(client.post(path).status_code, 404)
                self.assertEqual(client.get(path).status_code, 404)

    def test_nonexistent_purge_routes_have_no_side_effect_after_database_requery(self):
        approver = User(
            username=f"purge_view_approver_{uuid.uuid4().hex[:8]}",
            email=f"purge_view_approver_{uuid.uuid4().hex[:8]}@example.com",
            full_name="Approval Owner",
            role="APPROVAL_OWNER",
            is_active=True,
            approval_status="active",
        )
        owner = User(
            username=f"purge_view_owner_{uuid.uuid4().hex[:8]}",
            email=f"purge_view_owner_{uuid.uuid4().hex[:8]}@example.com",
            full_name="Workspace Owner",
            role="OWNER",
            is_active=True,
            approval_status="active",
        )
        target = User(
            username=f"purge_view_target_{uuid.uuid4().hex[:8]}",
            email=f"purge_view_target_{uuid.uuid4().hex[:8]}@example.com",
            full_name="Deleted Staff",
            role="STAFF",
            is_active=False,
            approval_status="active",
            deleted_at=datetime(2026, 7, 10, 9, 0),
        )
        approver.set_password("Password123!")
        owner.set_password("Password123!")
        target.set_password("Password123!")
        workspace = Workspace(
            name="Purge Placeholder Workspace",
            slug=f"purge-placeholder-{uuid.uuid4().hex}",
            status="active",
        )
        db.session.add_all([approver, owner, target, workspace])
        db.session.flush()
        target.deleted_by_id = approver.id
        owner_membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=owner.id,
            role="owner",
            status="active",
        )
        target_membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=target.id,
            role="staff",
            status="removed",
            removed_at=datetime(2026, 7, 10, 9, 0),
            removed_by_id=owner.id,
            removal_reason="placeholder test",
        )
        customer = Customer(
            name="Purge Placeholder Customer",
            workspace_id=workspace.id,
            deleted_at=datetime(2026, 7, 10, 9, 0),
            deleted_by="placeholder-owner",
        )
        db.session.add_all([owner_membership, target_membership, customer])
        db.session.commit()
        ids = {
            "approver": approver.id,
            "owner": owner.id,
            "target": target.id,
            "workspace": workspace.id,
            "customer": customer.id,
        }

        try:
            client = app.test_client()
            with client.session_transaction() as session:
                session[AUTH_SESSION_KEY] = ids["approver"]
            previous_purge_ui = app.config.get("PERMANENT_PURGE_UI_ENABLED")
            app.config["PERMANENT_PURGE_UI_ENABLED"] = True
            approval_response = client.get("/approval/accounts?status=deleted")
            app.config["PERMANENT_PURGE_UI_ENABLED"] = previous_purge_ui
            self.assertEqual(approval_response.status_code, 200)
            approval_html = approval_response.get_data(as_text=True)
            self.assertIn("Xóa vĩnh viễn qua yêu cầu", approval_html)
            self.assertIn("/approval/purge-requests", approval_html)
            self.assertNotIn("/permanent-delete", approval_html)

            with client.session_transaction() as session:
                session[AUTH_SESSION_KEY] = ids["owner"]
                session["current_workspace_id"] = ids["workspace"]
                session["_enable_workspace_isolation"] = True
            user_response = client.get("/users")
            self.assertEqual(user_response.status_code, 200)
            user_html = user_response.get_data(as_text=True)
            self.assertIn("Xóa vĩnh viễn", user_html)
            self.assertIn("disabled", user_html)
            self.assertNotIn("/purge", user_html)
            self.assertNotIn("/permanent-delete", user_html)

            recycle_response = client.get("/recycle-bin")
            self.assertEqual(recycle_response.status_code, 200)
            recycle_html = recycle_response.get_data(as_text=True)
            self.assertIn("Xóa vĩnh viễn", recycle_html)
            self.assertIn("disabled", recycle_html)
            self.assertNotIn("/recycle-bin/delete/", recycle_html)

            with self.subTest(route="representative purge routes"):
                for path in (
                    f"/approval/users/{ids['target']}/purge",
                    f"/approval/workspaces/{ids['workspace']}/purge",
                    f"/users/{ids['target']}/purge",
                    f"/recycle-bin/delete/Customer/{ids['customer']}",
                ):
                    self.assertEqual(client.post(path).status_code, 404)

            db.session.expire_all()
            persisted_target = db.session.get(User, ids["target"])
            persisted_workspace = db.session.get(Workspace, ids["workspace"])
            persisted_customer = db.session.get(Customer, ids["customer"])
            self.assertIsNotNone(persisted_target)
            self.assertIsNotNone(persisted_workspace)
            self.assertIsNotNone(persisted_customer)
            self.assertFalse(persisted_target.is_active)
            self.assertIsNotNone(persisted_target.deleted_at)
            self.assertIsNotNone(persisted_customer.deleted_at)
        finally:
            db.session.rollback()
            db.session.delete(db.session.get(Customer, ids["customer"]))
            db.session.delete(db.session.get(WorkspaceMember, target_membership.id))
            db.session.delete(db.session.get(WorkspaceMember, owner_membership.id))
            db.session.delete(db.session.get(Workspace, ids["workspace"]))
            for user_id in (ids["target"], ids["owner"], ids["approver"]):
                db.session.delete(db.session.get(User, user_id))
            db.session.commit()

    def test_no_account_workspace_purge_service_is_exposed(self):
        for service in (UserService, WorkspaceService):
            for method_name in (
                "purge_account",
                "permanently_delete_account",
                "purge_owner_workspace",
                "hard_delete_workspace",
            ):
                self.assertFalse(hasattr(service, method_name))

    def test_business_purge_entry_points_remain_fail_closed(self):
        for method in (
            CustomerService.permanent_delete,
            ServiceService.permanent_delete_service,
            AppointmentService.permanent_delete,
            InvoiceService.permanent_delete,
        ):
            with self.subTest(method=method.__name__):
                with self.assertRaises(ValidationException):
                    method(1)
        with self.assertRaises(ValidationException):
            RecycleBinService.cleanup_old_records()
