import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from openpyxl import Workbook

from tests.test_basic import BasicTestCase
from app import app
from extensions import db
from models.customer import Customer
from models.service import Service
from services.import_service import ImportService
from services.backup_service import BackupService

class TestImportExecutionFixes(BasicTestCase):
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
