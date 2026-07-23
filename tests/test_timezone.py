from tests.session_helpers import set_authenticated_session
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from flask import session

TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_timezone_test.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_media_timezone_test"
if TEST_DB_FILE.exists():
    TEST_DB_FILE.unlink()
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
from models.activity_log import ActivityLog
from models.appointment import Appointment
from models.customer import Customer
from models.invoice import Invoice
from models.service import Service
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.activity_log_service import ActivityLogService
from services.appointment_service import AppointmentService
from services.dashboard_statistics_service import DashboardStatisticsService
from services.invoice_service import InvoiceService
from utils.timezone_utils import get_app_timezone, local_today, to_local_datetime

class TimezoneTestCase(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        finally:
            if TEST_DB_FILE.exists():
                TEST_DB_FILE.unlink()
            if TEST_MEDIA_ROOT.exists():
                shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        # Dynamically set config paths to prevent test pollution
        app.config["PERSISTENT_ROOT"] = TEST_MEDIA_ROOT.as_posix()
        app.config["BACKUP_FOLDER"] = (TEST_MEDIA_ROOT / "backup").as_posix()
        app.config["UPLOAD_ROOT"] = (TEST_MEDIA_ROOT / "uploads").as_posix()
        app.config["LOGO_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "logos").as_posix()
        app.config["AVATAR_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "avatars").as_posix()

        self.app_context = app.app_context()
        self.app_context.push()
        self.client = app.test_client()
        db.session.rollback()
        db.drop_all()
        db.create_all()

        # Clear global dashboard cache to prevent test pollution
        from core.cache import dashboard_cache
        dashboard_cache.clear()

        # Create mock workspace and owner user
        self.workspace = Workspace(name="Timezone Workspace", slug="timezone-workspace", status="active")
        self.user = User(username="timezone_user", full_name="Timezone User", email="tz@example.com", is_active=True, role="OWNER")
        self.user.set_password("Password123!")
        db.session.add(self.workspace)
        db.session.add(self.user)
        db.session.flush()

        self.member = WorkspaceMember(workspace_id=self.workspace.id, user_id=self.user.id, role="owner", status="active")
        db.session.add(self.member)
        db.session.commit()

        # Push request context and set workspace session
        self.req_context = app.test_request_context()
        self.req_context.push()
        set_authenticated_session(session, self.user.id)
        session["user_id"] = self.user.id
        session["current_workspace_id"] = self.workspace.id
        session["_enable_workspace_isolation"] = True

    def tearDown(self):
        db.session.rollback()
        db.drop_all()
        # Clean request context
        self.req_context.pop()
        self.app_context.pop()

    def create_customer_and_service(self):
        customer = Customer(
            name="Khách test",
            phone="0901234567",
            email="test@example.com",
            address="HCM",
            workspace_id=self.workspace.id
        )
        service = Service(
            name="Massage test",
            price=150000,
            duration=60,
            description="Test service",
            category="spa",
            workspace_id=self.workspace.id
        )
        db.session.add(customer)
        db.session.add(service)
        db.session.commit()
        return customer, service

    def test_local_today_crosses_midnight_at_utc_boundary(self):
        self.assertEqual(local_today(datetime(2026, 7, 3, 16, 59)), date(2026, 7, 3))
        self.assertEqual(local_today(datetime(2026, 7, 3, 17, 30)), date(2026, 7, 4))

    def test_timezone_configuration_defaults_and_rejects_invalid(self):
        self.assertEqual(app.config["APP_TIMEZONE"], "Asia/Ho_Chi_Minh")
        tz = get_app_timezone()
        self.assertEqual(datetime(2026, 1, 1, tzinfo=tz).utcoffset(), timedelta(hours=7))

        with patch.dict(os.environ, {"APP_TIMEZONE": "Invalid/Zone"}, clear=False):
            with self.assertRaises(ValueError):
                get_app_timezone()

    def test_dashboard_today_counts_and_chart_use_local_day(self):
        customer, service = self.create_customer_and_service()
        db.session.add(Appointment(
            customer_id=customer.id,
            service_id=service.id,
            appointment_time=datetime(2026, 7, 4, 9, 0),
            status="Pending",
            notes="",
            workspace_id=self.workspace.id,
        ))
        db.session.add(Invoice(
            customer_id=customer.id,
            invoice_date=date(2026, 7, 4),
            subtotal=150000,
            discount=0,
            total_amount=150000,
            payment_method="Cash",
            notes="",
            workspace_id=self.workspace.id,
        ))
        db.session.add(ActivityLog(
            created_at=datetime(2026, 7, 3, 17, 0),
            module="System",
            action="TEST",
            description="Timezone log",
            user_id=self.user.id
        ))
        db.session.commit()

        # Clear global dashboard cache before retrieving
        from core.cache import dashboard_cache
        dashboard_cache.clear()

        with patch("services.dashboard_statistics_service.local_today", return_value=date(2026, 7, 4)):
            data = DashboardStatisticsService.get_dashboard_data()
            chart = DashboardStatisticsService.get_revenue_chart_data()

        self.assertEqual(data["stats"]["appointments"]["value"], "1")
        self.assertEqual(data["stats"]["invoices"]["value"], "1")
        self.assertEqual(chart["labels"][-1], "04/07")
        self.assertEqual(chart["values"][-1], 150000.0)
        self.assertIn("04/07/2026 00:00", data["recent_activities"][0]["time"])

    def test_appointment_update_preserves_local_time(self):
        customer, service = self.create_customer_and_service()
        appointment = Appointment(
            customer_id=customer.id,
            service_id=service.id,
            appointment_time=datetime(2026, 7, 4, 9, 0),
            status="Pending",
            notes="Original",
            workspace_id=self.workspace.id,
        )
        db.session.add(appointment)
        db.session.commit()

        with patch("validators.appointment_validator.local_today", return_value=date(2026, 7, 3)):
            updated = AppointmentService.update(
                appointment.id,
                customer_id=customer.id,
                service_id=service.id,
                appointment_date="2026-07-04",
                appointment_time="09:00",
                notes="Updated"
            )

        self.assertEqual(updated.appointment_time, datetime(2026, 7, 4, 9, 0))

    def test_invoice_default_date_uses_local_today(self):
        customer, service = self.create_customer_and_service()

        with patch("services.invoice_service.local_today", return_value=date(2026, 7, 4)):
            invoice = InvoiceService.create_invoice({
                "customer_id": customer.id,
                "invoice_date": None,
                "payment_method": "Cash",
                "notes": "Test invoice",
                "discount": 0,
                "items": [
                    {"service_id": service.id, "quantity": 1, "price": 150000}
                ]
            })

        self.assertEqual(invoice.invoice_date, date(2026, 7, 4))

    def test_vietnam_time_filter_shifts_once(self):
        converted = app.jinja_env.filters["vietnam_time"](datetime(2026, 7, 3, 17, 0))
        self.assertEqual(converted.strftime("%d/%m/%Y %H:%M"), "04/07/2026 00:00")

    def test_storage_timezone_helpers_round_trip(self):
        local_dt = to_local_datetime(datetime(2026, 7, 3, 17, 30), assume_utc=True)
        self.assertEqual(local_dt.strftime("%Y-%m-%d %H:%M"), "2026-07-04 00:30")

if __name__ == "__main__":
    unittest.main()
