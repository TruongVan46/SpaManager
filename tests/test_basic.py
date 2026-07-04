import os
import shutil
import tempfile
import unittest
import re
import json
import html as html_module
import uuid
import inspect
import sqlite3
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from sqlalchemy import event, text, inspect as sa_inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_owner_seed_test.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_media_seed_test"
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
from config import DevelopmentConfig, ProductionConfig
from extensions import db
from core.auth.constants import AUTH_SESSION_KEY
from core.exceptions import AuthenticationException
from models.activity_log import ActivityLog
from models.appointment import Appointment
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from models.service import Service
from models.setting import Setting
from models.user import User
from services.appointment_service import AppointmentService
from services.activity_log_service import ActivityLogService
from services.customer_service import CustomerService
from services.invoice_service import InvoiceService
from services.service_service import ServiceService
from services.auth_service import AuthService
from services.backup_service import BackupService
from services.import_service import ImportService
from repositories.backup_repository import BackupRepository
from core.auth.permissions import (
    can_manage_backups,
    can_manage_business_data,
    can_manage_settings,
    can_manage_users,
    can_view_activity_logs,
    is_admin,
    is_manager,
    is_owner,
    is_staff,
)
from core.activity_log_utils import sanitize_activity_log_value, get_activity_actor_display_name
import core.csrf as csrf_module


class BasicTestCase(unittest.TestCase):
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
        self.app_context = app.app_context()
        self.app_context.push()
        self.client = app.test_client()
        self.reset_database_schema()

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def reset_database_schema(self):
        db.session.rollback()
        db.drop_all()
        db.session.commit()
        with db.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        db.create_all()

    def clear_database_schema(self):
        db.session.rollback()
        db.drop_all()
        db.session.commit()
        with db.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))

    def create_user(self, username, password="secret123", full_name="Test User", role="STAFF"):
        user = User(
            username=username,
            full_name=full_name,
            role=role,
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    def login_as(self, user):
        with self.client.session_transaction() as sess:
            sess[AUTH_SESSION_KEY] = user.id

    def get_csrf_token(self, path="/login"):
        response = self.client.get(path, follow_redirects=True)
        html = response.get_data(as_text=True)
        match = re.search(r'name="csrf-token" content="([^"]+)"', html)
        if not match:
            match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match, "CSRF token not found in response HTML")
        return match.group(1)

    def post_with_csrf(self, url, path="/login", **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["X-CSRFToken"] = self.get_csrf_token(path)
        return self.client.post(url, headers=headers, **kwargs)

    def create_customer_record(self, name="Test Customer"):
        customer = Customer(name=name, phone="0900000000", email=f"{name.lower().replace(' ', '')}@example.com")
        db.session.add(customer)
        db.session.commit()
        return customer

    def create_service_record(self, name="Test Service"):
        service = Service(name=name, price=100000, duration=30, description="Test", category="other")
        db.session.add(service)
        db.session.commit()
        return service

    def create_appointment_record(self, customer=None, service=None):
        customer = customer or self.create_customer_record("Appointment Customer")
        service = service or self.create_service_record("Appointment Service")
        appointment = Appointment(
            customer_id=customer.id,
            service_id=service.id,
            appointment_time=datetime(2026, 7, 4, 10, 0),
            status="Pending"
        )
        db.session.add(appointment)
        db.session.commit()
        return appointment

    def create_invoice_record(self, customer=None, service=None):
        customer = customer or self.create_customer_record("Invoice Customer")
        service = service or self.create_service_record("Invoice Service")
        invoice = Invoice(
            customer_id=customer.id,
            invoice_date=datetime(2026, 7, 4).date(),
            subtotal=100000,
            discount=0,
            total_amount=100000,
            payment_method="Cash",
            notes="Test invoice"
        )
        db.session.add(invoice)
        db.session.flush()
        detail = InvoiceDetail(
            invoice_id=invoice.id,
            service_id=service.id,
            price=100000,
            quantity=1
        )
        db.session.add(detail)
        db.session.commit()
        return invoice

    def create_media_file(self, relative_path, content=b"media-bytes"):
        absolute_path = TEST_MEDIA_ROOT / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(content)
        return absolute_path

    def create_settings_backup_via_route(self, user, notes="Route backup"):
        self.login_as(user)
        response = self.post_with_csrf(
            "/settings/backup",
            path="/settings",
            data={
                "notes": notes,
                "backup_type": "Manual",
                "format": "json",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertTrue(payload["success"])
        backup_id = payload["download_url"].rsplit("/", 1)[-1]
        meta = BackupRepository.get_by_id(app, backup_id)
        self.assertIsNotNone(meta)
        backup_path = Path(BackupService.get_backup_file_path(app, meta["filename"]))
        self.assertTrue(backup_path.exists())
        return backup_id, meta, backup_path

    def create_customer_import_xlsx(self, rows=None):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Khách hàng"
        sheet.append(["Họ tên", "Số điện thoại", "Email", "Địa chỉ"])
        sample_rows = rows or [[f"Import {uuid.uuid4().hex[:8]}", "0901234567", f"{uuid.uuid4().hex[:8]}@example.com", "123 Đường A"]]
        for row in sample_rows:
            sheet.append(row)

        temp_path = Path(tempfile.gettempdir()) / f"settings-import-{uuid.uuid4().hex}.xlsx"
        workbook.save(temp_path)
        workbook.close()
        return temp_path

    def insert_owner_row(self):
        now = datetime.utcnow()
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users
                        (username, password_hash, full_name, avatar, role, is_active,
                         last_login, email, email_verified, auth_provider, oauth_id,
                         created_at, updated_at)
                    VALUES
                        (:username, :password_hash, :full_name, NULL, :role, :is_active,
                         NULL, NULL, 0, 'local', NULL, :created_at, :updated_at)
                    """
                ),
                {
                    "username": "owner",
                    "password_hash": "existing-owner-hash",
                    "full_name": "Chá»§ Spa",
                    "role": "OWNER",
                    "is_active": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    def test_app_initialization(self):
        self.assertIsNotNone(app)

    def test_login_page_loads(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn('csrf-token', response.get_data(as_text=True))

    def test_login_post_requires_csrf_token(self):
        self.create_user("login-csrf", password="login-pass", full_name="Login CSRF", role="STAFF")

        response = self.client.post(
            "/login",
            json={
                "username": "login-csrf",
                "password": "login-pass",
                "remember": False,
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.is_json)
        payload = response.get_json()
        self.assertEqual(payload["error"], "csrf_failed")
        self.assertNotIn("Location", response.headers)

    def test_login_post_succeeds_with_csrf_token(self):
        self.create_user("login-ok", password="login-pass", full_name="Login OK", role="STAFF")
        csrf_token = self.get_csrf_token("/login")

        response = self.client.post(
            "/login",
            json={
                "username": "login-ok",
                "password": "login-pass",
                "remember": False,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": csrf_token,
            },
            follow_redirects=False
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        payload = response.get_json()
        self.assertTrue(payload["success"])

    def test_login_rejects_external_next_redirect(self):
        self.create_user("login-next", password="login-pass", full_name="Login Next", role="STAFF")
        csrf_token = self.get_csrf_token("/login")

        response = self.client.post(
            "/login?next=https://evil.example",
            json={
                "username": "login-next",
                "password": "login-pass",
                "remember": False,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": csrf_token,
            },
            follow_redirects=False
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["redirect"], "/")

    def test_csrf_token_uses_compare_digest(self):
        source = inspect.getsource(csrf_module.validate_csrf_request)
        self.assertIn("compare_digest", source)

    def test_csrf_token_is_session_bound(self):
        self.create_user("bound-user", password="bound-pass", full_name="Bound User", role="STAFF")
        client_a = app.test_client()
        client_b = app.test_client()

        login_page = client_a.get("/login")
        token_a = re.search(r'name="csrf-token" content="([^"]+)"', login_page.get_data(as_text=True)).group(1)

        response = client_b.post(
            "/login",
            json={
                "username": "bound-user",
                "password": "bound-pass",
                "remember": False,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": token_a,
            },
            follow_redirects=False
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.is_json)
        self.assertEqual(response.get_json()["error"], "csrf_failed")

    def test_csrf_fetch_only_adds_token_for_same_origin_unsafe_methods(self):
        source = Path("static/js/csrf.js").read_text(encoding="utf-8")
        self.assertIn("isUnsafeMethod", source)
        self.assertIn("isSameOrigin", source)
        self.assertIn("credentials = 'same-origin'", source)
        self.assertNotIn("window.fetch =", source)
        self.assertNotIn("Content-Type: 'multipart/form-data'", source)

    def test_global_csrf_protects_all_unsafe_routes(self):
        self.assertEqual(
            set(csrf_module.CSRF_SAFE_PATH_PREFIXES),
            {"/health", "/static/", "/media/"}
        )
        unsafe_methods = {"POST", "PUT", "PATCH", "DELETE"}
        for rule in app.url_map.iter_rules():
            rule_unsafe_methods = unsafe_methods.intersection(rule.methods or set())
            if not rule_unsafe_methods:
                continue
            concrete_rule = re.sub(r"<[^>]+>", "1", rule.rule)
            for method in rule_unsafe_methods:
                with app.test_request_context(concrete_rule, method=method):
                    if rule.rule.startswith(csrf_module.CSRF_SAFE_PATH_PREFIXES):
                        self.assertFalse(csrf_module.requires_csrf_protection(), rule.rule)
                    else:
                        self.assertTrue(csrf_module.requires_csrf_protection(), rule.rule)

    def test_no_state_changing_get_routes(self):
        allowed_read_only_get_routes = {
            "/settings/backup/download/<string:backup_id>",
            "/settings/restore-wizard/validate/<string:backup_id>",
            "/settings/template/customers",
            "/settings/template/services",
            "/settings/import/errors/download/<string:filename>",
            "/customers/<int:id>/can-delete",
        }
        banned_keywords = ("logout", "delete", "restore", "permanent", "import", "backup", "update", "upload", "status")

        for rule in app.url_map.iter_rules():
            if "GET" not in (rule.methods or set()):
                continue
            lower_rule = rule.rule.lower()
            if any(keyword in lower_rule for keyword in banned_keywords):
                self.assertIn(rule.rule, allowed_read_only_get_routes)

    def test_csrf_token_rotates_after_login_and_old_token_stops_working(self):
        self.create_user("rotate-user", password="rotate-pass", full_name="Rotate User", role="STAFF")
        old_token = self.get_csrf_token("/login")

        login_response = self.client.post(
            "/login",
            json={
                "username": "rotate-user",
                "password": "rotate-pass",
                "remember": False,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": old_token,
            },
            follow_redirects=False
        )
        self.assertEqual(login_response.status_code, 200)

        stale_token_response = self.client.post(
            "/customers/create",
            data={
                "name": f"Rotate Reject {uuid.uuid4().hex[:8]}",
                "phone": f"09{uuid.uuid4().int % 100000000:08d}",
                "email": f"rotate-reject-{uuid.uuid4().hex[:8]}@example.com",
                "address": "HCMC",
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": old_token,
            },
            follow_redirects=False
        )
        self.assertEqual(stale_token_response.status_code, 400)
        self.assertEqual(stale_token_response.get_json()["error"], "csrf_failed")

        fresh_token = self.get_csrf_token("/customers")
        success_response = self.client.post(
            "/customers/create",
            data={
                "name": f"Rotate Accept {uuid.uuid4().hex[:8]}",
                "phone": f"09{uuid.uuid4().int % 100000000:08d}",
                "email": f"rotate-accept-{uuid.uuid4().hex[:8]}@example.com",
                "address": "HCMC",
            },
            headers={"X-CSRFToken": fresh_token},
            follow_redirects=False
        )
        self.assertEqual(success_response.status_code, 302)

    def test_logout_clears_session_and_csrf_token(self):
        self.create_user("logout-user", password="logout-pass", full_name="Logout User", role="STAFF")
        login_token = self.get_csrf_token("/login")

        login_response = self.client.post(
            "/login",
            json={
                "username": "logout-user",
                "password": "logout-pass",
                "remember": False,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": login_token,
            },
            follow_redirects=False
        )
        self.assertEqual(login_response.status_code, 200)

        logout_response = self.client.post(
            "/logout",
            headers={"X-CSRFToken": self.get_csrf_token("/customers")},
            follow_redirects=False
        )
        self.assertEqual(logout_response.status_code, 302)

        relogin_attempt = self.client.post(
            "/login",
            json={
                "username": "logout-user",
                "password": "logout-pass",
                "remember": False,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": login_token,
            },
            follow_redirects=False
        )
        self.assertEqual(relogin_attempt.status_code, 400)
        self.assertEqual(relogin_attempt.get_json()["error"], "csrf_failed")

        new_login_token = self.get_csrf_token("/login")
        self.assertNotEqual(login_token, new_login_token)

    def test_html_form_post_requires_csrf_token(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        response = self.client.post(
            "/customers/create",
            data={
                "name": "CSRF Customer",
                "phone": "0900000000",
                "email": "csrf@example.com",
                "address": "HCMC",
            },
            follow_redirects=False
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type.split(";")[0], "text/html")
        self.assertIn("Yêu cầu không hợp lệ", response.get_data(as_text=True))
        self.assertEqual(Customer.query.filter_by(email="csrf@example.com").count(), 0)

        success_response = self.post_with_csrf(
            "/customers/create",
            path="/customers",
            data={
                "name": f"CSRF Customer {uuid.uuid4().hex[:8]}",
                "phone": f"09{uuid.uuid4().int % 100000000:08d}",
                "email": f"csrf-{uuid.uuid4().hex[:8]}@example.com",
                "address": "HCMC",
            },
            follow_redirects=False
        )

        self.assertEqual(success_response.status_code, 302)
        self.assertEqual(Customer.query.filter(Customer.name.like("CSRF Customer %")).count(), 1)

    def test_multipart_profile_update_requires_csrf_token(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        response = self.client.post(
            "/profile",
            data={
                "full_name": "Owner Updated",
                "avatar": (BytesIO(b"avatar-bytes"), "avatar.png"),
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            content_type="multipart/form-data",
            follow_redirects=False
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.is_json)
        self.assertEqual(response.get_json()["error"], "csrf_failed")
        refreshed_owner = User.query.filter_by(username="owner").first()
        self.assertEqual(refreshed_owner.full_name, owner.full_name)

        success_response = self.post_with_csrf(
            "/profile",
            path="/profile",
            data={
                "full_name": "Owner Updated",
                "avatar": (BytesIO(b"avatar-bytes"), "avatar.png"),
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            content_type="multipart/form-data",
            follow_redirects=False
        )

        self.assertEqual(success_response.status_code, 200)
        self.assertTrue(success_response.is_json)
        self.assertTrue(success_response.get_json()["success"])

    def test_logout_get_is_safe_and_post_requires_csrf(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        get_response = self.client.get("/logout", follow_redirects=False)
        self.assertEqual(get_response.status_code, 405)
        still_authenticated = self.client.get("/customers", follow_redirects=False)
        self.assertEqual(still_authenticated.status_code, 200)

        csrf_token = self.get_csrf_token("/customers")
        post_response = self.client.post(
            "/logout",
            headers={"X-CSRFToken": csrf_token},
            follow_redirects=False
        )

        self.assertEqual(post_response.status_code, 302)
        self.assertIn("/login", post_response.headers.get("Location", ""))
        post_logout_access = self.client.get("/customers", follow_redirects=False)
        self.assertEqual(post_logout_access.status_code, 302)

    def test_health_check_returns_json_without_login(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertTrue(response.is_json)
        self.assertEqual(response.get_json(), {
            "status": "ok",
            "app": "SpaManager",
            "database": "connected",
        })

    def test_health_check_executes_database_probe(self):
        with patch("app.db.session.execute") as mocked_execute:
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        mocked_execute.assert_called_once()
        self.assertEqual(str(mocked_execute.call_args.args[0]), "SELECT 1")

    def test_health_check_returns_503_on_database_error_and_rolls_back(self):
        self.create_user("health-check-user", password="health-pass", full_name="Health Check", role="STAFF")
        original_rollback = db.session.rollback

        with patch("app.db.session.execute", side_effect=SQLAlchemyError("database unavailable")) as mocked_execute:
            with patch("app.db.session.rollback", wraps=original_rollback) as mocked_rollback:
                response = self.client.get("/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertTrue(response.is_json)
        payload = response.get_json()
        self.assertEqual(payload["status"], "unhealthy")
        self.assertEqual(payload["database"], "unavailable")
        self.assertNotIn("password", response.get_data(as_text=True).lower())
        self.assertNotIn("database unavailable", response.get_data(as_text=True).lower())
        mocked_execute.assert_called_once()
        mocked_rollback.assert_called_once()
        self.assertEqual(User.query.filter_by(username="health-check-user").count(), 1)

    def test_health_check_post_method_is_not_allowed(self):
        response = self.client.post("/health")

        self.assertEqual(response.status_code, 405)
        self.assertNotIn("Location", response.headers)

    def test_health_check_session_remains_usable_after_rollback(self):
        self.create_user("session-safe", password="session-pass", full_name="Session Safe", role="STAFF")

        with patch("app.db.session.execute", side_effect=SQLAlchemyError("database unavailable")):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 503)
        query_result = User.query.filter_by(username="session-safe").first()
        self.assertIsNotNone(query_result)
        self.assertEqual(query_result.username, "session-safe")

    def test_production_requires_secret_key(self):
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "sqlite:///prod.sqlite",
                "DEFAULT_OWNER_PASSWORD": "prod-owner-pass",
                "SECRET_KEY": "",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                ProductionConfig()

    def test_production_requires_database_url(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "prod-secret",
                "DEFAULT_OWNER_PASSWORD": "prod-owner-pass",
                "DATABASE_URL": "",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                ProductionConfig()

    def test_media_route_serves_logo_from_persistent_folder(self):
        self.create_media_file(Path("uploads") / "logos" / "sample-logo.png", b"\x89PNG\r\n\x1a\n")

        response = self.client.get("/media/logos/sample-logo.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        response.close()

    def test_missing_media_returns_404_without_redirect(self):
        response = self.client.get("/media/logos/missing.png", follow_redirects=False)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Location", response.headers)

    def test_missing_route_returns_html_404_without_redirect_when_not_logged_in(self):
        response = self.client.get("/khong-ton-tai", follow_redirects=False)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content_type.split(";")[0], "text/html")
        self.assertNotIn("Location", response.headers)
        self.assertIn("404", response.get_data(as_text=True))

    def test_missing_route_returns_json_404_when_requested(self):
        response = self.client.get(
            "/khong-ton-tai-json",
            headers={"Accept": "application/json"},
            follow_redirects=False
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.is_json)
        payload = response.get_json()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "not_found")
        self.assertNotIn("Location", response.headers)

    def test_static_missing_returns_404_without_redirect(self):
        response = self.client.get("/static/missing.css", follow_redirects=False)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Location", response.headers)

    def test_protected_html_route_redirects_login_when_not_authenticated(self):
        response = self.client.get("/customers", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_json_auth_error_returns_401_without_redirect(self):
        response = self.client.post(
            "/change-password",
            json={
                "current_password": "x",
                "new_password": "y",
                "confirm_password": "y",
            },
            follow_redirects=False
        )

        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.is_json)
        payload = response.get_json()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "unauthorized")
        self.assertNotIn("Location", response.headers)

    def test_html_500_renders_template_and_rolls_back(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        def explode_dashboard():
            raise RuntimeError("boom")

        original_view = app.view_functions["dashboard.index"]
        app.view_functions["dashboard.index"] = explode_dashboard
        try:
            response = self.client.get("/", follow_redirects=False)
        finally:
            app.view_functions["dashboard.index"] = original_view

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.content_type.split(";")[0], "text/html")
        self.assertIn("500", response.get_data(as_text=True))
        self.assertNotIn("boom", response.get_data(as_text=True))
        self.assertNotIn("Traceback", response.get_data(as_text=True))

    def test_json_500_returns_json_and_rolls_back(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        def explode_dashboard():
            raise RuntimeError("boom-json")

        original_view = app.view_functions["dashboard.index"]
        app.view_functions["dashboard.index"] = explode_dashboard
        try:
            response = self.client.get("/", headers={"Accept": "application/json"}, follow_redirects=False)
        finally:
            app.view_functions["dashboard.index"] = original_view

        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.is_json)
        payload = response.get_json()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "internal_server_error")
        self.assertNotIn("boom-json", response.get_data(as_text=True))
        self.assertNotIn("Traceback", response.get_data(as_text=True))

    def test_dashboard_today_appointments_render_expected_classes(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        response = self.client.get("/")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="dashboard-schedule-list"', html)
        self.assertIn('class="schedule-list"', html)
        self.assertIn('class="appointment-item schedule-item"', html)
        self.assertIn('id="appt-footer"', html)

    def test_dashboard_manager_sees_admin_summary_and_backup_status(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        response = self.client.get("/")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Tổng quan quản trị", html)
        self.assertIn("Backup gần nhất", html)
        self.assertIn("Người dùng", html)
        self.assertIn("Cảnh báo gần đây", html)
        self.assertIn("Phím tắt quản trị", html)
        self.assertNotIn(os.path.abspath("backup"), html)

        api_response = self.client.get("/api/dashboard/data")
        payload = api_response.get_json()
        self.assertIn("admin_summary", payload)
        self.assertIn("backup", payload["admin_summary"])
        self.assertIn("users", payload["admin_summary"])
        self.assertIn("activity", payload["admin_summary"])

    def test_dashboard_manager_shows_latest_backup_summary_when_available(self):
        owner = self.create_user("dashboard-backup-owner", password="owner-pass", full_name="Dashboard Backup Owner", role="OWNER")
        self.login_as(owner)
        backup_id, backup_meta, backup_path = self.create_settings_backup_via_route(owner, notes="Dashboard summary backup")

        try:
            response = self.client.get("/")
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn("Backup ngày", html)
            self.assertIn("Hôm nay", html)
            self.assertIn(backup_meta["display_name"], html)
            self.assertNotIn(str(backup_path), html)
        finally:
            if backup_path.exists():
                backup_path.unlink()
            BackupRepository.delete(app, backup_id)

    def test_dashboard_staff_hides_admin_summary_and_api_does_not_leak_sensitive_blocks(self):
        owner = AuthService.seed_owner_if_empty()
        staff = self.create_user("dashboard-staff", password="staff-pass", full_name="Dashboard Staff", role="STAFF")
        self.login_as(owner)
        backup_id, backup_meta, backup_path = self.create_settings_backup_via_route(owner, notes="Staff visibility backup")

        try:
            self.login_as(staff)
            response = self.client.get("/")
            html = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("Lịch hẹn hôm nay", html)
            self.assertIn("Doanh thu hôm nay", html)
            self.assertNotIn("Tổng quan quản trị", html)
            self.assertNotIn("Phím tắt quản trị", html)
            self.assertNotIn("Backup gần nhất", html)
            self.assertNotIn("Người dùng", html)

            api_response = self.client.get("/api/dashboard/data")
            payload = api_response.get_json()
            self.assertNotIn("admin_summary", payload)
            self.assertNotIn("recent_activities", payload)
        finally:
            if backup_path.exists():
                backup_path.unlink()
            BackupRepository.delete(app, backup_id)

    def test_topbar_exposes_command_palette_hint(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        html = self.client.get("/").get_data(as_text=True)
        source = Path("static/js/command-palette.js").read_text(encoding="utf-8")
        palette_html = Path("templates/layout/command_palette.html").read_text(encoding="utf-8")

        self.assertIn('data-command-palette-open', html)
        self.assertIn('type="button"', html)
        self.assertIn('Tìm nhanh', html)
        self.assertIn('Ctrl K', html)
        self.assertIn('data-command-palette-close', palette_html)
        self.assertIn('aria-label="Đóng tìm nhanh"', palette_html)
        self.assertIn('command-palette-close', palette_html)
        self.assertIn('window.openCommandPalette = function (triggerEl)', source)
        self.assertIn('window.closeCommandPalette = function ()', source)
        self.assertIn('[data-command-palette-open]', source)
        self.assertIn('[data-command-palette-close]', source)

    def test_page_size_handler_is_scoped_to_explicit_controls(self):
        source = Path("static/js/shared-table.js").read_text(encoding="utf-8")
        macro = Path("templates/layout/table_macros.html").read_text(encoding="utf-8")
        invoice_template = Path("templates/invoice/index.html").read_text(encoding="utf-8")
        appointment_template = Path("templates/appointment/index.html").read_text(encoding="utf-8")
        activity_log_template = Path("templates/activity_log/index.html").read_text(encoding="utf-8")
        recycle_bin_template = Path("templates/recycle_bin/index.html").read_text(encoding="utf-8")

        self.assertIn("[data-stf-filter]", source)
        self.assertIn("[data-stf-per-page]", source)
        self.assertIn("fetchAndSwapPageSize", source)
        self.assertIn("window.history.replaceState", source)
        self.assertIn("data-stf-per-page-param", macro)
        self.assertNotIn("reloadWithParams(p, pageParam)", source)
        self.assertNotIn("window.location.href = u.toString()", invoice_template)
        self.assertNotIn("window.location.href = u.toString()", appointment_template)
        self.assertNotIn("window.location.href = u.toString()", activity_log_template)
        self.assertNotIn("window.location.href = u.toString()", recycle_bin_template)

    def test_seed_owner_creates_owner_when_database_is_empty(self):
        owner = AuthService.seed_owner_if_empty()

        self.assertIsNotNone(owner)
        self.assertEqual(owner.username, "owner")
        self.assertEqual(User.query.filter_by(username="owner").count(), 1)
        self.assertTrue(User.query.filter_by(username="owner").first().check_password("owner123"))

    def test_seed_owner_does_not_change_existing_owner(self):
        existing_owner = self.create_user("owner", password="old-password", full_name="Chá»§ Spa", role="OWNER")
        existing_hash = existing_owner.password_hash

        result = AuthService.seed_owner_if_empty()

        refreshed_owner = User.query.filter_by(username="owner").first()
        self.assertEqual(result.id, existing_owner.id)
        self.assertEqual(User.query.filter_by(username="owner").count(), 1)
        self.assertEqual(refreshed_owner.password_hash, existing_hash)
        self.assertTrue(refreshed_owner.check_password("old-password"))

    def test_seed_owner_creates_owner_when_other_user_exists(self):
        self.create_user("customer-1", password="customer-pass", full_name="Customer 1", role="STAFF")

        owner = AuthService.seed_owner_if_empty()

        self.assertIsNotNone(owner)
        self.assertEqual(owner.username, "owner")
        self.assertEqual(User.query.filter_by(username="owner").count(), 1)
        self.assertEqual(User.query.count(), 2)

    def test_seed_owner_recovers_from_integrity_error_when_owner_appears(self):
        self.create_user("observer", password="observer-pass", full_name="Observer", role="STAFF")

        def inject_owner_before_commit(session):
            self.insert_owner_row()

        event.listen(db.session, "before_commit", inject_owner_before_commit)
        try:
            result = AuthService.seed_owner_if_empty()
        finally:
            event.remove(db.session, "before_commit", inject_owner_before_commit)

        self.assertEqual(result.username, "owner")
        self.assertEqual(User.query.filter_by(username="owner").count(), 1)
        self.assertEqual(User.query.filter_by(username="observer").first().username, "observer")
        self.assertEqual(User.query.count(), 2)

    def test_seed_owner_raises_when_integrity_error_and_owner_still_missing(self):
        self.create_user("observer-2", password="observer-pass", full_name="Observer 2", role="STAFF")
        original_add = db.session.add
        duplicate_added = False

        def add_duplicate_owner(obj):
            nonlocal duplicate_added
            original_add(obj)
            if isinstance(obj, User) and obj.username == "owner" and not duplicate_added:
                duplicate_added = True
                duplicate_owner = User(
                    username="owner",
                    full_name="Chá»§ Spa",
                    role="OWNER",
                    is_active=True,
                )
                duplicate_owner.set_password("duplicate-pass")
                original_add(duplicate_owner)

        with patch("services.auth_service.db.session.add", side_effect=add_duplicate_owner):
            with self.assertRaises(IntegrityError):
                AuthService.seed_owner_if_empty()

        self.assertIsNone(User.query.filter_by(username="owner").first())
        self.assertEqual(User.query.filter_by(username="observer-2").first().username, "observer-2")
        self.assertEqual(User.query.count(), 1)

    def test_seed_owner_session_still_queryable_after_rollback(self):
        self.create_user("session-check", password="session-pass", full_name="Session Check", role="STAFF")
        original_add = db.session.add
        duplicate_added = False

        def add_duplicate_owner(obj):
            nonlocal duplicate_added
            original_add(obj)
            if isinstance(obj, User) and obj.username == "owner" and not duplicate_added:
                duplicate_added = True
                duplicate_owner = User(
                    username="owner",
                    full_name="Chá»§ Spa",
                    role="OWNER",
                    is_active=True,
                )
                duplicate_owner.set_password("duplicate-pass")
                original_add(duplicate_owner)

        with patch("services.auth_service.db.session.add", side_effect=add_duplicate_owner):
            with self.assertRaises(IntegrityError):
                AuthService.seed_owner_if_empty()

        query_result = User.query.filter_by(username="session-check").first()
        self.assertIsNotNone(query_result)
        self.assertEqual(query_result.username, "session-check")

    def test_seed_owner_multiple_calls_keep_single_owner(self):
        AuthService.seed_owner_if_empty()
        AuthService.seed_owner_if_empty()
        AuthService.seed_owner_if_empty()

        self.assertEqual(User.query.filter_by(username="owner").count(), 1)
        self.assertEqual(User.query.count(), 1)

    def test_customer_delete_records_deleted_by(self):
        owner = AuthService.seed_owner_if_empty()
        customer = self.create_customer_record("Audit Customer")
        self.login_as(owner)

        response = self.post_with_csrf(f"/customers/{customer.id}/delete", path="/customers")

        self.assertEqual(response.status_code, 302)
        deleted_customer = Customer.query.get(customer.id)
        self.assertIsNotNone(deleted_customer)
        self.assertEqual(deleted_customer.deleted_by, "owner")

    def test_customer_restore_clears_deleted_by(self):
        owner = AuthService.seed_owner_if_empty()
        customer = self.create_customer_record("Restore Customer")
        self.login_as(owner)
        self.post_with_csrf(f"/customers/{customer.id}/delete", path="/customers")

        response = self.post_with_csrf(f"/recycle-bin/restore/Customer/{customer.id}", path="/recycle-bin")

        self.assertEqual(response.status_code, 200)
        restored_customer = Customer.query.get(customer.id)
        self.assertIsNotNone(restored_customer)
        self.assertIsNone(restored_customer.deleted_at)
        self.assertIsNone(restored_customer.deleted_by)

    def test_customer_detail_requires_login(self):
        customer = self.create_customer_record("Anonymous Detail Customer")

        response = self.client.get(f"/customers/{customer.id}", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_customer_detail_visible_for_staff_owner_and_admin(self):
        owner = AuthService.seed_owner_if_empty()
        admin = self.create_user("detail-admin", password="admin-pass", full_name="Detail Admin", role="ADMIN")
        staff = self.create_user("detail-staff", password="staff-pass", full_name="Detail Staff", role="STAFF")
        customer = self.create_customer_record("Detail Customer")

        for user in (staff, admin, owner):
            self.login_as(user)
            response = self.client.get(f"/customers/{customer.id}")
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn("Chi tiết Khách hàng", html)
            self.assertIn(customer.name, html)
            self.assertIn("Tổng lịch hẹn", html)
            self.assertIn("Tổng hóa đơn", html)

    def test_customer_detail_shows_history_and_quick_actions(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        customer = self.create_customer_record("History Customer")
        other_customer = self.create_customer_record("Other History Customer")
        service = self.create_service_record("History Service")
        other_service = self.create_service_record("Other History Service")

        appointment = Appointment(
            customer_id=customer.id,
            service_id=service.id,
            appointment_time=datetime(2026, 7, 4, 9, 30),
            status="CONFIRMED",
            notes="Ghi chú lịch hẹn"
        )
        db.session.add(appointment)

        invoice = self.create_invoice_record(customer, service)
        invoice.payment_method = "CARD"
        db.session.commit()
        other_appointment = Appointment(
            customer_id=other_customer.id,
            service_id=other_service.id,
            appointment_time=datetime(2026, 7, 4, 11, 0),
            status="Pending",
            notes="Không nên xuất hiện"
        )
        db.session.add(other_appointment)
        db.session.commit()

        response = self.client.get(f"/customers/{customer.id}")
        html = response.get_data(as_text=True)
        normalized_html = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()

        self.assertEqual(response.status_code, 200)
        self.assertIn("History Customer", html)
        self.assertIn("History Service", html)
        self.assertIn("Ghi chú lịch hẹn", html)
        self.assertIn(f"HD{invoice.id}", html)
        self.assertIn("Đã xác nhận", html)
        self.assertIn("Thẻ", html)
        self.assertIn("/appointments/create?customer_id=", html)
        self.assertIn("/invoices/create?customer_id=", html)
        self.assertIn("history-action-btn", html)
        self.assertIn("invoice-history-actions", html)
        self.assertIn("Hiển thị 1 - 1 trong tổng số 1 lịch hẹn", normalized_html)
        self.assertIn("Hiển thị 1 - 1 trong tổng số 1 hóa đơn", normalized_html)
        self.assertIn("Mỗi trang", html)
        self.assertIn("&laquo;&laquo;", html)
        self.assertIn("&raquo;&raquo;", html)
        self.assertNotIn("Other History Customer", html)
        self.assertNotIn("Không nên xuất hiện", html)
        self.assertNotIn("PENDING", html)
        self.assertNotIn("CONFIRMED", html)
        self.assertNotIn("CARD", html)

        invalid_response = self.client.get(f"/customers/{customer.id}?appointment_page=abc&invoice_page=-1")
        invalid_html = invalid_response.get_data(as_text=True)
        normalized_invalid_html = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", invalid_html)).strip()
        self.assertEqual(invalid_response.status_code, 200)
        self.assertIn("Hiển thị 1 - 1 trong tổng số 1 lịch hẹn", normalized_invalid_html)
        self.assertIn("Hiển thị 1 - 1 trong tổng số 1 hóa đơn", normalized_invalid_html)
        self.assertIn("Mỗi trang", invalid_html)

    def test_customer_detail_paginates_appointments_and_invoices_independently(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        customer = self.create_customer_record("Paginate Customer")
        service = self.create_service_record("Paginate Service")

        appointment_ids = []
        for index in range(11):
            appointment = Appointment(
                customer_id=customer.id,
                service_id=service.id,
                appointment_time=datetime(2026, 7, 4, 8, 0) + timedelta(days=index),
                status="Confirmed" if index % 2 == 0 else "Pending",
                notes=f"Appointment {index + 1}"
            )
            db.session.add(appointment)
            db.session.flush()
            appointment_ids.append(appointment.id)

        invoice_ids = []
        for index in range(11):
            invoice = Invoice(
                customer_id=customer.id,
                invoice_date=datetime(2026, 7, 4).date(),
                subtotal=100000 + index,
                discount=0,
                total_amount=100000 + index,
                payment_method="Cash",
                notes=f"Invoice {index + 1}"
            )
            db.session.add(invoice)
            db.session.flush()
            detail = InvoiceDetail(
                invoice_id=invoice.id,
                service_id=service.id,
                price=100000 + index,
                quantity=1
            )
            db.session.add(detail)
            invoice_ids.append(invoice.id)
        db.session.commit()

        page1_html = self.client.get(f"/customers/{customer.id}").get_data(as_text=True)
        page2_html = self.client.get(
            f"/customers/{customer.id}?appointment_page=2&appointment_per_page=10&invoice_page=1&invoice_per_page=10"
        ).get_data(as_text=True)
        invoice_page2_html = self.client.get(
            f"/customers/{customer.id}?appointment_page=1&appointment_per_page=10&invoice_page=2&invoice_per_page=10"
        ).get_data(as_text=True)
        mixed_html = self.client.get(
            f"/customers/{customer.id}?appointment_page=2&appointment_per_page=10&invoice_page=2&invoice_per_page=10"
        ).get_data(as_text=True)
        mixed_page_size_html = self.client.get(
            f"/customers/{customer.id}?appointment_page=1&appointment_per_page=25&invoice_page=2&invoice_per_page=10"
        ).get_data(as_text=True)

        self.assertIn("Appointment 11", page1_html)
        self.assertIn("Appointment 1", page2_html)
        self.assertNotIn("Appointment 11", page2_html)
        self.assertIn("Invoice 1", invoice_page2_html)
        self.assertNotIn("Invoice 11", invoice_page2_html)
        self.assertIn("appointment_page=2", html_module.unescape(mixed_html))
        self.assertIn("appointment_per_page=10", html_module.unescape(mixed_html))
        self.assertIn("invoice_page=2", html_module.unescape(mixed_html))
        self.assertIn("invoice_per_page=10", html_module.unescape(mixed_html))
        self.assertIn("#appointment-history", html_module.unescape(mixed_html))
        self.assertIn("#invoice-history", html_module.unescape(mixed_html))
        normalized_mixed_html = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", mixed_html)).strip()
        self.assertIn("Hiển thị 11 - 11 trong tổng số 11 lịch hẹn", normalized_mixed_html)
        self.assertIn("Hiển thị 11 - 11 trong tổng số 11 hóa đơn", normalized_mixed_html)
        self.assertIn("appointment_per_page=25", html_module.unescape(mixed_page_size_html))
        self.assertIn("invoice_per_page=10", html_module.unescape(mixed_page_size_html))
        normalized_page_size_html = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", mixed_page_size_html)).strip()
        self.assertIn("Hiển thị 1 - 11 trong tổng số 11 lịch hẹn", normalized_page_size_html)
        self.assertIn("Hiển thị 11 - 11 trong tổng số 11 hóa đơn", normalized_page_size_html)
        self.assertIn("Mỗi trang", mixed_html)
        self.assertIn("Tổng lịch hẹn", mixed_html)
        self.assertIn("Tổng hóa đơn", mixed_html)
        self.assertIn("Lịch sử lịch hẹn", mixed_html)

    def test_customer_detail_hides_soft_deleted_history(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        customer = self.create_customer_record("Soft Delete Detail Customer")
        service = self.create_service_record("Soft Delete Detail Service")
        appointment = self.create_appointment_record(customer=customer, service=service)
        invoice = self.create_invoice_record(customer, service)

        appointment.deleted_at = datetime.utcnow()
        appointment.deleted_by = "owner"
        invoice.deleted_at = datetime.utcnow()
        invoice.deleted_by = "owner"
        db.session.commit()

        response = self.client.get(f"/customers/{customer.id}")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Chưa có lịch hẹn nào", html)
        self.assertIn("Chưa có hóa đơn nào", html)
        self.assertNotIn(service.name, html)
        self.assertNotIn(f"HD{invoice.id}", html)

    def test_customer_detail_404_for_missing_or_deleted_customer(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        customer = self.create_customer_record("Deleted Detail Customer")
        customer.deleted_at = datetime.utcnow()
        customer.deleted_by = "owner"
        db.session.commit()

        deleted_response = self.client.get(f"/customers/{customer.id}")
        missing_response = self.client.get("/customers/999999")

        self.assertEqual(deleted_response.status_code, 404)
        self.assertEqual(missing_response.status_code, 404)

    def test_customer_detail_back_url_round_trips_from_child_detail(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        customer = self.create_customer_record("Back URL Customer")
        service = self.create_service_record("Back URL Service")
        customer_id = customer.id
        service_id = service.id
        appointment = self.create_appointment_record(customer=customer, service=service)
        invoice = Invoice(
            customer_id=customer_id,
            invoice_date=datetime(2026, 7, 4).date(),
            subtotal=100000,
            discount=0,
            total_amount=100000,
            payment_method="Cash",
            notes="Back URL invoice"
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            InvoiceDetail(
                invoice_id=invoice.id,
                service_id=service_id,
                price=100000,
                quantity=1
            )
        )
        db.session.commit()

        customer_detail_url = f"/customers/{customer.id}?appointment_page=2&invoice_page=3"

        appointment_response = self.client.get(
            f"/appointments/detail/{appointment.id}",
            query_string={"return_to": customer_detail_url},
            follow_redirects=False
        )
        invoice_response = self.client.get(
            f"/invoices/{invoice.id}",
            query_string={"return_to": customer_detail_url},
            follow_redirects=False
        )

        self.assertEqual(appointment_response.status_code, 200)
        self.assertEqual(invoice_response.status_code, 200)
        appointment_html = html_module.unescape(appointment_response.get_data(as_text=True))
        invoice_html = html_module.unescape(invoice_response.get_data(as_text=True))
        self.assertIn(customer_detail_url, appointment_html)
        self.assertIn(customer_detail_url, invoice_html)

    def test_customer_detail_rejects_external_return_to(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        customer = self.create_customer_record("External Back URL Customer")
        service = self.create_service_record("External Back URL Service")
        appointment = self.create_appointment_record(customer=customer, service=service)
        invoice = self.create_invoice_record(customer, service)

        appointment_response = self.client.get(
            f"/appointments/detail/{appointment.id}",
            query_string={"return_to": "https://evil.com"},
            follow_redirects=False
        )
        invoice_response = self.client.get(
            f"/invoices/{invoice.id}",
            query_string={"return_to": "//evil.com"},
            follow_redirects=False
        )

        self.assertEqual(appointment_response.status_code, 200)
        self.assertEqual(invoice_response.status_code, 200)
        self.assertIn('/appointments', appointment_response.get_data(as_text=True))
        self.assertIn('/invoices', invoice_response.get_data(as_text=True))

    def test_customer_detail_template_is_scoped_and_utf8_safe(self):
        template = Path("templates/customer/detail.html").read_text(encoding="utf-8")

        self.assertIn("customer-detail-page", template)
        self.assertIn("Chi tiết Khách hàng", template)
        self.assertIn("Lịch sử lịch hẹn", template)
        self.assertIn("Hóa đơn liên quan", template)
        for marker in ("Ã", "á»", "áº", "Æ", "Ä", "Â"):
            self.assertNotIn(marker, template)

    def test_customer_detail_quick_actions_prefill_related_creates(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        customer = self.create_customer_record("Quick Action Customer")

        appointment_html = self.client.get(f"/appointments/create?customer_id={customer.id}").get_data(as_text=True)
        invoice_html = self.client.get(f"/invoices/create?customer_id={customer.id}").get_data(as_text=True)

        self.assertIn(str(customer.id), appointment_html)
        self.assertIn(customer.name, appointment_html)
        self.assertIn(str(customer.id), invoice_html)
        self.assertIn(customer.name, invoice_html)

    def test_soft_delete_records_deleted_by_for_service_appointment_and_invoice(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        service = self.create_service_record("Audit Service")
        service_result = self.post_with_csrf(
            f"/services/delete/{service.id}",
            path="/services",
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(service_result.status_code, 200)
        self.assertEqual(Service.query.get(service.id).deleted_by, "owner")

        appointment = self.create_appointment_record()
        appointment_result = self.post_with_csrf(
            f"/appointments/delete/{appointment.id}",
            path="/appointments",
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(appointment_result.status_code, 200)
        self.assertEqual(Appointment.query.get(appointment.id).deleted_by, "owner")

        invoice = self.create_invoice_record()
        invoice_result = self.post_with_csrf(
            f"/invoices/delete/{invoice.id}",
            path="/invoices",
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(invoice_result.status_code, 200)
        self.assertEqual(Invoice.query.get(invoice.id).deleted_by, "owner")

    def test_appointment_pages_render_hidden_csrf_token(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        self.create_customer_record("Appointment Render Customer")
        self.create_service_record("Appointment Render Service")
        appointment = self.create_appointment_record()

        create_html = self.client.get("/appointments/create").get_data(as_text=True)
        edit_html = self.client.get(f"/appointments/edit/{appointment.id}").get_data(as_text=True)
        index_html = self.client.get("/appointments").get_data(as_text=True)

        self.assertIn('name="csrf_token"', create_html)
        self.assertIn('name="csrf_token"', edit_html)
        self.assertIn('name="csrf_token"', index_html)

    def test_appointment_create_requires_and_accepts_csrf_token(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        customer = self.create_customer_record("Appointment Create Customer")
        service = self.create_service_record("Appointment Create Service")
        before_count = Appointment.query.count()

        missing = self.client.post(
            "/appointments/create",
            data={
                "customer_id": customer.id,
                "service_id": service.id,
                "appointment_date": "2026-07-04",
                "appointment_time": "10:00",
                "status": "Pending",
                "notes": "Test create",
            },
            follow_redirects=False
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(Appointment.query.count(), before_count)

        token = self.get_csrf_token("/appointments/create")
        response = self.client.post(
            "/appointments/create",
            data={
                "customer_id": customer.id,
                "service_id": service.id,
                "appointment_date": "2026-07-04",
                "appointment_time": "10:00",
                "status": "Pending",
                "notes": "Test create",
            },
            headers={"X-CSRFToken": token},
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Appointment.query.count(), before_count + 1)

    def test_appointment_edit_requires_and_accepts_csrf_token(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        appointment = self.create_appointment_record()
        customer = self.create_customer_record("Appointment Edit Customer")
        service = self.create_service_record("Appointment Edit Service")

        missing = self.client.post(
            f"/appointments/edit/{appointment.id}",
            data={
                "customer_id": customer.id,
                "service_id": service.id,
                "appointment_time": "2026-07-05T11:30",
                "status": "Confirmed",
                "notes": "Edited",
            },
            follow_redirects=False
        )
        self.assertEqual(missing.status_code, 400)
        untouched = Appointment.query.get(appointment.id)
        self.assertEqual(untouched.status, "Pending")

        token = self.get_csrf_token(f"/appointments/edit/{appointment.id}")
        response = self.client.post(
            f"/appointments/edit/{appointment.id}",
            data={
                "customer_id": customer.id,
                "service_id": service.id,
                "appointment_time": "2026-07-05T11:30",
                "status": "Confirmed",
                "notes": "Edited",
            },
            headers={"X-CSRFToken": token},
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 302)
        updated = Appointment.query.get(appointment.id)
        self.assertEqual(updated.status, "Confirmed")

    def test_appointment_update_status_requires_header_token(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        appointment = self.create_appointment_record()
        token = self.get_csrf_token("/appointments")

        success = self.client.post(
            "/appointments/update_status",
            json={"id": appointment.id, "status": "Confirmed"},
            headers={"X-CSRFToken": token}
        )
        self.assertEqual(success.status_code, 200)
        self.assertEqual(Appointment.query.get(appointment.id).status, "Confirmed")

        self.create_appointment_record()
        missing = self.client.post(
            "/appointments/update_status",
            json={"id": appointment.id, "status": "Completed"}
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(Appointment.query.get(appointment.id).status, "Confirmed")

    def test_appointment_delete_requires_csrf_token(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        appointment = self.create_appointment_record()

        missing = self.client.post(f"/appointments/delete/{appointment.id}")
        self.assertEqual(missing.status_code, 400)
        untouched = Appointment.query.get(appointment.id)
        self.assertIsNone(untouched.deleted_at)
        self.assertIsNone(untouched.deleted_by)

        response = self.post_with_csrf(
            f"/appointments/delete/{appointment.id}",
            path="/appointments",
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(response.status_code, 200)
        deleted = Appointment.query.get(appointment.id)
        self.assertIsNotNone(deleted.deleted_at)
        self.assertEqual(deleted.deleted_by, "owner")

    def test_appointment_calendar_script_uses_csrf_token_for_delete_form(self):
        source = Path("static/js/appointment-calendar.js").read_text(encoding="utf-8")
        self.assertIn("window.SpaCsrf.getToken()", source)
        self.assertIn('name="csrf_token"', source)

    def test_appointment_calendar_detail_panel_has_scrollable_body_and_mobile_drawer_rules(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        css = Path("static/css/pages/appointment-calendar.css").read_text(encoding="utf-8")
        html = self.client.get("/appointments").get_data(as_text=True)

        self.assertIn('id="calOffcanvas"', html)
        self.assertIn('btn-close', html)
        self.assertIn('.cal-offcanvas .offcanvas-body', css)
        self.assertIn('overflow-y: auto', css)
        self.assertIn('height: 100dvh', css)
        self.assertIn('width: 100vw', css)
        self.assertIn('@media (max-width: 768px)', css)

    def test_permanent_delete_logs_current_actor_before_removal(self):
        owner = AuthService.seed_owner_if_empty()
        customer = self.create_customer_record("Permanent Customer")
        self.login_as(owner)
        self.post_with_csrf(f"/customers/{customer.id}/delete", path="/customers")

        response = self.post_with_csrf(f"/recycle-bin/delete/Customer/{customer.id}", path="/recycle-bin")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(Customer.query.get(customer.id))
        log_entry = ActivityLog.query.filter_by(
            module=ActivityLogService.MODULE_CUSTOMER,
            action="PERMANENT_DELETE",
            reference_id=customer.id
        ).order_by(ActivityLog.id.desc()).first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.user_id, owner.id)
        self.assertIn("owner", log_entry.description)

    def test_delete_without_login_does_not_change_data(self):
        customer = self.create_customer_record("Anonymous Customer")

        response = self.client.post(f"/customers/{customer.id}/delete")

        self.assertEqual(response.status_code, 302)
        untouched_customer = Customer.query.get(customer.id)
        self.assertIsNotNone(untouched_customer)
        self.assertIsNone(untouched_customer.deleted_at)
        self.assertIsNone(untouched_customer.deleted_by)
        self.assertEqual(ActivityLog.query.filter_by(reference_id=customer.id).count(), 0)

    def test_stale_session_user_is_rejected(self):
        customer = self.create_customer_record("Stale Session Customer")
        with self.client.session_transaction() as sess:
            sess[AUTH_SESSION_KEY] = 999999

        response = self.client.post(f"/customers/{customer.id}/delete")

        self.assertEqual(response.status_code, 302)
        untouched_customer = Customer.query.get(customer.id)
        self.assertIsNone(untouched_customer.deleted_at)
        self.assertIsNone(untouched_customer.deleted_by)
        self.assertEqual(ActivityLog.query.filter_by(reference_id=customer.id).count(), 0)

    def test_service_delete_outside_request_requires_actor(self):
        service = self.create_service_record("No Actor Service")
        service_id = service.id

        with self.assertRaises(AuthenticationException):
            ServiceService.delete_service(service_id)

        untouched_service = Service.query.get(service_id)
        self.assertIsNone(untouched_service.deleted_at)
        self.assertIsNone(untouched_service.deleted_by)

    def test_background_actor_system_is_only_explicit(self):
        service = self.create_service_record("System Actor Service")

        result = ServiceService.delete_service(service.id, actor="Há»‡ thá»‘ng")

        self.assertTrue(result)
        deleted_service = Service.query.get(service.id)
        self.assertEqual(deleted_service.deleted_by, "Há»‡ thá»‘ng")
        self.assertEqual(ActivityLog.query.filter_by(reference_id=service.id).count(), 1)

    def test_user_management_is_manager_only(self):
        staff = self.create_user("staff-user", password="staff-pass", full_name="Staff User", role="STAFF")
        admin = self.create_user("admin-user", password="admin-pass", full_name="Admin User", role="ADMIN")
        owner = self.create_user("owner-user", password="owner-pass", full_name="Owner User", role="OWNER")

        self.login_as(staff)
        staff_response = self.client.get("/users", follow_redirects=False)
        self.assertEqual(staff_response.status_code, 403)

        with self.client.session_transaction() as sess:
            sess.clear()

        self.login_as(admin)
        admin_response = self.client.get("/users", follow_redirects=False)
        self.assertEqual(admin_response.status_code, 200)
        self.assertIn("Quản lý Người dùng", admin_response.get_data(as_text=True))

        with self.client.session_transaction() as sess:
            sess.clear()

        self.login_as(owner)
        owner_response = self.client.get("/users", follow_redirects=False)
        self.assertEqual(owner_response.status_code, 200)
        self.assertIn("Quản lý Người dùng", owner_response.get_data(as_text=True))

    def test_user_create_edit_reset_toggle_and_logs_work_with_csrf(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        create_token = self.get_csrf_token("/users/create")
        create_response = self.client.post(
            "/users/create",
            data={
                "username": "staff-live",
                "full_name": "Staff Live",
                "email": "staff-live@example.com",
                "role": "STAFF",
                "password": "StrongPass123",
                "confirm_password": "StrongPass123",
                "is_active": "1",
            },
            headers={"X-CSRFToken": create_token},
            follow_redirects=False
        )

        self.assertEqual(create_response.status_code, 302)
        created_user = User.query.filter_by(username="staff-live").first()
        self.assertIsNotNone(created_user)
        self.assertTrue(created_user.check_password("StrongPass123"))
        create_log = ActivityLog.query.filter_by(
            module="Users",
            action="CREATE_USER",
            reference_id=created_user.id
        ).order_by(ActivityLog.id.desc()).first()
        self.assertIsNotNone(create_log)
        self.assertEqual(create_log.user_id, owner.id)

        edit_token = self.get_csrf_token(f"/users/{created_user.id}/edit")
        edit_response = self.client.post(
            f"/users/{created_user.id}/edit",
            data={
                "username": "staff-live-updated",
                "full_name": "Staff Live Updated",
                "email": "staff-live-updated@example.com",
                "role": "ADMIN",
            },
            headers={"X-CSRFToken": edit_token},
            follow_redirects=False
        )

        self.assertEqual(edit_response.status_code, 302)
        updated_user = User.query.get(created_user.id)
        self.assertEqual(updated_user.username, "staff-live-updated")
        self.assertEqual(updated_user.full_name, "Staff Live Updated")
        self.assertEqual(updated_user.role, "ADMIN")
        edit_log = ActivityLog.query.filter_by(
            module="Users",
            action="UPDATE_USER",
            reference_id=created_user.id
        ).order_by(ActivityLog.id.desc()).first()
        self.assertIsNotNone(edit_log)
        self.assertEqual(edit_log.user_id, owner.id)

        reset_token = self.get_csrf_token(f"/users/{created_user.id}/reset-password")
        reset_response = self.client.post(
            f"/users/{created_user.id}/reset-password",
            data={
                "new_password": "AnotherStrong123",
                "confirm_password": "AnotherStrong123",
            },
            headers={"X-CSRFToken": reset_token},
            follow_redirects=False
        )

        self.assertEqual(reset_response.status_code, 302)
        refreshed_user = User.query.get(created_user.id)
        self.assertTrue(refreshed_user.check_password("AnotherStrong123"))
        reset_log = ActivityLog.query.filter_by(
            module="Users",
            action="RESET_USER_PASSWORD",
            reference_id=created_user.id
        ).order_by(ActivityLog.id.desc()).first()
        self.assertIsNotNone(reset_log)
        self.assertEqual(reset_log.user_id, owner.id)

        toggle_token = self.get_csrf_token("/users")
        deactivate_response = self.client.post(
            f"/users/{created_user.id}/toggle-active",
            data={"is_active": "0"},
            headers={"X-CSRFToken": toggle_token},
            follow_redirects=False
        )
        self.assertEqual(deactivate_response.status_code, 302)
        self.assertFalse(User.query.get(created_user.id).is_active)

        toggle_token = self.get_csrf_token("/users")
        activate_response = self.client.post(
            f"/users/{created_user.id}/toggle-active",
            data={"is_active": "1"},
            headers={"X-CSRFToken": toggle_token},
            follow_redirects=False
        )
        self.assertEqual(activate_response.status_code, 302)
        self.assertTrue(User.query.get(created_user.id).is_active)

    def test_user_management_blocks_self_disable_and_self_role_demotion(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        self_disable_token = self.get_csrf_token("/users")
        self_disable_response = self.client.post(
            f"/users/{owner.id}/toggle-active",
            data={"is_active": "0"},
            headers={"X-CSRFToken": self_disable_token},
            follow_redirects=False
        )
        self.assertEqual(self_disable_response.status_code, 302)
        self.assertTrue(User.query.get(owner.id).is_active)

        edit_token = self.get_csrf_token(f"/users/{owner.id}/edit")
        self_demote_response = self.client.post(
            f"/users/{owner.id}/edit",
            data={
                "username": owner.username,
                "full_name": owner.full_name,
                "email": owner.email or "",
                "role": "STAFF",
            },
            headers={"X-CSRFToken": edit_token},
            follow_redirects=False
        )
        self.assertEqual(self_demote_response.status_code, 200)
        self.assertEqual(User.query.get(owner.id).role, "OWNER")

        second_owner = self.create_user("second-owner", password="second-pass", full_name="Second Owner", role="OWNER")
        second_owner_token = self.get_csrf_token("/users")
        second_owner_response = self.client.post(
            f"/users/{second_owner.id}/toggle-active",
            data={"is_active": "0"},
            headers={"X-CSRFToken": second_owner_token},
            follow_redirects=False
        )
        self.assertEqual(second_owner_response.status_code, 302)
        self.assertFalse(User.query.get(second_owner.id).is_active)

    def test_user_validation_and_csrf_guards(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        missing_csrf = self.client.post(
            "/users/create",
            data={
                "username": "csrf-user",
                "full_name": "CSRF User",
                "email": "csrf-user@example.com",
                "role": "STAFF",
                "password": "StrongPass123",
                "confirm_password": "StrongPass123",
            },
            follow_redirects=False
        )
        self.assertEqual(missing_csrf.status_code, 400)
        self.assertIsNone(User.query.filter_by(username="csrf-user").first())

        create_token = self.get_csrf_token("/users/create")
        self.client.post(
            "/users/create",
            data={
                "username": "duplicate-user",
                "full_name": "Duplicate One",
                "email": "duplicate-one@example.com",
                "role": "STAFF",
                "password": "StrongPass123",
                "confirm_password": "StrongPass123",
            },
            headers={"X-CSRFToken": create_token},
            follow_redirects=False
        )

        duplicate_token = self.get_csrf_token("/users/create")
        duplicate_response = self.client.post(
            "/users/create",
            data={
                "username": "duplicate-user",
                "full_name": "Duplicate Two",
                "email": "duplicate-two@example.com",
                "role": "STAFF",
                "password": "StrongPass123",
                "confirm_password": "StrongPass123",
            },
            headers={"X-CSRFToken": duplicate_token},
            follow_redirects=False
        )
        self.assertIn(duplicate_response.status_code, (200, 400))
        self.assertEqual(User.query.filter_by(username="duplicate-user").count(), 1)
        self.assertEqual(ActivityLog.query.filter_by(module="Users", action="CREATE_USER").count(), 1)

        mismatch_token = self.get_csrf_token("/users/create")
        mismatch_response = self.client.post(
            "/users/create",
            data={
                "username": "mismatch-user",
                "full_name": "Mismatch User",
                "email": "mismatch-user@example.com",
                "role": "STAFF",
                "password": "StrongPass123",
                "confirm_password": "DifferentPass123",
            },
            headers={"X-CSRFToken": mismatch_token},
            follow_redirects=False
        )
        self.assertEqual(mismatch_response.status_code, 400)
        self.assertIsNone(User.query.filter_by(username="mismatch-user").first())
        self.assertEqual(ActivityLog.query.filter_by(module="Users", action="CREATE_USER").count(), 1)

    def test_user_password_reset_login_and_enable_disable_flow(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        staff = self.create_user("flow-user", password="OldPass123", full_name="Flow User", role="STAFF")
        def get_token_for(client, path):
            response = client.get(path)
            html = response.get_data(as_text=True)
            match = re.search(r'name="csrf-token" content="([^"]+)"', html)
            if not match:
                match = re.search(r'name="csrf_token" value="([^"]+)"', html)
            self.assertIsNotNone(match)
            return match.group(1)

        reset_token = self.get_csrf_token(f"/users/{staff.id}/reset-password")
        reset_response = self.client.post(
            f"/users/{staff.id}/reset-password",
            data={
                "new_password": "NewPass123",
                "confirm_password": "NewPass123",
            },
            headers={"X-CSRFToken": reset_token},
            follow_redirects=False
        )
        self.assertEqual(reset_response.status_code, 302)
        self.assertTrue(User.query.get(staff.id).check_password("NewPass123"))

        login_client = app.test_client()
        login_token = get_token_for(login_client, "/login")
        login_response = login_client.post(
            "/login",
            json={
                "username": "flow-user",
                "password": "NewPass123",
                "remember": False,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": login_token,
            },
            follow_redirects=False
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.get_json()["success"])

        self.login_as(owner)
        disable_token = self.get_csrf_token("/users")
        disable_response = self.client.post(
            f"/users/{staff.id}/toggle-active",
            data={"is_active": "0"},
            headers={"X-CSRFToken": disable_token},
            follow_redirects=False
        )
        self.assertEqual(disable_response.status_code, 302)
        self.assertFalse(User.query.get(staff.id).is_active)

        disabled_login_client = app.test_client()
        login_token = get_token_for(disabled_login_client, "/login")
        disabled_login = disabled_login_client.post(
            "/login",
            json={
                "username": "flow-user",
                "password": "NewPass123",
                "remember": False,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": login_token,
            },
            follow_redirects=False
        )
        self.assertEqual(disabled_login.status_code, 401)
        self.assertFalse(disabled_login.get_json()["success"])

        self.login_as(owner)
        enable_token = self.get_csrf_token("/users")
        enable_response = self.client.post(
            f"/users/{staff.id}/toggle-active",
            data={"is_active": "1"},
            headers={"X-CSRFToken": enable_token},
            follow_redirects=False
        )
        self.assertEqual(enable_response.status_code, 302)
        self.assertTrue(User.query.get(staff.id).is_active)

        enabled_login_client = app.test_client()
        login_token = get_token_for(enabled_login_client, "/login")
        enabled_login = enabled_login_client.post(
            "/login",
            json={
                "username": "flow-user",
                "password": "NewPass123",
                "remember": False,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": login_token,
            },
            follow_redirects=False
        )
        self.assertEqual(enabled_login.status_code, 200)
        self.assertTrue(enabled_login.get_json()["success"])

    def test_legacy_lowercase_manager_role_still_has_access(self):
        legacy_admin = User(
            username="legacy-admin",
            full_name="Legacy Admin",
            role="admin",
            is_active=True,
        )
        legacy_admin.set_password("LegacyPass123")
        db.session.add(legacy_admin)
        db.session.commit()
        self.login_as(legacy_admin)

        response = self.client.get("/users", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Quản lý Người dùng", response.get_data(as_text=True))

    def test_permission_helpers_follow_role_and_activity_state(self):
        owner = self.create_user("perm-owner", password="owner-pass", full_name="Perm Owner", role="OWNER")
        admin = self.create_user("perm-admin", password="admin-pass", full_name="Perm Admin", role="ADMIN")
        staff = self.create_user("perm-staff", password="staff-pass", full_name="Perm Staff", role="STAFF")
        inactive_admin = self.create_user("perm-inactive", password="inactive-pass", full_name="Perm Inactive", role="ADMIN")
        inactive_admin.is_active = False
        db.session.commit()

        self.assertTrue(is_owner(owner))
        self.assertTrue(is_admin(admin))
        self.assertTrue(is_staff(staff))
        self.assertTrue(is_manager(owner))
        self.assertTrue(is_manager(admin))
        self.assertFalse(is_manager(staff))
        self.assertFalse(is_manager(inactive_admin))
        self.assertFalse(is_manager(None))
        self.assertTrue(can_manage_users(owner))
        self.assertTrue(can_manage_users(admin))
        self.assertFalse(can_manage_users(staff))
        self.assertTrue(can_manage_settings(owner))
        self.assertTrue(can_view_activity_logs(admin))
        self.assertTrue(can_manage_backups(owner))
        self.assertTrue(can_manage_business_data(staff))
        self.assertFalse(can_manage_business_data(inactive_admin))
        self.assertFalse(can_manage_business_data(None))

    def test_staff_cannot_see_admin_menus_in_sidebar(self):
        staff = self.create_user("sidebar-staff", password="staff-pass", full_name="Sidebar Staff", role="STAFF")
        owner = self.create_user("sidebar-owner", password="owner-pass", full_name="Sidebar Owner", role="OWNER")
        admin = self.create_user("sidebar-admin", password="admin-pass", full_name="Sidebar Admin", role="ADMIN")

        self.login_as(staff)
        staff_sidebar = self.client.get("/customers", follow_redirects=False).get_data(as_text=True)

        self.login_as(owner)
        owner_sidebar = self.client.get("/customers", follow_redirects=False).get_data(as_text=True)

        self.login_as(admin)
        admin_sidebar = self.client.get("/customers", follow_redirects=False).get_data(as_text=True)

        hidden_labels = ["Thống kê", "Nhật ký hoạt động", "Thùng rác", "Cài đặt", "Người dùng"]
        visible_labels = ["Khách hàng", "Dịch vụ", "Lịch hẹn", "Hóa đơn"]

        for label in hidden_labels:
            self.assertNotIn(label, staff_sidebar)
            self.assertIn(label, owner_sidebar)
            self.assertIn(label, admin_sidebar)

        for label in visible_labels:
            self.assertIn(label, staff_sidebar)
            self.assertIn(label, owner_sidebar)
            self.assertIn(label, admin_sidebar)
        self.assertLess(owner_sidebar.index("Người dùng"), owner_sidebar.index("Cài đặt"))
        self.assertLess(admin_sidebar.index("Người dùng"), admin_sidebar.index("Cài đặt"))

    def test_admin_routes_are_blocked_for_staff_but_available_to_owner_and_admin(self):
        staff = self.create_user("route-staff", password="staff-pass", full_name="Route Staff", role="STAFF")
        admin = self.create_user("route-admin", password="admin-pass", full_name="Route Admin", role="ADMIN")
        owner = self.create_user("route-owner", password="owner-pass", full_name="Route Owner", role="OWNER")

        protected_get_routes = [
            "/settings",
            "/activity-logs",
            "/recycle-bin",
            "/statistics",
        ]

        for user in (owner, admin):
            self.login_as(user)
            for route in protected_get_routes:
                response = self.client.get(route, follow_redirects=False)
                self.assertEqual(response.status_code, 200, route)

        self.login_as(staff)
        staff_token = self.get_csrf_token("/customers")

        for route in protected_get_routes:
            response = self.client.get(route, follow_redirects=False)
            self.assertEqual(response.status_code, 403, route)

        json_forbidden = self.client.get(
            "/activity-logs",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        self.assertEqual(json_forbidden.status_code, 403)
        self.assertTrue(json_forbidden.is_json)
        self.assertEqual(json_forbidden.get_json()["error"], "forbidden")

        before_spa_name = Setting.get("spa_name")
        Setting.set("spa_name", "Before Permission Check")
        blocked_post = self.client.post(
            "/settings/save-spa-info",
            data={
                "spa_name": "Should Not Save",
                "spa_owner": "Should Not Save",
                "spa_phone": "0900000000",
                "spa_email": "blocked@example.com",
                "spa_address": "Nope",
                "spa_open_time": "08:00",
                "spa_close_time": "20:00",
            },
            headers={"X-CSRFToken": staff_token},
            follow_redirects=False,
        )
        self.assertEqual(blocked_post.status_code, 403)
        self.assertEqual(Setting.get("spa_name"), "Before Permission Check")
        if before_spa_name is None:
            with db.engine.begin() as connection:
                connection.execute(text("DELETE FROM settings WHERE key = 'spa_name'"))
        else:
            Setting.set("spa_name", before_spa_name)

    def test_staff_still_has_access_to_business_modules(self):
        staff = self.create_user("business-staff", password="staff-pass", full_name="Business Staff", role="STAFF")
        self.login_as(staff)

        for route in ("/customers", "/services", "/appointments", "/invoices"):
            response = self.client.get(route, follow_redirects=False)
            self.assertEqual(response.status_code, 200, route)

    def test_activity_log_sanitizer_redacts_sensitive_keys(self):
        payload = {
            "username": "demo",
            "password": "secret123",
            "confirm_password": "secret123",
            "csrf_token": "csrf-abc",
            "nested": {
                "api_key": "api-123",
                "note": "keep-me",
            },
            "raw": "password=abc123 token=xyz csrf=zz",
        }

        sanitized = sanitize_activity_log_value(payload)

        self.assertIn("demo", sanitized)
        self.assertIn("***REDACTED***", sanitized)
        self.assertNotIn("secret123", sanitized)
        self.assertNotIn("csrf-abc", sanitized)
        self.assertNotIn("api-123", sanitized)
        self.assertNotIn("password=abc123", sanitized)
        self.assertNotIn("token=xyz", sanitized)

    def test_auth_activity_log_uses_actor_display_name(self):
        owner = self.create_user("owner-log", password="owner-pass", full_name="Chủ Spa", role="OWNER")
        self.assertEqual(get_activity_actor_display_name(owner), owner.username)

        login_token = self.get_csrf_token("/login")
        login_response = self.client.post(
            "/login",
            json={
                "username": "owner-log",
                "password": "owner-pass",
                "remember": False,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": login_token,
            },
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 200)

        login_log = ActivityLog.query.filter_by(action="LOGIN", user_id=owner.id).order_by(ActivityLog.id.desc()).first()
        self.assertIsNotNone(login_log)
        self.assertNotIn("Chủ Spa", login_log.description)
        self.assertTrue(login_log.description.startswith("owner-log"))
        self.assertIn("đăng nhập thành công", login_log.description)

        self.login_as(owner)
        AuthService.on_logout(owner)

        logout_log = ActivityLog.query.filter_by(action="LOGOUT", user_id=owner.id).order_by(ActivityLog.id.desc()).first()
        self.assertIsNotNone(logout_log)
        self.assertNotIn("Chủ Spa", logout_log.description)
        self.assertIn("đăng xuất khỏi hệ thống", logout_log.description)

        AuthService.on_profile_update_success(owner)
        profile_log = ActivityLog.query.filter_by(action="PROFILE_UPDATE", user_id=owner.id).order_by(ActivityLog.id.desc()).first()
        self.assertIsNotNone(profile_log)
        self.assertNotIn("Chủ Spa", profile_log.description)
        self.assertIn("cập nhật thông tin tài khoản", profile_log.description)

        regular_user = self.create_user("Truong", password="truong-pass", full_name="Văn Công Trường", role="ADMIN")
        self.assertEqual(get_activity_actor_display_name(regular_user), "Văn Công Trường")
        AuthService.on_login_success(regular_user)
        regular_login_log = ActivityLog.query.filter_by(action="LOGIN", user_id=regular_user.id).order_by(ActivityLog.id.desc()).first()
        self.assertIsNotNone(regular_login_log)
        self.assertNotIn("Chủ Spa", regular_login_log.description)
        self.assertIn("Văn Công Trường", regular_login_log.description)

    def test_activity_log_service_write_log_sanitizes_details_and_supports_actor_filter(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        actor = self.create_user("actor-filter", password="actor-pass", full_name="Actor Filter", role="ADMIN")

        with self.client.session_transaction() as sess:
            sess[AUTH_SESSION_KEY] = actor.id

        ActivityLogService.write_log(
            module="System",
            action="custom_event",
            description={
                "password": "abc123",
                "message": "audit payload",
                "csrf_token": "csrf-x",
            },
            reference_id=77,
            severity="warning",
            user_id_override=actor.id,
        )

        stored_log = ActivityLog.query.order_by(ActivityLog.id.desc()).first()
        self.assertIsNotNone(stored_log)
        self.assertEqual(stored_log.action, "CUSTOM_EVENT")
        self.assertEqual(stored_log.severity, "WARNING")
        self.assertEqual(stored_log.user_id, actor.id)
        self.assertNotIn("abc123", stored_log.description)
        self.assertNotIn("csrf-x", stored_log.description)

        filtered = ActivityLogService.get_filtered_logs(
            page=1,
            per_page=20,
            actor="actor-filter",
        )
        self.assertGreaterEqual(filtered.total, 1)
        self.assertTrue(any(log.user_id == actor.id for log in filtered.items))

    def test_disabled_user_session_is_blocked_on_next_request(self):
        owner = AuthService.seed_owner_if_empty()
        staff = self.create_user("session-disabled", password="SessionPass123", full_name="Session Disabled", role="STAFF")

        staff_client = app.test_client()
        staff_login_html = staff_client.get("/login").get_data(as_text=True)
        staff_login_token = re.search(r'name="csrf-token" content="([^"]+)"', staff_login_html).group(1)
        staff_login = staff_client.post(
            "/login",
            json={
                "username": "session-disabled",
                "password": "SessionPass123",
                "remember": False,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": staff_login_token,
            },
            follow_redirects=False
        )
        self.assertEqual(staff_login.status_code, 200)

        self.login_as(owner)
        disable_token = self.get_csrf_token("/users")
        disable_response = self.client.post(
            f"/users/{staff.id}/toggle-active",
            data={"is_active": "0"},
            headers={"X-CSRFToken": disable_token},
            follow_redirects=False
        )
        self.assertEqual(disable_response.status_code, 302)
        self.assertFalse(User.query.get(staff.id).is_active)

        blocked_response = staff_client.get("/customers", follow_redirects=False)
        self.assertEqual(blocked_response.status_code, 302)
        self.assertIn("/login", blocked_response.headers.get("Location", ""))

    def test_two_users_write_two_different_deleted_by_values(self):
        user_a = self.create_user("user-a", password="pass-a", full_name="User A", role="STAFF")
        user_b = self.create_user("user-b", password="pass-b", full_name="User B", role="STAFF")

        customer_a = self.create_customer_record("Customer A")
        customer_b = self.create_customer_record("Customer B")

        self.login_as(user_a)
        self.post_with_csrf(f"/customers/{customer_a.id}/delete", path="/customers")

        self.login_as(user_b)
        self.post_with_csrf(f"/customers/{customer_b.id}/delete", path="/customers")

        self.assertEqual(Customer.query.get(customer_a.id).deleted_by, "user-a")
        self.assertEqual(Customer.query.get(customer_b.id).deleted_by, "user-b")
        self.assertEqual(
            ActivityLog.query.filter(ActivityLog.module == ActivityLogService.MODULE_CUSTOMER)
            .filter(ActivityLog.reference_id.in_([customer_a.id, customer_b.id]))
            .count(),
            2
        )

    def test_commit_failure_rolls_back_record_and_log(self):
        owner = AuthService.seed_owner_if_empty()
        customer = self.create_customer_record("Rollback Customer")
        customer_id = customer.id
        self.login_as(owner)
        before_logs = ActivityLog.query.filter_by(reference_id=customer_id).count()

        def fail_commit():
            raise SQLAlchemyError("commit failed")

        with patch("services.customer_service.db.session.commit", side_effect=fail_commit):
            with self.assertRaises(SQLAlchemyError):
                CustomerService.delete(customer_id, actor="owner")

        rolled_back_customer = Customer.query.get(customer_id)
        self.assertIsNone(rolled_back_customer.deleted_at)
        self.assertIsNone(rolled_back_customer.deleted_by)
        after_logs = ActivityLog.query.filter_by(reference_id=customer_id).count()
        self.assertEqual(after_logs, before_logs)

    def test_explicit_system_restore_is_allowed(self):
        customer = self.create_customer_record("System Restore Customer")
        customer.deleted_at = datetime.utcnow()
        customer.deleted_by = "legacy"
        db.session.commit()

        result = CustomerService.restore(customer.id, actor="Há»‡ thá»‘ng")

        self.assertTrue(result)
        restored_customer = Customer.query.get(customer.id)
        self.assertIsNone(restored_customer.deleted_at)
        self.assertIsNone(restored_customer.deleted_by)
        log_entry = ActivityLog.query.filter_by(reference_id=customer.id).order_by(ActivityLog.id.desc()).first()
        self.assertIsNotNone(log_entry)
        self.assertIn("Há»‡ thá»‘ng", log_entry.description)
        self.assertIsNone(log_entry.user_id)

    def test_recycle_bin_shows_fallback_for_missing_deleted_by(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        customer = self.create_customer_record("Unknown Customer")
        customer.deleted_at = datetime.utcnow()
        customer.deleted_by = None
        db.session.commit()

        response = self.client.get("/recycle-bin")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Không xác định", response.get_data(as_text=True))

    def test_production_requires_owner_password(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "prod-secret",
                "DATABASE_URL": "sqlite:///prod.sqlite",
                "DEFAULT_OWNER_PASSWORD": "",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                ProductionConfig()

    def test_production_reads_database_url_and_persistent_paths(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "prod-secret",
                "DATABASE_URL": "sqlite:////app/database/spa.db",
                "DEFAULT_OWNER_PASSWORD": "prod-owner-pass",
                "PERSISTENT_ROOT": "/app/database",
            },
            clear=True,
        ):
            config = ProductionConfig()

        self.assertEqual(config.SQLALCHEMY_DATABASE_URI, "sqlite:////app/database/spa.db")
        self.assertEqual(config.PERSISTENT_ROOT, "/app/database")
        self.assertEqual(config.UPLOAD_ROOT.replace("\\", "/"), "/app/database/uploads")
        self.assertEqual(config.LOGO_UPLOAD_FOLDER.replace("\\", "/"), "/app/database/uploads/logos")
        self.assertEqual(config.AVATAR_UPLOAD_FOLDER.replace("\\", "/"), "/app/database/uploads/avatars")
        self.assertFalse(config.DEBUG)

    def test_local_config_can_still_initialize(self):
        config = DevelopmentConfig()

        self.assertTrue(config.DEBUG)
        self.assertTrue(config.SQLALCHEMY_DATABASE_URI.startswith("sqlite:///"))
        self.assertEqual(config.DEFAULT_OWNER_USERNAME, "owner")
        self.assertEqual(config.DEFAULT_OWNER_PASSWORD, "owner123")
        self.assertEqual(config.APP_VERSION, "5.2.0")

    def test_google_oauth_variables_remain_optional(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "prod-secret",
                "DATABASE_URL": "sqlite:///prod.sqlite",
                "DEFAULT_OWNER_PASSWORD": "prod-owner-pass",
            },
            clear=True,
        ):
            config = ProductionConfig()

        self.assertEqual(config.GOOGLE_CLIENT_ID, "")
        self.assertEqual(config.GOOGLE_CLIENT_SECRET, "")
        self.assertEqual(config.GOOGLE_REDIRECT_URI, "")

    def test_readme_and_env_template_match_current_production_setup(self):
        readme = Path("README.md").read_text(encoding="utf-8")
        env_example = Path(".env.example").read_text(encoding="utf-8")
        changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
        workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("SpaManager is a Flask-based web app", readme)
        self.assertIn("Command Palette with `Ctrl+K`", readme)
        self.assertIn("badge.svg?branch=main", readme)
        self.assertIn("flask db upgrade", readme)
        self.assertIn("flask db stamp head", readme)
        self.assertIn("compileall .", readme)
        self.assertIn("DATABASE_URL=sqlite:///database/spa.db", env_example)
        self.assertIn("# DATABASE_URL=sqlite:////app/database/spa.db", env_example)
        self.assertIn("APP_VERSION=5.2.0", env_example)
        self.assertIn("v5.2.0", changelog)
        self.assertIn("change-this-to-a-strong-password", env_example)
        self.assertIn("CSRF_ENABLED=1", env_example)
        self.assertIn("python -m compileall .", workflow)
        self.assertNotIn("master", workflow)
        self.assertNotIn("owner123", readme)
        self.assertNotIn("owner123", env_example)
        self.assertNotIn("4.0.0", readme)

    def test_migration_commands_expose_baseline_revision(self):
        runner = app.test_cli_runner()

        current_before = runner.invoke(args=["db", "current"])
        self.assertEqual(current_before.exit_code, 0, current_before.output)
        self.assertIn("No revision stamp found", current_before.output)

        history = runner.invoke(args=["db", "history"])
        self.assertEqual(history.exit_code, 0, history.output)
        self.assertIn("0001_baseline", history.output)

    def test_db_upgrade_creates_schema_and_stamps_head(self):
        self.clear_database_schema()
        self.assertEqual(sa_inspect(db.engine).get_table_names(), [])

        runner = app.test_cli_runner()
        result = runner.invoke(args=["db", "upgrade"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Applied 0001_baseline", result.output)

        tables = sa_inspect(db.engine).get_table_names()
        self.assertIn("users", tables)
        self.assertIn("customers", tables)
        self.assertIn("alembic_version", tables)

        current_after = runner.invoke(args=["db", "current"])
        self.assertEqual(current_after.exit_code, 0, current_after.output)
        self.assertIn("0001_baseline", current_after.output)

    def test_version_is_rendered_from_config_in_setting_ui(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        response = self.client.get("/settings")
        html = response.get_data(as_text=True)
        self.assertIn("Spa Manager v5.2.0", html)
        self.assertIn("v5.2.0 Stable", html)
        self.assertIn(">5.2.0<", html)

    def test_sidebar_footer_shows_current_version(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)
        response = self.client.get("/")
        html = response.get_data(as_text=True)
        self.assertIn("Spa Manager v5.2.0", html)
        self.assertNotIn("Spa Manager v4.0", html)

    def test_settings_template_includes_explicit_csrf_tokens_for_post_forms(self):
        template = Path("templates/setting/index.html").read_text(encoding="utf-8")
        self.assertIn('id="createBackupForm"', template)
        self.assertIn('id="editBackupNoteForm"', template)
        self.assertIn('id="uploadBackupForm"', template)
        self.assertIn('action="{{ url_for(\'setting.save_spa_info\') }}" method="POST"', template)
        self.assertGreaterEqual(template.count('name="csrf_token"'), 4)
        self.assertIn('Backup lưu lại trạng thái hiện tại của hệ thống.', template)
        self.assertIn('id="restoreConfirmCheck"', template)
        self.assertIn('id="deleteBackupConfirmCheck"', template)
        self.assertIn('id="wizardRestoreConfirmCheck"', template)
        self.assertIn('id="confirmRestoreBackupBtn" disabled', template)
        self.assertIn('id="confirmDeleteBackupBtn" disabled', template)
        self.assertIn('id="wizard-btn-confirm" disabled', template)
        self.assertIn('btn-restore-backup', template)
        self.assertIn('btn-delete-backup', template)
        self.assertNotIn('href="{{ url_for(\'setting.restore_from_backup\'', template)
        self.assertNotIn('href="{{ url_for(\'setting.delete_backup\'', template)

    def test_settings_backup_restore_ux_copy_and_js_guardrails_are_present(self):
        template = Path("templates/setting/index.html").read_text(encoding="utf-8")
        script = Path("static/js/setting.js").read_text(encoding="utf-8")

        self.assertIn('Bản sao lưu sẽ lưu lại toàn bộ dữ liệu hiện tại của hệ thống', template)
        self.assertIn('Hành động này không thể hoàn tác!', template)
        self.assertIn('Nên tạo một bản sao lưu hiện tại trước khi tiếp tục', template)
        self.assertIn('Tôi hiểu thao tác này sẽ thay thế dữ liệu hiện tại.', template)
        self.assertIn('Tôi hiểu thao tác xóa này là vĩnh viễn.', template)
        self.assertNotRegex(template, r'[A-Z]:\\\\')

        self.assertIn('deleteBackupConfirmCheck', script)
        self.assertIn('confirmRestoreBackupBtn.disabled = !this.checked', script)
        self.assertIn('wizardRestoreConfirmCheck', script)
        self.assertIn('confirmDeleteBackupBtn.disabled = !this.checked', script)
        self.assertIn('wizardBtnConfirm.disabled = !this.checked || isExecutingRestore', script)
        self.assertIn('requestSubmit', script)

    def test_backup_service_metadata_uses_clean_vietnamese_text(self):
        service_source = Path("services/backup_service.py").read_text(encoding="utf-8")
        self.assertIn("Backup ngày", service_source)
        self.assertIn("Backup tạo lúc", service_source)
        self.assertIn("Hôm nay", service_source)
        self.assertIn("Hôm qua", service_source)
        for marker in ["Ã", "á»", "áº", "Æ", "Ä‘", "â€¢", "Â"]:
            self.assertNotIn(marker, service_source)

    def test_new_backup_metadata_and_list_render_clean_vietnamese_text(self):
        owner = self.create_user("settings-backup-vn-owner", password="owner-pass", full_name="Backup VN Owner", role="OWNER")
        self.login_as(owner)
        backup_id, backup_meta, backup_path = self.create_settings_backup_via_route(owner, notes="")
        try:
            self.assertIn("Backup ngày", backup_meta["display_name"])
            self.assertIn("Backup tạo lúc", backup_meta["notes"])

            response = self.client.get("/settings", follow_redirects=False)
            html = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("Backup ngày", html)
            self.assertIn("Hôm nay", html)
            self.assertNotIn("Backup ngÃ", html)
            self.assertNotIn("Backup táº", html)
            self.assertNotIn("Backup lÃºc", html)
        finally:
            if backup_path.exists():
                backup_path.unlink()
            BackupRepository.delete(app, backup_id)

    def test_settings_backup_list_reads_legacy_folder_read_only(self):
        owner = self.create_user("settings-backup-legacy-owner", password="owner-pass", full_name="Legacy Backup Owner", role="OWNER")
        self.login_as(owner)

        legacy_dir = Path(BackupService.get_legacy_backup_dir(app))
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy_metadata_path = Path(BackupRepository.get_legacy_metadata_path(app))
        original_metadata = legacy_metadata_path.read_text(encoding="utf-8") if legacy_metadata_path.exists() else None

        legacy_backup_id = str(uuid.uuid4())
        legacy_filename = f"SpaManager_Backup_legacy_{uuid.uuid4().hex}.sqlite"
        legacy_file_path = legacy_dir / legacy_filename
        conn = sqlite3.connect(legacy_file_path)
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        legacy_metadata = {
            legacy_backup_id: {
                "id": legacy_backup_id,
                "filename": legacy_filename,
                "display_name": "Backup ngày 04/07/2026 15:24",
                "created_at": datetime.utcnow().isoformat(),
                "size": legacy_file_path.stat().st_size,
                "database_version": "v5.1.0",
                "app_version": "SpaManager v5.1.0",
                "notes": "Legacy backup should stay visible",
                "type": "Manual",
                "created_by": None,
                "status": "Valid",
            }
        }

        try:
            legacy_metadata_path.write_text(
                json.dumps(legacy_metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            response = self.client.get("/settings", follow_redirects=False)
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn("Legacy backup should stay visible", html)
            self.assertIn("Backup ngày 04/07/2026 15:24", html)
            self.assertIn("SpaManager v5.1.0", html)
        finally:
            if legacy_file_path.exists():
                legacy_file_path.unlink()
            if original_metadata is None:
                if legacy_metadata_path.exists():
                    legacy_metadata_path.unlink()
            else:
                legacy_metadata_path.write_text(original_metadata, encoding="utf-8")

    def test_settings_backup_corrupt_metadata_json_does_not_500(self):
        owner = self.create_user("settings-backup-corrupt-owner", password="owner-pass", full_name="Corrupt Backup Owner", role="OWNER")
        self.login_as(owner)
        backup_id, backup_meta, backup_path = self.create_settings_backup_via_route(owner, notes="Corrupt metadata fallback")
        metadata_path = Path(BackupRepository.get_metadata_path(app))
        original_metadata = metadata_path.read_text(encoding="utf-8") if metadata_path.exists() else None

        try:
            metadata_path.write_text("{ this is not valid json", encoding="utf-8")

            response = self.client.get("/settings", follow_redirects=False)
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn("Backup ngày", html)
            self.assertIn("Tự động đồng bộ từ đĩa cứng", html)
            self.assertNotIn("Không thể tải danh sách sao lưu", html)
        finally:
            if backup_path.exists():
                backup_path.unlink()
            if original_metadata is None:
                if metadata_path.exists():
                    metadata_path.unlink()
            else:
                metadata_path.write_text(original_metadata, encoding="utf-8")
            BackupRepository.delete(app, backup_id)

    def test_backup_directory_uses_persistent_root_volume(self):
        backup_dir = Path(BackupService.get_backup_dir(app)).resolve()
        self.assertTrue(str(backup_dir).startswith(str(TEST_MEDIA_ROOT.resolve())))

    def test_settings_backup_list_keeps_backup_versions_visible(self):
        owner = self.create_user("settings-backup-legacy-owner", password="owner-pass", full_name="Backup Legacy Owner", role="OWNER")
        self.login_as(owner)

        first_backup_id, first_backup_meta, first_backup_path = self.create_settings_backup_via_route(
            owner,
            notes="Backup version 5.1 should stay visible",
        )
        second_backup_id, second_backup_meta, second_backup_path = self.create_settings_backup_via_route(
            owner,
            notes="Backup version 5.2 should stay visible",
        )

        first_backup_meta["database_version"] = "v5.1.0"
        first_backup_meta["app_version"] = "SpaManager v5.1.0"
        second_backup_meta["database_version"] = "v5.2.0"
        second_backup_meta["app_version"] = "SpaManager v5.2.0"

        try:
            BackupRepository.save(app, first_backup_id, first_backup_meta)
            BackupRepository.save(app, second_backup_id, second_backup_meta)

            response = self.client.get("/settings", follow_redirects=False)
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn("Backup version 5.1 should stay visible", html)
            self.assertIn("Backup version 5.2 should stay visible", html)
            self.assertIn("SpaManager v5.1.0", html)
            self.assertIn("SpaManager v5.2.0", html)
            self.assertNotIn("/app/database", html)
        finally:
            if first_backup_path.exists():
                first_backup_path.unlink()
            if second_backup_path.exists():
                second_backup_path.unlink()
            BackupRepository.delete(app, first_backup_id)
            BackupRepository.delete(app, second_backup_id)

    def test_settings_backup_list_ignores_corrupted_metadata_entry(self):
        owner = self.create_user("settings-backup-corrupt-owner", password="owner-pass", full_name="Backup Corrupt Owner", role="OWNER")
        self.login_as(owner)
        original_metadata = BackupRepository.load_all(app).copy()
        backup_id, backup_meta, backup_path = self.create_settings_backup_via_route(owner, notes="Healthy backup remains visible")

        corrupted_id = str(uuid.uuid4())
        corrupted_metadata = BackupRepository.load_all(app)
        corrupted_metadata[corrupted_id] = {
            "id": corrupted_id,
            "notes": "Broken metadata entry without filename",
            "status": "Valid",
        }

        try:
            BackupRepository.save_all(app, corrupted_metadata)

            response = self.client.get("/settings", follow_redirects=False)
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn("Healthy backup remains visible", html)
            self.assertNotIn("Không thể tải danh sách sao lưu", html)
        finally:
            if backup_path.exists():
                backup_path.unlink()
            BackupRepository.save_all(app, original_metadata)
            if BackupRepository.get_by_id(app, backup_id):
                BackupRepository.delete(app, backup_id)

    def test_backup_file_path_helper_blocks_traversal_and_stays_inside_backup_dir(self):
        backup_dir = Path(BackupService.get_backup_dir(app)).resolve()
        resolved = Path(BackupService.get_backup_file_path(app, "../../evil.sqlite"))
        self.assertEqual(resolved.parent, backup_dir)
        self.assertEqual(resolved.name, "evil.sqlite")

    def test_settings_backup_upload_error_response_is_generic(self):
        owner = AuthService.seed_owner_if_empty()
        self.login_as(owner)

        temp_db = Path(tempfile.gettempdir()) / f"settings-upload-{uuid.uuid4().hex}.sqlite"
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        try:
            with patch("routes.setting.BackupService.inspect_external_backup", side_effect=RuntimeError("secret-path-leak")):
                with temp_db.open("rb") as file_handle:
                    response = self.post_with_csrf(
                        "/settings/backup/upload",
                        path="/settings",
                        data={
                            "backup_file": (file_handle, temp_db.name),
                            "notes": "Test upload",
                        },
                        content_type="multipart/form-data",
                    )

            self.assertEqual(response.status_code, 500)
            payload = response.get_json()
            self.assertFalse(payload["success"])
            self.assertEqual(payload["message"], "Lỗi khi xử lý tệp tải lên.")
            self.assertNotIn("secret-path-leak", response.get_data(as_text=True))
        finally:
            if temp_db.exists():
                temp_db.unlink()

    def test_settings_staff_is_forbidden_on_sensitive_routes(self):
        owner = self.create_user("settings-owner", password="owner-pass", full_name="Settings Owner", role="OWNER")
        admin = self.create_user("settings-admin", password="admin-pass", full_name="Settings Admin", role="ADMIN")
        staff = self.create_user("settings-staff", password="staff-pass", full_name="Settings Staff", role="STAFF")

        backup_id, backup_meta, backup_path = self.create_settings_backup_via_route(owner, notes="Route access backup")
        import_file = self.create_customer_import_xlsx()
        logo_path = self.create_media_file(Path("uploads") / "logos" / "settings-route-logo.png", b"\x89PNG\r\n\x1a\n")
        logo_relative = "logos/settings-route-logo.png"
        Setting.set("spa_logo", logo_relative)

        staff_token = self.get_csrf_token("/customers")
        routes_to_block = [
            ("GET", "/settings", None, None),
            ("POST", "/settings/backup", {"notes": "x", "backup_type": "Manual", "format": "json"}, "form"),
            ("POST", f"/settings/backup/delete/{backup_id}", None, None),
            ("GET", f"/settings/backup/download/{backup_id}", None, None),
            ("POST", f"/settings/backup/restore/{backup_id}", {"backup_id": backup_id}, "json"),
            ("POST", "/settings/restore", {"restore_file": (logo_path.open("rb"), logo_path.name)}, "multipart"),
            ("GET", f"/settings/restore-wizard/validate/{backup_id}", None, None),
            ("POST", "/settings/restore-wizard/confirm", {"backup_id": backup_id}, "json"),
            ("POST", "/settings/import/analyze", {"import_file": (import_file.open("rb"), import_file.name), "import_type": "customers"}, "multipart"),
            ("POST", "/settings/import/execute", {"temp_file_id": "fake-temp", "import_type": "customers", "duplicate_action": "skip", "all_or_nothing": False}, "json"),
            ("POST", "/settings/delete-logo", None, None),
            ("POST", "/settings/save-spa-info", {
                "spa_name": "Blocked",
                "spa_owner": "Blocked",
                "spa_phone": "0900000000",
                "spa_email": "blocked@example.com",
                "spa_address": "Blocked",
                "spa_open_time": "08:00",
                "spa_close_time": "20:00",
            }, "form"),
        ]

        try:
            self.login_as(staff)
            for method, url, data, payload_type in routes_to_block:
                with self.subTest(route=url):
                    if method == "GET":
                        response = self.client.get(url, follow_redirects=False)
                    elif payload_type == "json":
                        response = self.client.post(url, json=data, headers={"X-CSRFToken": staff_token}, follow_redirects=False)
                    elif payload_type == "multipart":
                        response = self.client.post(
                            url,
                            data=data,
                            headers={"X-CSRFToken": staff_token},
                            content_type="multipart/form-data",
                            follow_redirects=False,
                        )
                        if url.endswith("/restore"):
                            data["restore_file"][0].close()
                        if url.endswith("/analyze"):
                            data["import_file"][0].close()
                    else:
                        response = self.client.post(url, data=data or {}, headers={"X-CSRFToken": staff_token}, follow_redirects=False)

                    self.assertIn(response.status_code, (403, 401), url)

            self.assertTrue(backup_path.exists())
            self.assertEqual(Setting.get("spa_logo"), logo_relative)
        finally:
            if import_file.exists():
                import_file.unlink()
            if logo_path.exists():
                logo_path.unlink()
            if backup_path.exists():
                backup_path.unlink()
            BackupRepository.delete(app, backup_id)

        self.login_as(owner)
        self.assertEqual(self.client.get("/settings", follow_redirects=False).status_code, 200)
        self.login_as(admin)
        self.assertEqual(self.client.get("/settings", follow_redirects=False).status_code, 200)

    def test_settings_backup_create_missing_csrf_has_no_side_effect(self):
        owner = self.create_user("settings-backup-owner", password="owner-pass", full_name="Backup Owner", role="OWNER")
        self.login_as(owner)
        backup_dir = Path(BackupService.get_backup_dir(app))
        before_files = {path.name for path in backup_dir.glob("*.sqlite")}

        response = self.client.post(
            "/settings/backup",
            data={"notes": "No CSRF", "backup_type": "Manual", "format": "json"},
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )

        after_files = {path.name for path in backup_dir.glob("*.sqlite")}
        self.assertEqual(response.status_code, 400)
        self.assertEqual(before_files, after_files)

    def test_settings_backup_delete_missing_csrf_keeps_backup_file(self):
        owner = self.create_user("settings-delete-owner", password="owner-pass", full_name="Delete Owner", role="OWNER")
        backup_id, backup_meta, backup_path = self.create_settings_backup_via_route(owner, notes="Delete CSRF backup")
        before_log_count = ActivityLog.query.count()

        try:
            response = self.client.post(f"/settings/backup/delete/{backup_id}", follow_redirects=False)
            self.assertEqual(response.status_code, 400)
            self.assertTrue(backup_path.exists())
            self.assertIsNotNone(BackupRepository.get_by_id(app, backup_id))
            self.assertEqual(ActivityLog.query.count(), before_log_count)
        finally:
            if backup_path.exists():
                backup_path.unlink()
            BackupRepository.delete(app, backup_id)

    def test_settings_restore_confirm_missing_csrf_keeps_database_unchanged(self):
        owner = self.create_user("settings-restore-owner", password="owner-pass", full_name="Restore Owner", role="OWNER")
        self.login_as(owner)
        customer_before = self.create_customer_record("Before Restore")
        backup_id, backup_meta, backup_path = self.create_settings_backup_via_route(owner, notes="Restore CSRF backup")
        customer_after = self.create_customer_record("After Backup")

        try:
            response = self.client.post(
                "/settings/restore-wizard/confirm",
                json={"backup_id": backup_id},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 400)
            self.assertIsNotNone(Customer.query.get(customer_before.id))
            self.assertIsNotNone(Customer.query.get(customer_after.id))
            self.assertEqual(Customer.query.count(), 2)
        finally:
            if backup_path.exists():
                backup_path.unlink()
            BackupRepository.delete(app, backup_id)

    def test_settings_import_execute_missing_csrf_keeps_database_unchanged(self):
        owner = self.create_user("settings-import-owner", password="owner-pass", full_name="Import Owner", role="OWNER")
        self.login_as(owner)
        before_count = Customer.query.count()
        import_file = self.create_customer_import_xlsx()

        try:
            analyze_response = self.post_with_csrf(
                "/settings/import/analyze",
                path="/settings",
                data={
                    "import_file": (import_file.open("rb"), import_file.name),
                    "import_type": "customers",
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(analyze_response.status_code, 200)
            temp_file_id = analyze_response.get_json()["temp_file_id"]

            execute_response = self.client.post(
                "/settings/import/execute",
                json={
                    "temp_file_id": temp_file_id,
                    "import_type": "customers",
                    "duplicate_action": "skip",
                    "all_or_nothing": False,
                },
                follow_redirects=False,
            )
            self.assertEqual(execute_response.status_code, 400)
            self.assertEqual(Customer.query.count(), before_count)
        finally:
            if import_file.exists():
                import_file.unlink()
            temp_path = Path(ImportService.get_upload_dir(app)) / temp_file_id if 'temp_file_id' in locals() else None
            if temp_path and temp_path.exists():
                temp_path.unlink()

    def test_settings_logo_upload_and_delete_require_csrf(self):
        owner = self.create_user("settings-logo-owner", password="owner-pass", full_name="Logo Owner", role="OWNER")
        self.login_as(owner)
        logo_before = Setting.get("spa_logo")
        before_files = {path.name for path in (TEST_MEDIA_ROOT / "uploads" / "logos").glob("*") if path.is_file()}

        logo_upload = BytesIO(b"\x89PNG\r\n\x1a\n")
        logo_upload.name = "logo-no-csrf.png"
        upload_response = self.client.post(
            "/settings/save-spa-info",
            data={
                "spa_name": "Spa Test",
                "spa_owner": "Owner",
                "spa_phone": "0901234567",
                "spa_email": "owner@example.com",
                "spa_address": "Address",
                "spa_open_time": "08:00",
                "spa_close_time": "20:00",
                "spa_logo": (logo_upload, logo_upload.name),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        after_upload_files = {path.name for path in (TEST_MEDIA_ROOT / "uploads" / "logos").glob("*") if path.is_file()}
        self.assertEqual(upload_response.status_code, 400)
        self.assertEqual(logo_before, Setting.get("spa_logo"))
        self.assertEqual(before_files, after_upload_files)

        created_logo = self.create_media_file(Path("uploads") / "logos" / "delete-logo-no-csrf.png", b"\x89PNG\r\n\x1a\n")
        Setting.set("spa_logo", "logos/delete-logo-no-csrf.png")

        delete_response = self.client.post("/settings/delete-logo", follow_redirects=False)
        self.assertEqual(delete_response.status_code, 400)
        self.assertTrue(created_logo.exists())
        self.assertEqual(Setting.get("spa_logo"), "logos/delete-logo-no-csrf.png")

        if created_logo.exists():
            created_logo.unlink()
        Setting.set("spa_logo", logo_before or "")

    def test_settings_path_traversal_routes_reject_outside_paths(self):
        owner = self.create_user("settings-traversal-owner", password="owner-pass", full_name="Traversal Owner", role="OWNER")
        backup_id, backup_meta, backup_path = self.create_settings_backup_via_route(owner, notes="Traversal backup")
        self.login_as(owner)

        try:
            traversal_paths = [
                f"/settings/backup/download/..%2F{backup_id}",
                f"/settings/backup/delete/..%2F{backup_id}",
                f"/settings/backup/restore/..%2F{backup_id}",
            ]
            for url in traversal_paths:
                response = self.client.open(url, method="GET" if "download" in url else "POST", follow_redirects=False)
                self.assertIn(response.status_code, (400, 404), url)
                self.assertNotIn(str(TEST_MEDIA_ROOT).replace("\\", "/"), response.get_data(as_text=True))
            self.assertTrue(backup_path.exists())
        finally:
            if backup_path.exists():
                backup_path.unlink()
            BackupRepository.delete(app, backup_id)

    def test_settings_restore_validate_is_read_only_and_invalid_restore_file_is_blocked(self):
        owner = self.create_user("settings-validate-owner", password="owner-pass", full_name="Validate Owner", role="OWNER")
        backup_id, backup_meta, backup_path = self.create_settings_backup_via_route(owner, notes="Validate backup")
        before_customer_count = Customer.query.count()

        invalid_restore = Path(tempfile.gettempdir()) / f"invalid-restore-{uuid.uuid4().hex}.sqlite"
        invalid_restore.write_text("not a sqlite database", encoding="utf-8")

        try:
            self.login_as(owner)
            validate_response = self.client.get(f"/settings/restore-wizard/validate/{backup_id}", follow_redirects=False)
            self.assertEqual(validate_response.status_code, 200)
            self.assertEqual(Customer.query.count(), before_customer_count)

            with invalid_restore.open("rb") as file_handle:
                restore_response = self.post_with_csrf(
                    "/settings/restore",
                    path="/settings",
                    data={"restore_file": (file_handle, invalid_restore.name)},
                    content_type="multipart/form-data",
                )
            self.assertEqual(restore_response.status_code, 302)
            self.assertEqual(Customer.query.count(), before_customer_count)
        finally:
            if invalid_restore.exists():
                invalid_restore.unlink()
            if backup_path.exists():
                backup_path.unlink()
            BackupRepository.delete(app, backup_id)

    def test_settings_backup_logs_are_attributed_and_sanitized(self):
        owner = self.create_user("settings-log-owner", password="owner-pass", full_name="Log Owner", role="OWNER")
        self.login_as(owner)
        before_log_count = ActivityLog.query.count()
        backup_id, backup_meta, backup_path = self.create_settings_backup_via_route(owner, notes="Log backup")
        created_log = ActivityLog.query.order_by(ActivityLog.id.desc()).first()
        self.assertGreater(ActivityLog.query.count(), before_log_count)
        self.assertIsNotNone(created_log)
        self.assertEqual(created_log.user_id, owner.id)
        self.assertNotIn("password", created_log.description.lower())
        self.assertNotIn("token", created_log.description.lower())
        self.assertNotIn("database_url", created_log.description.lower())
        self.assertNotIn(str(TEST_MEDIA_ROOT).lower(), created_log.description.lower())

        delete_response = self.post_with_csrf(f"/settings/backup/delete/{backup_id}", path="/settings")
        self.assertEqual(delete_response.status_code, 200)
        delete_log = ActivityLog.query.order_by(ActivityLog.id.desc()).first()
        self.assertIsNotNone(delete_log)
        self.assertEqual(delete_log.user_id, owner.id)
        self.assertNotIn("password", delete_log.description.lower())
        self.assertNotIn("token", delete_log.description.lower())
        self.assertNotIn("database_url", delete_log.description.lower())
        self.assertNotIn(str(TEST_MEDIA_ROOT).lower(), delete_log.description.lower())

        if backup_path.exists():
            backup_path.unlink()
        BackupRepository.delete(app, backup_id)

    def test_sidebar_template_contains_clean_vietnamese_text(self):
        sidebar = Path("templates/layout/sidebar.html").read_text(encoding="utf-8")
        self.assertIn("TIỆM NHÀ NHÍM", sidebar)
        self.assertIn("Trang chủ", sidebar)
        self.assertIn("Người dùng", sidebar)
        for marker in ["Ã", "á»", "áº", "Æ", "Ä‘", "â€¢", "Â"]:
            self.assertNotIn(marker, sidebar)

    def test_activity_log_action_badge_is_scoped_and_truncated(self):
        template = Path("templates/activity_log/index.html").read_text(encoding="utf-8")
        css = Path("static/css/pages/activity-log.css").read_text(encoding="utf-8")

        self.assertIn("activity-action-badge", template)
        self.assertIn("name=\"actor\"", template)
        self.assertIn("col-actor", template)
        self.assertIn(".activity-log-page .activity-action-badge", css)
        self.assertIn("text-overflow: ellipsis", css)
        self.assertIn("overflow: hidden", css)
        self.assertIn(".activity-log-page .activity-log-table .col-action", css)
        self.assertIn(".activity-log-page .activity-log-table .col-severity", css)
        self.assertIn(".activity-log-page .activity-log-table .col-actor", css)

    def test_db_stamp_head_marks_existing_schema_without_rebuilding(self):
        tables_before = sorted(sa_inspect(db.engine).get_table_names())
        runner = app.test_cli_runner()

        result = runner.invoke(args=["db", "stamp", "head"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Stamped 0001_baseline", result.output)

        tables_after = sorted(sa_inspect(db.engine).get_table_names())
        self.assertIn("alembic_version", tables_after)
        self.assertEqual(tables_before, [table for table in tables_after if table != "alembic_version"])

        current_after = runner.invoke(args=["db", "current"])
        self.assertEqual(current_after.exit_code, 0, current_after.output)
        self.assertIn("0001_baseline", current_after.output)


if __name__ == "__main__":
    unittest.main()
