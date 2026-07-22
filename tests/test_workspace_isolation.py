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
from models.account_purge import UserCreationProvenance
from models.workspace import Workspace, WorkspaceMember
from models.customer import Customer
from models.service import Service
from models.appointment import Appointment
from models.invoice import Invoice
from services.customer_service import CustomerService
from services.service_service import ServiceService
from services.appointment_service import AppointmentService
from services.invoice_service import InvoiceService
from services.user_service import UserService
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


class TestWorkspaceUserManagement(unittest.TestCase):
    """
    Task 6.5.6 — Workspace-scoped user management tests with strict role creation policies.

    Uses _enable_workspace_isolation = True to simulate production isolation.
    """

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

    def setUp(self):
        db.session.rollback()
        # Clean all tables (order matters for FK constraints)
        WorkspaceMember.query.delete()
        UserCreationProvenance.query.delete()
        User.query.filter(User.role != "APPROVAL_OWNER").delete()
        Workspace.query.delete()
        db.session.commit()

        # Two workspaces
        self.workspace_a = Workspace(name="Workspace A", slug="ws-a-um", status="active")
        self.workspace_b = Workspace(name="Workspace B", slug="ws-b-um", status="active")
        db.session.add_all([self.workspace_a, self.workspace_b])
        db.session.flush()

        # Owners for each workspace
        self.owner_a = User(username="owner_a", full_name="Owner A", email="oa@test.com", is_active=True, role="OWNER")
        self.owner_a.set_password("Password123!")
        self.owner_b = User(username="owner_b", full_name="Owner B", email="ob@test.com", is_active=True, role="OWNER")
        self.owner_b.set_password("Password123!")
        # An ADMIN belonging to workspace_a
        self.admin_a = User(username="admin_a", full_name="Admin A", email="aa@test.com", is_active=True, role="ADMIN")
        self.admin_a.set_password("Password123!")
        db.session.add_all([self.owner_a, self.owner_b, self.admin_a])
        db.session.flush()

        # Memberships
        db.session.add_all([
            WorkspaceMember(workspace_id=self.workspace_a.id, user_id=self.owner_a.id, role="owner", status="active"),
            WorkspaceMember(workspace_id=self.workspace_b.id, user_id=self.owner_b.id, role="owner", status="active"),
            WorkspaceMember(workspace_id=self.workspace_a.id, user_id=self.admin_a.id, role="admin", status="active"),
        ])
        db.session.commit()

    def test_create_user_auto_assigns_workspace_membership(self):
        """
        Creating a user inside workspace A context must create a WorkspaceMember for workspace A.
        """
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.owner_a.id
            session["user_id"] = self.owner_a.id

            new_user = UserService.create_user(
                actor=self.owner_a,
                username="staff_new",
                full_name="Staff New",
                password="Password123!",
                email="staffnew@test.com",
                role="STAFF",
                is_active=True,
            )
            # Membership must exist for workspace_a
            membership = WorkspaceMember.query.filter(
                WorkspaceMember.workspace_id == self.workspace_a.id,
                WorkspaceMember.user_id == new_user.id,
                WorkspaceMember.status == "active",
            ).first()
            self.assertIsNotNone(membership)
            self.assertEqual(membership.role, "staff")

    def test_search_paginated_scoped_to_workspace(self):
        """
        search_paginated must only return users belonging to the current workspace.
        """
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.owner_a.id
            session["user_id"] = self.owner_a.id

            results = UserService.search_paginated()
            user_ids = [u.id for u in results.items]

            # owner_a and admin_a belong to workspace_a
            self.assertIn(self.owner_a.id, user_ids)
            self.assertIn(self.admin_a.id, user_ids)
            # owner_b does NOT belong to workspace_a
            self.assertNotIn(self.owner_b.id, user_ids)

    def test_search_paginated_fail_closed_when_no_workspace(self):
        """
        search_paginated must return empty when workspace is None (fail-closed).
        """
        with app.test_request_context():
            session["current_workspace_id"] = None
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = None
            session["user_id"] = None

            results = UserService.search_paginated()
            self.assertEqual(results.total, 0)

    def test_cross_workspace_edit_blocked(self):
        """
        Updating a user from workspace B while in workspace A context must raise NotFoundException.
        """
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.owner_a.id
            session["user_id"] = self.owner_a.id

            with self.assertRaises(NotFoundException):
                UserService.update_user(
                    actor=self.owner_a,
                    user_id=self.owner_b.id,
                    username="hacked_name",
                    full_name="Hacked",
                )

    def test_cross_workspace_reset_password_blocked(self):
        """
        Resetting password for a user from workspace B while in workspace A context must raise NotFoundException.
        """
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.owner_a.id
            session["user_id"] = self.owner_a.id

            with self.assertRaises(NotFoundException):
                UserService.reset_password(
                    actor=self.owner_a,
                    user_id=self.owner_b.id,
                    new_password="NewPassword123!",
                )

    def test_cross_workspace_toggle_active_blocked(self):
        """
        Toggling active for a user from workspace B while in workspace A context must raise NotFoundException.
        """
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.owner_a.id
            session["user_id"] = self.owner_a.id

            with self.assertRaises(NotFoundException):
                UserService.toggle_active(
                    actor=self.owner_a,
                    user_id=self.owner_b.id,
                    is_active=False,
                )

    def test_owner_can_create_staff_and_admin(self):
        """
        OWNER can create STAFF and ADMIN roles.
        """
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.owner_a.id
            session["user_id"] = self.owner_a.id

            staff = UserService.create_user(
                actor=self.owner_a,
                username="o_staff",
                full_name="O Staff",
                password="Password123!",
                role="STAFF",
            )
            self.assertEqual(staff.role, "STAFF")

            admin = UserService.create_user(
                actor=self.owner_a,
                username="o_admin",
                full_name="O Admin",
                password="Password123!",
                role="ADMIN",
            )
            self.assertEqual(admin.role, "ADMIN")

    def test_owner_cannot_create_owner_or_approval_owner(self):
        """
        OWNER cannot create OWNER or APPROVAL_OWNER roles.
        """
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.owner_a.id
            session["user_id"] = self.owner_a.id

            with self.assertRaises(ValidationException):
                UserService.create_user(
                    actor=self.owner_a,
                    username="o_owner",
                    full_name="O Owner",
                    password="Password123!",
                    role="OWNER",
                )

            with self.assertRaises(ValidationException):
                UserService.create_user(
                    actor=self.owner_a,
                    username="o_app_owner",
                    full_name="O App Owner",
                    password="Password123!",
                    role="APPROVAL_OWNER",
                )

    def test_admin_can_create_staff_but_not_admin_or_owner(self):
        """
        ADMIN can create STAFF, but cannot create ADMIN or OWNER roles.
        """
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.admin_a.id
            session["user_id"] = self.admin_a.id

            staff = UserService.create_user(
                actor=self.admin_a,
                username="a_staff",
                full_name="A Staff",
                password="Password123!",
                role="STAFF",
            )
            self.assertEqual(staff.role, "STAFF")

            with self.assertRaises(ValidationException):
                UserService.create_user(
                    actor=self.admin_a,
                    username="a_admin",
                    full_name="A Admin",
                    password="Password123!",
                    role="ADMIN",
                )

            with self.assertRaises(ValidationException):
                UserService.create_user(
                    actor=self.admin_a,
                    username="a_owner",
                    full_name="A Owner",
                    password="Password123!",
                    role="OWNER",
                )

    def test_update_user_role_blocks_elevation_to_owner_and_admin(self):
        """
        update_user blocks non-OWNER from elevating a user to OWNER or ADMIN.
        """
        # Create a staff user to update
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.owner_a.id
            session["user_id"] = self.owner_a.id

            staff = UserService.create_user(
                actor=self.owner_a,
                username="u_staff",
                full_name="U Staff",
                password="Password123!",
                role="STAFF",
            )
            db.session.commit()

        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.admin_a.id
            session["user_id"] = self.admin_a.id

            # ADMIN tries to update staff to ADMIN
            with self.assertRaises(ValidationException):
                UserService.update_user(
                    actor=self.admin_a,
                    user_id=staff.id,
                    username="u_staff",
                    full_name="U Staff",
                    role="ADMIN",
                )

            # ADMIN tries to update staff to OWNER
            with self.assertRaises(ValidationException):
                UserService.update_user(
                    actor=self.admin_a,
                    user_id=staff.id,
                    username="u_staff",
                    full_name="U Staff",
                    role="OWNER",
                )

            # OWNER tries to update staff to OWNER
            session["auth_user_id"] = self.owner_a.id
            session["user_id"] = self.owner_a.id
            with self.assertRaises(ValidationException):
                UserService.update_user(
                    actor=self.owner_a,
                    user_id=staff.id,
                    username="u_staff",
                    full_name="U Staff",
                    role="OWNER",
                )

    def test_idempotent_membership_on_create(self):
        """
        If a user somehow already has a membership in the workspace, add_member_for_user
        must update the existing record (idempotent, no duplicate key error).
        """
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace_a.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.owner_a.id
            session["user_id"] = self.owner_a.id

            # owner_a already has a membership — we test add_member_for_user directly with admin_a
            from services.workspace_service import WorkspaceService
            count_before = WorkspaceMember.query.filter(
                WorkspaceMember.workspace_id == self.workspace_a.id,
                WorkspaceMember.user_id == self.admin_a.id,
            ).count()
            self.assertEqual(count_before, 1)

            # Should not raise; should update existing record
            WorkspaceService.add_member_for_user(
                workspace_id=self.workspace_a.id,
                user=self.admin_a,
                global_role="STAFF",  # downgrade role via update
                actor=self.owner_a,
            )
            db.session.commit()

            count_after = WorkspaceMember.query.filter(
                WorkspaceMember.workspace_id == self.workspace_a.id,
                WorkspaceMember.user_id == self.admin_a.id,
            ).count()
            self.assertEqual(count_after, 1)  # still only 1 row

            updated = WorkspaceMember.query.filter(
                WorkspaceMember.workspace_id == self.workspace_a.id,
                WorkspaceMember.user_id == self.admin_a.id,
            ).first()
            self.assertEqual(updated.role, "staff")
