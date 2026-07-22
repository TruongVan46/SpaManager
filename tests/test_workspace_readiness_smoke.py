import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Setup unique database file for smoke tests to avoid lock issues
TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_readiness_smoke_test.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_media_smoke_test"

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
from models.account_purge import UserCreationProvenance
from models.workspace import Workspace, WorkspaceMember
from models.customer import Customer
from models.service import Service
from models.appointment import Appointment
from models.invoice import Invoice
from services.user_service import UserService
from services.customer_service import CustomerService
from services.service_service import ServiceService
from services.appointment_service import AppointmentService
from services.invoice_service import InvoiceService
from services.workspace_service import WorkspaceService
from services.dashboard_statistics_service import DashboardStatisticsService
from core.exceptions import ValidationException, NotFoundException
from flask import session
from datetime import datetime, date, timedelta


class TestWorkspaceReadinessSmoke(unittest.TestCase):
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
            try:
                TEST_DB_FILE.unlink()
            except Exception:
                pass
        if TEST_MEDIA_ROOT.exists():
            shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        cls.app_context.pop()

    def setUp(self):
        db.session.rollback()
        # Clean all tables (order respects foreign keys)
        Invoice.query.delete()
        Appointment.query.delete()
        Customer.query.delete()
        Service.query.delete()
        WorkspaceMember.query.delete()
        UserCreationProvenance.query.delete()
        User.query.delete()
        Workspace.query.delete()
        db.session.commit()

        # Seed an APPROVAL_OWNER for system provisioning
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

    def test_approved_google_owner_has_workspace_and_context(self):
        """
        1. Google owner được duyệt sẽ có workspace riêng.
        2. Owner login sẽ có current_workspace_id.
        """
        # Create a pending Google user
        google_user = self._create_user(
            username="google_owner",
            role="OWNER",
            email="google_owner@gmail.com",
            is_active=False,
            auth_provider="google",
            approval_status=User.APPROVAL_PENDING
        )
        db.session.commit()

        # Approve the user using the UserService
        UserService.approve_pending_user(actor=self.approval_owner, user_id=google_user.id)

        # Assert Workspace is created
        workspace = Workspace.query.filter_by(slug="google-owner").first()
        self.assertIsNotNone(workspace)
        self.assertEqual(workspace.status, "active")

        # Assert WorkspaceMember role owner active is created
        membership = WorkspaceMember.query.filter_by(
            workspace_id=workspace.id,
            user_id=google_user.id
        ).first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.role, "owner")
        self.assertEqual(membership.status, "active")

        # Simulate login context & verify current_workspace_id is set
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            WorkspaceService.ensure_current_workspace_session(google_user)
            self.assertEqual(session.get("current_workspace_id"), workspace.id)

    def test_owner_creates_staff_and_admin_inside_current_workspace(self):
        """
        3. Owner tạo ADMIN/STAFF trong workspace hiện tại.
        """
        # Setup Workspaces
        workspace_a = Workspace(name="Workspace A", slug="ws-a", status="active")
        workspace_b = Workspace(name="Workspace B", slug="ws-b", status="active")
        db.session.add_all([workspace_a, workspace_b])
        db.session.flush()

        owner_a = self._create_user(username="owner_a", role="OWNER")
        # Add ownership membership for Owner A
        db.session.add(WorkspaceMember(workspace_id=workspace_a.id, user_id=owner_a.id, role="owner", status="active"))
        db.session.commit()

        # Simulate Owner A request context
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace_a.id
            session["auth_user_id"] = owner_a.id

            # Create STAFF
            staff = UserService.create_user(
                actor=owner_a,
                username="staff_a",
                full_name="Staff A",
                password="Password123!",
                email="sa@test.com",
                role="STAFF"
            )
            # Create ADMIN
            admin = UserService.create_user(
                actor=owner_a,
                username="admin_a",
                full_name="Admin A",
                password="Password123!",
                email="aa@test.com",
                role="ADMIN"
            )

            # Assert WorkspaceMember assignments
            staff_member = WorkspaceMember.query.filter_by(user_id=staff.id).first()
            self.assertIsNotNone(staff_member)
            self.assertEqual(staff_member.workspace_id, workspace_a.id)
            self.assertEqual(staff_member.role, "staff")

            admin_member = WorkspaceMember.query.filter_by(user_id=admin.id).first()
            self.assertIsNotNone(admin_member)
            self.assertEqual(admin_member.workspace_id, workspace_a.id)
            self.assertEqual(admin_member.role, "admin")

            # Assert no memberships to Workspace B
            self.assertFalse(WorkspaceService.is_user_in_workspace(staff.id, workspace_b.id))
            self.assertFalse(WorkspaceService.is_user_in_workspace(admin.id, workspace_b.id))

    def test_staff_login_uses_same_workspace_and_sees_same_business_data(self):
        """
        4. ADMIN/STAFF login vào đúng workspace.
        5. Customers/services/appointments/invoices/dashboard chỉ hiện dữ liệu workspace hiện tại.
        """
        workspace_a = Workspace(name="Workspace A", slug="ws-a", status="active")
        workspace_b = Workspace(name="Workspace B", slug="ws-b", status="active")
        db.session.add_all([workspace_a, workspace_b])
        db.session.flush()

        staff_a = self._create_user(username="staff_a", role="STAFF")
        db.session.add(WorkspaceMember(workspace_id=workspace_a.id, user_id=staff_a.id, role="staff", status="active"))
        db.session.commit()

        # Seed data in A and B
        cust_a = Customer(name="Customer A", phone="0911223344", workspace_id=workspace_a.id)
        cust_b = Customer(name="Customer B", phone="0955667788", workspace_id=workspace_b.id)
        db.session.add_all([cust_a, cust_b])
        db.session.commit()

        # Login Staff A
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            WorkspaceService.ensure_current_workspace_session(staff_a)
            self.assertEqual(session.get("current_workspace_id"), workspace_a.id)

            # Query list
            all_customers = CustomerService.get_all()
            self.assertEqual(len(all_customers), 1)
            self.assertEqual(all_customers[0].name, "Customer A")

    def test_workspace_a_cannot_see_workspace_b_business_data(self):
        """
        7. Workspace A không thấy/chạm dữ liệu Workspace B.
        """
        workspace_a = Workspace(name="Workspace A", slug="ws-a", status="active")
        workspace_b = Workspace(name="Workspace B", slug="ws-b", status="active")
        db.session.add_all([workspace_a, workspace_b])
        db.session.flush()

        owner_a = self._create_user(username="owner_a", role="OWNER")
        db.session.add(WorkspaceMember(workspace_id=workspace_a.id, user_id=owner_a.id, role="owner", status="active"))
        db.session.commit()

        # Customer A and B
        cust_a = Customer(name="Customer A", phone="0911223344", workspace_id=workspace_a.id)
        cust_b = Customer(name="Customer B", phone="0955667788", workspace_id=workspace_b.id)
        db.session.add_all([cust_a, cust_b])
        db.session.commit()

        # Under context A
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace_a.id
            session["auth_user_id"] = owner_a.id

            # Try get customer B details
            res = CustomerService.get_by_id(cust_b.id)
            self.assertIsNone(res)

            # Try dashboard stats
            stats = DashboardStatisticsService.get_dashboard_data()
            self.assertEqual(stats["stats"]["customers"]["value"], "1")

    def test_user_management_is_workspace_scoped(self):
        """
        6. User management chỉ hiện user cùng workspace.
        """
        workspace_a = Workspace(name="Workspace A", slug="ws-a", status="active")
        workspace_b = Workspace(name="Workspace B", slug="ws-b", status="active")
        db.session.add_all([workspace_a, workspace_b])
        db.session.flush()

        owner_a = self._create_user(username="owner_a", role="OWNER")
        owner_b = self._create_user(username="owner_b", role="OWNER")
        admin_a = self._create_user(username="admin_a", role="ADMIN")
        staff_a = self._create_user(username="staff_a", role="STAFF")

        db.session.add_all([
            WorkspaceMember(workspace_id=workspace_a.id, user_id=owner_a.id, role="owner", status="active"),
            WorkspaceMember(workspace_id=workspace_b.id, user_id=owner_b.id, role="owner", status="active"),
            WorkspaceMember(workspace_id=workspace_a.id, user_id=admin_a.id, role="admin", status="active"),
            WorkspaceMember(workspace_id=workspace_a.id, user_id=staff_a.id, role="staff", status="active"),
        ])
        db.session.commit()

        # Under context A, logged as Owner A
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace_a.id
            session["auth_user_id"] = owner_a.id

            # Users returned
            users_paginated = UserService.search_paginated()
            user_ids = [u.id for u in users_paginated.items]
            self.assertIn(owner_a.id, user_ids)
            self.assertIn(admin_a.id, user_ids)
            self.assertIn(staff_a.id, user_ids)
            self.assertNotIn(owner_b.id, user_ids)

            # Try to edit User B -> raises NotFoundException
            with self.assertRaises(NotFoundException):
                UserService.update_user(
                    actor=owner_a,
                    user_id=owner_b.id,
                    username=owner_b.username,
                    full_name="Hack",
                    email=owner_b.email,
                    role=owner_b.role
                )

        # Under context A, logged as Admin A
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace_a.id
            session["auth_user_id"] = admin_a.id

            # ADMIN A tries to create ADMIN -> raises ValidationException
            with self.assertRaises(ValidationException):
                UserService.create_user(
                    actor=admin_a,
                    username="admin_a2",
                    full_name="Admin A2",
                    password="Password123!",
                    email="aa2@test.com",
                    role="ADMIN"
                )

        # Under context A, logged as Staff A
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace_a.id
            session["auth_user_id"] = staff_a.id

            # STAFF A and APPROVAL_OWNER must be blocked from user management
            from core.auth.permissions import can_manage_users
            self.assertFalse(can_manage_users(staff_a))
            self.assertFalse(can_manage_users(self.approval_owner))

    def test_no_current_workspace_fail_closed(self):
        """
        8. Không có current_workspace_id hợp lệ thì fail-closed.
        """
        # Under context without current_workspace_id
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = None

            # Customer query should be empty
            customers = CustomerService.get_all()
            self.assertEqual(len(customers), 0)

            # User query should be empty
            users = UserService.search_paginated().items
            self.assertEqual(len(users), 0)

            # User creation should fail
            dummy_actor = User(username="dummy", role="OWNER", full_name="Dummy")
            with self.assertRaises(ValidationException):
                UserService.create_user(
                    actor=dummy_actor,
                    username="test_fc",
                    full_name="FC",
                    password="Password123!",
                    email="fc@test.com",
                    role="STAFF"
                )

    def test_owner_role_cannot_be_created_from_spamanager_ui(self):
        """
        10. Không còn đường tạo OWNER từ UI SpaManager.
        """
        workspace_a = Workspace(name="Workspace A", slug="ws-a", status="active")
        db.session.add(workspace_a)
        db.session.flush()

        owner_a = self._create_user(username="owner_a", role="OWNER")
        db.session.add(WorkspaceMember(workspace_id=workspace_a.id, user_id=owner_a.id, role="owner", status="active"))
        db.session.commit()

        # Under Owner A context
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = workspace_a.id
            session["auth_user_id"] = owner_a.id

            # Create OWNER -> raises ValidationException
            with self.assertRaises(ValidationException):
                UserService.create_user(
                    actor=owner_a,
                    username="owner_new",
                    full_name="New Owner",
                    password="Password123!",
                    email="onew@test.com",
                    role="OWNER"
                )

            # Update role to OWNER -> raises ValidationException
            test_user = self._create_user(username="staff_temp", role="STAFF")
            db.session.add(WorkspaceMember(workspace_id=workspace_a.id, user_id=test_user.id, role="staff", status="active"))
            db.session.commit()

            with self.assertRaises(ValidationException):
                UserService.update_user(
                    actor=owner_a,
                    user_id=test_user.id,
                    username=test_user.username,
                    full_name=test_user.full_name,
                    email=test_user.email,
                    role="OWNER"
                )
