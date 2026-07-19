import os
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook

# Configure environment variables at the very top before importing app
TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_import_fixes_test.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_media_import_fixes_test"

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

# Now it is safe to import app and db
from app import app
from extensions import db
from models.customer import Customer
from models.service import Service
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.import_service import ImportService
from services.backup_service import BackupService

class TestImportExecutionFixes(unittest.TestCase):
    def setUp(self):
        # Configure app context paths
        app.config["PERSISTENT_ROOT"] = TEST_MEDIA_ROOT.as_posix()
        app.config["BACKUP_FOLDER"] = (TEST_MEDIA_ROOT / "backup").as_posix()
        app.config["UPLOAD_ROOT"] = (TEST_MEDIA_ROOT / "uploads").as_posix()
        app.config["LOGO_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "logos").as_posix()
        app.config["AVATAR_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "avatars").as_posix()

        self.app_context = app.app_context()
        self.app_context.push()

        # Clean database tables to prevent test pollution on reused sqlite file
        db.session.remove()
        db.drop_all()
        db.create_all()

        self.client = app.test_client()

    def tearDown(self):
        try:
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        finally:
            self.app_context.pop()
            if TEST_DB_FILE.exists():
                try:
                    TEST_DB_FILE.unlink()
                except Exception:
                    pass
            if TEST_MEDIA_ROOT.exists():
                shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def create_user(self, username, password="secret123", full_name="Test User", role="STAFF", is_active=True, approval_status="active"):
        user = User(
            username=username,
            full_name=full_name,
            role=role,
            is_active=is_active,
            approval_status=approval_status,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    def grant_active_workspace_access(self, user, role=None, slug=None):
        workspace = Workspace(
            name=f"Fixture Workspace {user.username}",
            slug=slug or f"fixture-{user.username}",
            status="active",
        )
        db.session.add(workspace)
        db.session.flush()
        member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role=(role or user.role).lower(),
            status="active",
        )
        db.session.add(member)
        db.session.commit()

    def login_as(self, user):
        from core.auth.constants import AUTH_SESSION_KEY
        with self.client.session_transaction() as sess:
            sess[AUTH_SESSION_KEY] = user.id

    def create_customer_import_xlsx_unique(self, valid_count, invalid_count):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Khách hàng"
        sheet.append(list(ImportService.CUSTOMER_COLUMNS))

        # Add valid rows with unique phones and emails
        for i in range(1, valid_count + 1):
            sheet.append([
                f"Valid Customer {i}",
                f"0901{i:06d}",
                f"valid_{i}@example.com",
                f"Street {i}"
            ])

        # Add invalid rows
        for i in range(1, invalid_count + 1):
            sheet.append([
                f"Invalid Customer {i}",
                f"0902{i:06d}",
                f"invalid_email_{i}_no_at",
                f"Street {i}"
            ])

        temp_path = Path(tempfile.gettempdir()) / f"test-import-cust-unique.xlsx"
        workbook.save(temp_path)
        workbook.close()
        return temp_path

    def create_service_import_xlsx_unique(self, count):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Dịch vụ"
        sheet.append(list(ImportService.SERVICE_COLUMNS))

        for i in range(1, count + 1):
            sheet.append([
                f"Service {i}",
                100000 + i * 1000,
                30 + i,
                f"Description {i}",
                "Massage"
            ])

        temp_path = Path(tempfile.gettempdir()) / f"test-import-serv-unique.xlsx"
        workbook.save(temp_path)
        workbook.close()
        return temp_path

    @patch('services.backup_service.BackupService.is_sqlite_database')
    @patch('services.backup_service.BackupService.create_backup')
    def test_postgresql_import_does_not_call_sqlite_backup(self, mock_create_backup, mock_is_sqlite):
        # 1. Mock database type to be PostgreSQL (not SQLite)
        mock_is_sqlite.return_value = False

        owner = self.create_user("import-pg-owner", password="owner-pass", role="OWNER")
        self.grant_active_workspace_access(owner, role="OWNER")
        self.login_as(owner)

        import_file = self.create_service_import_xlsx_unique(5)

        try:
            with app.test_request_context("/settings"):
                report = ImportService.execute_import(app, str(import_file), "services", "skip", False)
            # Verify backup was NOT called
            mock_create_backup.assert_not_called()
        finally:
            if import_file.exists():
                import_file.unlink()

    @patch('services.backup_service.BackupService.is_sqlite_database')
    @patch('services.backup_service.BackupService.create_backup')
    def test_sqlite_import_calls_backup(self, mock_create_backup, mock_is_sqlite):
        # 1. Mock database type to be SQLite
        mock_is_sqlite.return_value = True

        owner = self.create_user("import-sqlite-owner", password="owner-pass", role="OWNER")
        self.grant_active_workspace_access(owner, role="OWNER")
        self.login_as(owner)

        import_file = self.create_service_import_xlsx_unique(5)

        try:
            with app.test_request_context("/settings"):
                report = ImportService.execute_import(app, str(import_file), "services", "skip", False)
            # Verify backup was called
            mock_create_backup.assert_called_once()
        finally:
            if import_file.exists():
                import_file.unlink()

    def test_service_import_20_valid_rows_inserts_20_rows(self):
        owner = self.create_user("import-serv-20-owner", password="owner-pass", role="OWNER")
        self.grant_active_workspace_access(owner, role="OWNER")
        self.login_as(owner)

        before_count = Service.query.count()
        import_file = self.create_service_import_xlsx_unique(20)

        try:
            with app.test_request_context("/settings"):
                report = ImportService.execute_import(app, str(import_file), "services", "skip", False)
            self.assertEqual(report["success"], 20)
            self.assertEqual(report["failed"], 0)
            self.assertEqual(Service.query.count(), before_count + 20)
        finally:
            if import_file.exists():
                import_file.unlink()

    def test_customer_import_all_or_nothing_inserts_zero_on_any_error(self):
        owner = self.create_user("import-cust-aon-owner", password="owner-pass", role="OWNER")
        self.grant_active_workspace_access(owner, role="OWNER")
        self.login_as(owner)

        before_count = Customer.query.count()
        # 39 valid, 11 invalid
        import_file = self.create_customer_import_xlsx_unique(39, 11)

        try:
            with app.test_request_context("/settings"):
                report = ImportService.execute_import(app, str(import_file), "customers", "skip", True)
            self.assertEqual(report["success"], 0)
            self.assertEqual(report["failed"], 50)
            self.assertEqual(Customer.query.count(), before_count)
        finally:
            if import_file.exists():
                import_file.unlink()

    def test_customer_import_partial_mode_inserts_valid_rows(self):
        owner = self.create_user("import-cust-part-owner", password="owner-pass", role="OWNER")
        self.grant_active_workspace_access(owner, role="OWNER")
        self.login_as(owner)

        before_count = Customer.query.count()
        # 39 valid, 11 invalid
        import_file = self.create_customer_import_xlsx_unique(39, 11)

        try:
            with app.test_request_context("/settings"):
                report = ImportService.execute_import(app, str(import_file), "customers", "skip", False)
            self.assertEqual(report["success"], 39)
            self.assertEqual(report["failed"], 11)
            self.assertEqual(Customer.query.count(), before_count + 39)
        finally:
            if import_file.exists():
                import_file.unlink()
