import os
import re
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, datetime
from pathlib import Path


TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_business_permanent_delete_disabled.sqlite"
if TEST_DB_FILE.exists():
    TEST_DB_FILE.unlink()

os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"

from app import app
from core.auth.constants import AUTH_SESSION_KEY
from core.exceptions import ValidationException
from extensions import db
from models.activity_log import ActivityLog
from models.appointment import Appointment
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from models.service import Service
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.appointment_service import AppointmentService
from services.customer_service import CustomerService
from services.invoice_service import InvoiceService
from services.recycle_bin_service import RecycleBinRegistry, RecycleBinService
from services.service_service import ServiceService


class BusinessPermanentDeleteDisabledTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        cls.app_context.pop()
        if TEST_DB_FILE.exists():
            try:
                TEST_DB_FILE.unlink()
            except PermissionError:
                pass

    def setUp(self):
        db.session.rollback()
        self._clear_database()
        self.client = app.test_client()
        self.workspace = Workspace(name="Permanent Delete Safety", slug="permanent-delete-safety")
        self.other_workspace = Workspace(name="Other Workspace", slug="other-workspace")
        db.session.add_all([self.workspace, self.other_workspace])
        db.session.flush()

        self.users = {}
        self.user_ids = {}
        for role in ("OWNER", "ADMIN", "STAFF", "APPROVAL_OWNER"):
            user = User(
                username=f"disabled_{role.lower()}",
                email=f"disabled_{role.lower()}@example.com",
                full_name=role,
                role=role,
                is_active=True,
                approval_status="active",
            )
            user.set_password("Password123!")
            db.session.add(user)
            db.session.flush()
            self.users[role] = user
            self.user_ids[role] = user.id
            if role != "APPROVAL_OWNER":
                db.session.add(WorkspaceMember(
                    workspace_id=self.workspace.id,
                    user_id=user.id,
                    role=role.lower(),
                    status="active",
                ))

        self.customer = Customer(name="Active Customer", workspace_id=self.workspace.id)
        self.service = Service(name="Active Service", price=100000, workspace_id=self.workspace.id)
        self.other_customer = Customer(name="Other Customer", workspace_id=self.other_workspace.id)
        db.session.add_all([self.customer, self.service, self.other_customer])
        db.session.flush()

        self.appointment = Appointment(
            customer_id=self.customer.id,
            service_id=self.service.id,
            appointment_time=datetime(2026, 7, 10, 9, 0),
            workspace_id=self.workspace.id,
        )
        self.invoice = Invoice(
            customer_id=self.customer.id,
            invoice_date=date(2026, 7, 10),
            total_amount=100000,
            workspace_id=self.workspace.id,
        )
        db.session.add_all([self.appointment, self.invoice])
        db.session.flush()
        self.invoice_detail = InvoiceDetail(
            invoice_id=self.invoice.id,
            service_id=self.service.id,
            price=100000,
            quantity=1,
        )
        db.session.add(self.invoice_detail)
        db.session.commit()
        self.customer_id = self.customer.id
        self.service_id = self.service.id
        self.other_customer_id = self.other_customer.id
        self.appointment_id = self.appointment.id
        self.invoice_id = self.invoice.id
        self.invoice_detail_id = self.invoice_detail.id

    def tearDown(self):
        db.session.rollback()
        self._clear_database()

    @staticmethod
    def _clear_database():
        db.session.remove()
        ActivityLog.query.delete()
        InvoiceDetail.query.delete()
        Invoice.query.delete()
        Appointment.query.delete()
        Customer.query.delete()
        Service.query.delete()
        WorkspaceMember.query.delete()
        Workspace.query.delete()
        User.query.delete()
        db.session.commit()
        db.session.remove()

    def _login_as(self, role):
        with self.client.session_transaction() as session:
            session[AUTH_SESSION_KEY] = self.user_ids[role]
            session["current_workspace_id"] = self.workspace.id
            session["_enable_workspace_isolation"] = True

    def _csrf_token(self):
        response = self.client.get("/recycle-bin")
        match = re.search(r'name="csrf-token" content="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(match)
        return match.group(1)

    def _post_legacy_delete(self, item_type, item_id, include_csrf=True, confirmation_phrase=None):
        headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
        if include_csrf:
            headers["X-CSRFToken"] = self._csrf_token()
        return self.client.post(
            f"/recycle-bin/delete/{item_type}/{item_id}",
            headers=headers,
        )

    def _assert_fixture_rows_exist(self):
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(Customer, self.customer_id))
        self.assertIsNotNone(db.session.get(Service, self.service_id))
        self.assertIsNotNone(db.session.get(Appointment, self.appointment_id))
        self.assertIsNotNone(db.session.get(Invoice, self.invoice_id))
        self.assertIsNotNone(db.session.get(InvoiceDetail, self.invoice_detail_id))

    def test_permanent_delete_route_requires_manager_and_csrf(self):
        self._login_as("OWNER")
        response = self._post_legacy_delete(
            "Customer", self.customer_id, include_csrf=False
        )
        self.assertEqual(response.status_code, 400)
        self._assert_fixture_rows_exist()


    def test_legacy_route_has_no_side_effect_without_csrf(self):
        self._login_as("OWNER")
        response = self._post_legacy_delete("Customer", self.customer_id, include_csrf=False)
        self.assertEqual(response.status_code, 400)
        self._assert_fixture_rows_exist()

    def test_active_and_soft_deleted_rows_are_protected_by_direct_services(self):
        methods = (
            (CustomerService.permanent_delete, self.customer),
            (ServiceService.permanent_delete_service, self.service),
            (AppointmentService.permanent_delete, self.appointment),
            (InvoiceService.permanent_delete, self.invoice),
        )
        for method, record in methods:
            with self.subTest(method=method.__name__, state="active"):
                with self.assertRaisesRegex(ValidationException, "chưa được hỗ trợ"):
                    method(record.id, actor="disabled_owner")

        lifecycle_time = datetime(2026, 7, 1, 8, 0)
        for _, record in methods:
            record.deleted_at = lifecycle_time
            record.deleted_by = "disabled_owner"
        db.session.commit()

        for method, record in methods:
            with self.subTest(method=method.__name__, state="deleted"):
                with self.assertRaisesRegex(ValidationException, "chưa được hỗ trợ"):
                    method(record.id, actor="disabled_owner")

        self._assert_fixture_rows_exist()
        for _, record in methods:
            refreshed = db.session.get(type(record), record.id)
            self.assertEqual(refreshed.deleted_at, lifecycle_time)
            self.assertEqual(refreshed.deleted_by, "disabled_owner")
        self.assertEqual(ActivityLog.query.filter_by(action="PERMANENT_DELETE").count(), 0)

    def test_registry_and_cleanup_fail_closed_without_mutation(self):
        for config in RecycleBinRegistry.get_all().values():
            self.assertNotIn("permanent_delete_func", config)

        with self.assertRaisesRegex(ValidationException, "Tự động xóa vĩnh viễn"):
            RecycleBinService.cleanup_old_records(days=0)

        self._assert_fixture_rows_exist()
        self.assertEqual(ActivityLog.query.filter_by(action="PERMANENT_DELETE").count(), 0)

    def test_cross_workspace_record_is_not_mutated(self):
        self._login_as("OWNER")
        response = self._post_legacy_delete("Customer", self.other_customer_id)
        self.assertEqual(response.status_code, 404)
        db.session.expire_all()
        other_customer = db.session.get(Customer, self.other_customer_id)
        self.assertIsNotNone(other_customer)
        self.assertIsNone(other_customer.deleted_at)

    @unittest.skip("superseded by the permanent-delete dependency-state contract")
    def test_recycle_bin_ui_keeps_restore_and_only_disabled_delete_placeholder(self):
        self.customer.deleted_at = datetime(2026, 7, 1, 8, 0)
        self.customer.deleted_by = "disabled_owner"
        db.session.commit()
        self._login_as("OWNER")

        response = self.client.get("/recycle-bin")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        template = Path("templates/recycle_bin/index.html").read_text(encoding="utf-8")
        self.assertIn("Xóa vĩnh viễn hiện chưa được hỗ trợ", html)
        self.assertRegex(html, r"<button[^>]*disabled[^>]*>\s*<i[^>]*></i> Xóa vĩnh viễn")
        self.assertNotIn("/recycle-bin/delete/", template)
        self.assertNotIn("btn-delete-item", template)
        self.assertNotIn("btn-confirm-delete", template)
        self.assertIn("btn-restore-item", template)
        self.assertIn("/recycle-bin/restore/", template)

    def test_recycle_bin_ui_keeps_restore_and_dependency_delete_state(self):
        self.customer.deleted_at = datetime(2026, 7, 1, 8, 0)
        self.customer.deleted_by = "disabled_owner"
        db.session.commit()
        self._login_as("OWNER")
        response = self.client.get("/recycle-bin")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        template = Path("templates/recycle_bin/index.html").read_text(encoding="utf-8")
        self.assertNotIn("permanent_delete_phrase", template)
        self.assertNotIn("permanent-delete-confirmation", template)
        self.assertNotIn("permanent-delete-phrase", template)
        self.assertIn("btn-permanent-delete-item", template)
        self.assertIn("btn-confirm-permanent-delete", template)
        self.assertIn("/recycle-bin/delete/", template)
        self.assertIn("btn-restore-item", template)
        self.assertIn("disabled", html)
        self.assertIn("Đặt lại bộ lọc", template)

    def test_customer_restore_regression(self):
        self.customer.deleted_at = datetime(2026, 7, 1, 8, 0)
        self.customer.deleted_by = "disabled_owner"
        db.session.commit()
        self._login_as("OWNER")

        response = self.client.post(
            f"/recycle-bin/restore/Customer/{self.customer_id}",
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": self._csrf_token(),
            },
        )
        self.assertEqual(response.status_code, 200)
        db.session.expire_all()
        customer = db.session.get(Customer, self.customer_id)
        self.assertIsNotNone(customer)
        self.assertIsNone(customer.deleted_at)
        self.assertIsNone(customer.deleted_by)

    def test_soft_deleted_appointment_and_invoice_are_deleted_with_audit(self):
        self._login_as("OWNER")
        lifecycle_time = datetime(2026, 7, 1, 8, 0)
        self.appointment.deleted_at = lifecycle_time
        self.invoice.deleted_at = lifecycle_time
        db.session.commit()

        appointment_response = self._post_legacy_delete(
            "Appointment",
            self.appointment_id,
            confirmation_phrase=f"XÓA VĨNH VIỄN LỊCH HẸN {self.appointment_id}",
        )
        self.assertEqual(appointment_response.status_code, 200)
        self.assertIsNone(db.session.get(Appointment, self.appointment_id))

        invoice_response = self._post_legacy_delete(
            "Invoice",
            self.invoice_id,
            confirmation_phrase=f"XÓA VĨNH VIỄN HÓA ĐƠN {self.invoice_id}",
        )
        self.assertEqual(invoice_response.status_code, 200)
        self.assertIsNone(db.session.get(Invoice, self.invoice_id))
        self.assertIsNone(db.session.get(InvoiceDetail, self.invoice_detail_id))
        self.assertEqual(
            ActivityLog.query.filter_by(action="PERMANENT_DELETE").count(),
            2,
        )

    def test_audit_failure_rolls_back_permanent_delete(self):
        self._login_as("OWNER")
        self.appointment.deleted_at = datetime(2026, 7, 1, 8, 0)
        db.session.commit()
        with patch(
            "services.recycle_bin_service.ActivityLogService.write_log",
            return_value=False,
        ):
            response = self._post_legacy_delete(
                "Appointment",
                self.appointment_id,
                confirmation_phrase=f"XÓA VĨNH VIỄN LỊCH HẸN {self.appointment_id}",
            )
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(db.session.get(Appointment, self.appointment_id))


if __name__ == "__main__":
    unittest.main()
