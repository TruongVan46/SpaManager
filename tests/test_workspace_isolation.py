import os
import shutil
import tempfile
import unittest
from pathlib import Path

# SETUP ENVIRONMENT VARIABLES BEFORE IMPORTING APP OR MODELS
test_db = Path(tempfile.gettempdir()) / "spamanager_isolation_test.sqlite"
if test_db.exists():
    test_db.unlink()
os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{test_db.as_posix()}"

from flask import session
from app import app
from extensions import db
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from models.customer import Customer
from models.service import Service
from models.appointment import Appointment
from models.invoice import Invoice
from services.customer_service import CustomerService
from services.service_service import ServiceService
from services.appointment_service import AppointmentService
from services.invoice_service import InvoiceService
from services.dashboard_statistics_service import DashboardStatisticsService
from core.exceptions import ValidationException, NotFoundException
from core.cache import dashboard_cache

class WorkspaceIsolationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_db = test_db
        cls.app_context = app.app_context()
        cls.app_context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        if cls.test_db.exists():
            cls.test_db.unlink()
        cls.app_context.pop()

    def setUp(self):
        db.session.rollback()
        # Clean business data tables
        Appointment.query.delete()
        Invoice.query.delete()
        Customer.query.delete()
        Service.query.delete()
        WorkspaceMember.query.delete()
        Workspace.query.delete()
        User.query.delete()
        db.session.commit()
        dashboard_cache.clear()

        # Create 2 mock workspaces
        self.workspace_a = Workspace(name="Workspace A", slug="workspace-a", status="active")
        self.workspace_b = Workspace(name="Workspace B", slug="workspace-b", status="active")
        db.session.add(self.workspace_a)
        db.session.add(self.workspace_b)
        db.session.flush()

        # Create 2 users with full_name to satisfy PostgreSQL / DB constraints
        self.user_a = User(username="user_a", full_name="User A", email="a@test.com", is_active=True, role="OWNER")
        self.user_a.set_password("Password123!")
        self.user_b = User(username="user_b", full_name="User B", email="b@test.com", is_active=True, role="OWNER")
        self.user_b.set_password("Password123!")
        db.session.add(self.user_a)
        db.session.add(self.user_b)
        db.session.flush()

        # Add memberships
        self.member_a = WorkspaceMember(workspace_id=self.workspace_a.id, user_id=self.user_a.id, role="owner", status="active")
        self.member_b = WorkspaceMember(workspace_id=self.workspace_b.id, user_id=self.user_b.id, role="owner", status="active")
        db.session.add(self.member_a)
        db.session.add(self.member_b)
        db.session.commit()

    def test_customer_isolation(self):
        """
        Verify Customer isolation:
        - workspace A only sees customer A.
        - workspace A cannot get customer B by get_by_id.
        - create customer auto-assigns workspace_id A.
        """
        with app.test_request_context():
            # Workspace A context
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.user_a.id
            session["user_id"] = self.user_a.id

            cust_a = CustomerService.create(name="Customer A", phone="0901111111", email="a@cust.com")
            self.assertEqual(cust_a.workspace_id, self.workspace_a.id)

            # Retrieve list
            self.assertEqual(len(CustomerService.get_all()), 1)
            self.assertEqual(CustomerService.get_all()[0].id, cust_a.id)

        with app.test_request_context():
            # Workspace B context
            session["current_workspace_id"] = self.workspace_b.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.user_b.id
            session["user_id"] = self.user_b.id

            cust_b = CustomerService.create(name="Customer B", phone="0902222222", email="b@cust.com")
            self.assertEqual(cust_b.workspace_id, self.workspace_b.id)

            # Retrieve list under B
            self.assertEqual(len(CustomerService.get_all()), 1)
            self.assertEqual(CustomerService.get_all()[0].id, cust_b.id)

            # Try to get customer A under workspace B context
            self.assertIsNone(CustomerService.get_by_id(cust_a.id))

    def test_service_isolation(self):
        """
        Verify Service isolation:
        - workspace A only sees service A.
        - workspace A cannot get service B.
        - create service auto-assigns workspace_id A.
        """
        with app.test_request_context():
            # Workspace A context
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.user_a.id
            session["user_id"] = self.user_a.id

            serv_a = ServiceService.create_service({"name": "Service A", "price": 100000, "duration": 60})
            self.assertEqual(serv_a.workspace_id, self.workspace_a.id)

            self.assertEqual(len(ServiceService.get_all_services()), 1)

        with app.test_request_context():
            # Workspace B context
            session["current_workspace_id"] = self.workspace_b.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.user_b.id
            session["user_id"] = self.user_b.id

            serv_b = ServiceService.create_service({"name": "Service B", "price": 200000, "duration": 45})
            self.assertEqual(serv_b.workspace_id, self.workspace_b.id)

            self.assertEqual(len(ServiceService.get_all_services()), 1)
            self.assertIsNone(ServiceService.get_service_by_id(serv_a.id))

    def test_appointment_isolation_and_cross_linkage(self):
        """
        Verify Appointment isolation & validation:
        - workspace A only sees appointment A.
        - creating appointment with customer/service of workspace B throws ValidationException.
        """
        # Create resources
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.user_a.id
            session["user_id"] = self.user_a.id

            cust_a = CustomerService.create(name="Customer A", phone="0901111111", email="a@cust.com")
            serv_a = ServiceService.create_service({"name": "Service A", "price": 100000, "duration": 60})
            appt_a = AppointmentService.create_appointment(
                customer_id=cust_a.id,
                service_id=serv_a.id,
                appointment_date="2026-08-01",
                appointment_time="10:00"
            )
            self.assertEqual(appt_a.workspace_id, self.workspace_a.id)

        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_b.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.user_b.id
            session["user_id"] = self.user_b.id

            cust_b = CustomerService.create(name="Customer B", phone="0902222222", email="b@cust.com")
            serv_b = ServiceService.create_service({"name": "Service B", "price": 200000, "duration": 45})

            # Check isolation of appointment A
            self.assertEqual(len(AppointmentService.get_all()), 0)
            self.assertIsNone(AppointmentService.get_by_id(appt_a.id))

            # Cross-workspace customer link must fail
            with self.assertRaises(ValidationException):
                AppointmentService.create_appointment(
                    customer_id=cust_a.id,
                    service_id=serv_b.id,
                    appointment_date="2026-08-01",
                    appointment_time="11:00"
                )

            # Cross-workspace service link must fail
            with self.assertRaises(ValidationException):
                AppointmentService.create_appointment(
                    customer_id=cust_b.id,
                    service_id=serv_a.id,
                    appointment_date="2026-08-01",
                    appointment_time="11:00"
                )

    def test_invoice_isolation_and_cross_linkage(self):
        """
        Verify Invoice isolation & validation:
        - workspace A only sees invoice A.
        - creating invoice with customer/service of workspace B throws ValidationException.
        """
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.user_a.id
            session["user_id"] = self.user_a.id

            cust_a = CustomerService.create(name="Customer A", phone="0901111111", email="a@cust.com")
            serv_a = ServiceService.create_service({"name": "Service A", "price": 100000, "duration": 60})
            inv_a = InvoiceService.create_invoice({
                "customer_id": cust_a.id,
                "payment_method": "cash",
                "items": [{"service_id": serv_a.id, "quantity": 1}]
            })
            self.assertEqual(inv_a.workspace_id, self.workspace_a.id)

        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_b.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.user_b.id
            session["user_id"] = self.user_b.id

            cust_b = CustomerService.create(name="Customer B", phone="0902222222", email="b@cust.com")
            serv_b = ServiceService.create_service({"name": "Service B", "price": 200000, "duration": 45})

            # Check invoice A isolation
            self.assertEqual(len(InvoiceService.get_all()), 0)
            self.assertIsNone(InvoiceService.get_by_id(inv_a.id))

            # Cross-workspace customer link must fail
            with self.assertRaises(ValidationException):
                InvoiceService.create_invoice({
                    "customer_id": cust_a.id,
                    "payment_method": "cash",
                    "items": [{"service_id": serv_b.id, "quantity": 1}]
                })

            # Cross-workspace service link must fail
            with self.assertRaises(ValidationException):
                InvoiceService.create_invoice({
                    "customer_id": cust_b.id,
                    "payment_method": "cash",
                    "items": [{"service_id": serv_a.id, "quantity": 1}]
                })

    def test_dashboard_statistics_isolation(self):
        """
        Verify Dashboard statistics:
        - counts, revenue & cache key are correctly scoped by workspace.
        """
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.user_a.id
            session["user_id"] = self.user_a.id

            cust_a = CustomerService.create(name="Customer A", phone="0901111111", email="a@cust.com")
            serv_a = ServiceService.create_service({"name": "Service A", "price": 100000, "duration": 60})
            InvoiceService.create_invoice({
                "customer_id": cust_a.id,
                "payment_method": "cash",
                "items": [{"service_id": serv_a.id, "quantity": 1}]
            })

            dashboard_cache.clear()
            data_a = DashboardStatisticsService.get_dashboard_data()
            self.assertEqual(data_a["stats"]["customers"]["value"], "1")
            self.assertEqual(data_a["services_count"], 1)
            self.assertEqual(data_a["stats"]["revenue"]["value"], "100.000đ")

        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_b.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.user_b.id
            session["user_id"] = self.user_b.id

            dashboard_cache.clear()
            data_b = DashboardStatisticsService.get_dashboard_data()
            self.assertEqual(data_b["stats"]["customers"]["value"], "0")
            self.assertEqual(data_b["services_count"], 0)
            self.assertEqual(data_b["stats"]["revenue"]["value"], "0đ")

    def test_no_current_workspace_fail_closed(self):
        """
        Verify Fail-Closed Principle:
        - when workspace context is missing/invalid, production-like requests return empty queries
          and do not leak any global data.
        """
        # Set database records
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.user_a.id
            session["user_id"] = self.user_a.id
            CustomerService.create(name="Secret Customer", phone="0909999999", email="secret@spa.com")

        # Simulate no current workspace but isolation enabled (production behavior simulated)
        with app.test_request_context():
            session["current_workspace_id"] = None
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = None
            session["user_id"] = None

            # Retrieve lists - must return empty
            self.assertEqual(len(CustomerService.get_all()), 0)
            self.assertEqual(len(ServiceService.get_all_services()), 0)
            self.assertEqual(len(AppointmentService.get_all()), 0)
            self.assertEqual(len(InvoiceService.get_all()), 0)
