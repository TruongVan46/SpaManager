from tests.session_helpers import set_authenticated_session
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_activity_log_workspace_test.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_activity_log_workspace_media"
os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["PERSISTENT_ROOT"] = TEST_MEDIA_ROOT.as_posix()

from app import app
from extensions import db
from flask import session
from models.activity_log import ActivityLog
from models.appointment import Appointment
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from models.service import Service
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.activity_log_service import ActivityLogService


class ActivityLogWorkspaceAttributionTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        if TEST_DB_FILE.exists():
            TEST_DB_FILE.unlink()
        if TEST_MEDIA_ROOT.exists():
            shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        cls.app_context.pop()

    def setUp(self):
        ActivityLog.query.delete()
        InvoiceDetail.query.delete()
        Invoice.query.delete()
        Appointment.query.delete()
        Customer.query.delete()
        Service.query.delete()
        WorkspaceMember.query.delete()
        User.query.delete()
        Workspace.query.delete()
        db.session.commit()
        self.client = app.test_client()

    def _workspace_owner(self, slug):
        workspace = Workspace(name=slug, slug=slug, status="active")
        owner = User(username=f"owner_{slug}", email=f"{slug}@example.test", role="OWNER", full_name=slug)
        owner.set_password("Password123!")
        db.session.add_all([workspace, owner])
        db.session.flush()
        db.session.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner", status="active"))
        db.session.commit()
        return workspace, owner

    def _use_workspace(self, user, workspace):
        with self.client.session_transaction() as client_session:
            set_authenticated_session(client_session, user.id)
            client_session["current_workspace_id"] = workspace.id
            client_session["_enable_workspace_isolation"] = True

    def test_write_log_uses_trusted_workspace_and_allows_explicit_system_null(self):
        workspace, owner = self._workspace_owner("workspace-a")
        with app.test_request_context():
            set_authenticated_session(session, owner.id)
            session["current_workspace_id"] = workspace.id
            self.assertTrue(ActivityLogService.write_log("Customer", "CREATE", "workspace log"))

        workspace_log = ActivityLog.query.filter_by(description="workspace log").one()
        self.assertEqual(workspace_log.workspace_id, workspace.id)

        self.assertTrue(ActivityLogService.write_log("System", "CUSTOM", "system log", workspace_id=None))
        system_log = ActivityLog.query.filter_by(description="system log").one()
        self.assertIsNone(system_log.workspace_id)

    def test_activity_log_scope_uses_workspace_id_not_membership_inference(self):
        workspace_a, owner_a = self._workspace_owner("workspace-a")
        workspace_b, owner_b = self._workspace_owner("workspace-b")
        db.session.add_all([
            ActivityLog(module="Customer", action="CREATE", description="A log", user_id=owner_a.id, workspace_id=workspace_a.id),
            ActivityLog(module="Customer", action="CREATE", description="B log", user_id=owner_a.id, workspace_id=workspace_b.id),
            ActivityLog(module="System", action="CUSTOM", description="Legacy log", user_id=None, workspace_id=None),
        ])
        db.session.commit()
        db.session.add(WorkspaceMember(workspace_id=workspace_b.id, user_id=owner_a.id, role="staff", status="active"))
        db.session.commit()

        with app.test_request_context():
            set_authenticated_session(session, owner_a.id)
            session["current_workspace_id"] = workspace_a.id
            logs_a = ActivityLogService.get_filtered_logs().items
            self.assertEqual([log.description for log in logs_a], ["A log"])

            session["current_workspace_id"] = workspace_b.id
            logs_b = ActivityLogService.get_filtered_logs().items
            self.assertEqual([log.description for log in logs_b], ["B log"])

    def test_activity_log_http_route_excludes_foreign_and_null_logs(self):
        workspace_a, owner_a = self._workspace_owner("workspace-a")
        workspace_b, owner_b = self._workspace_owner("workspace-b")
        db.session.add_all([
            ActivityLog(module="Customer", action="CREATE", description="A visible", user_id=owner_a.id, workspace_id=workspace_a.id),
            ActivityLog(module="Customer", action="CREATE", description="B secret", user_id=owner_b.id, workspace_id=workspace_b.id),
            ActivityLog(module="System", action="CUSTOM", description="Legacy secret", workspace_id=None),
        ])
        db.session.commit()
        self._use_workspace(owner_a, workspace_a)

        response = self.client.get(f"/activity-logs?workspace_id={workspace_b.id}")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("A visible", body)
        self.assertNotIn("B secret", body)
        self.assertNotIn("Legacy secret", body)

    def test_read_only_foreign_workspace_routes_fail_closed(self):
        workspace_a, owner_a = self._workspace_owner("workspace-a")
        workspace_b, _ = self._workspace_owner("workspace-b")
        customer = Customer(name="Foreign Customer", phone="0999999999", email="foreign@example.test", workspace_id=workspace_b.id)
        service = Service(name="Foreign Service", price=100, workspace_id=workspace_b.id)
        db.session.add_all([customer, service])
        db.session.flush()
        appointment = Appointment(
            customer_id=customer.id,
            service_id=service.id,
            appointment_time=datetime(2026, 7, 11, 10, 0),
            workspace_id=workspace_b.id,
        )
        invoice = Invoice(
            customer_id=customer.id,
            invoice_date=datetime(2026, 7, 11).date(),
            subtotal=100,
            total_amount=100,
            workspace_id=workspace_b.id,
        )
        db.session.add_all([appointment, invoice])
        db.session.flush()
        db.session.add(InvoiceDetail(invoice_id=invoice.id, service_id=service.id, price=100, quantity=1))
        db.session.commit()
        self._use_workspace(owner_a, workspace_a)

        urls = [
            f"/customers/{customer.id}",
            f"/customers/{customer.id}/edit",
            f"/services/edit/{service.id}",
            f"/appointments/detail/{appointment.id}",
            f"/appointments/edit/{appointment.id}",
            f"/invoices/{invoice.id}",
            f"/invoices/print/{invoice.id}",
            f"/statistics/customer/{customer.id}",
            f"/statistics/service/{service.id}",
            f"/recycle-bin/info/Customer/{customer.id}",
        ]
        for url in urls:
            response = self.client.get(url, follow_redirects=False)
            self.assertIn(response.status_code, (200, 302, 404), url)
            body = response.get_data(as_text=True)
            self.assertNotIn("Foreign Customer", body, url)
            self.assertNotIn("Foreign Service", body, url)
            self.assertNotIn("0999999999", body, url)


if __name__ == "__main__":
    unittest.main()
