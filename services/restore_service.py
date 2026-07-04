import os
import sqlite3

from extensions import db
from core.logger import app_logger
from repositories.backup_repository import BackupRepository
from services.activity_log_service import ActivityLogService
from services.system_refresh_service import SystemRefreshService



class RestoreService:
    """Service for restoring the SQLite database from a backup file."""

    @staticmethod
    def get_db_path(app):
        """Get the absolute path to the SQLite database file from configuration."""
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if db_uri.startswith('sqlite:///'):
            return db_uri.replace('sqlite:///', '')
        return os.path.join(app.root_path, 'database', 'spa.db')

    @staticmethod
    def get_upload_dir(app):
        """Get the upload directory for restore files."""
        upload_dir = os.path.join(app.root_path, 'static', 'uploads', 'import')
        os.makedirs(upload_dir, exist_ok=True)
        return upload_dir

    @staticmethod
    def validate_backup_file(filepath):
        """
        Validate that the uploaded file is a valid SQLite database.
        Returns (is_valid, error_message).
        """
        if not os.path.exists(filepath):
            return False, 'File không tồn tại.'

        # Check file size (must not be empty)
        if os.path.getsize(filepath) == 0:
            return False, 'File backup rỗng.'

        # Check SQLite header magic bytes
        try:
            with open(filepath, 'rb') as f:
                header = f.read(16)
                if not header.startswith(b'SQLite format 3'):
                    return False, 'File không phải định dạng SQLite hợp lệ.'
        except Exception:
            return False, 'Không thể đọc file backup.'

        # Try opening as SQLite database
        try:
            conn = sqlite3.connect(filepath)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()

            # Check that essential tables exist
            required_tables = ['customers', 'services']
            missing = [t for t in required_tables if t not in tables]
            if missing:
                return False, f'File backup thiếu bảng dữ liệu: {", ".join(missing)}'

            return True, None
        except Exception as e:
            return False, f'File backup không hợp lệ: {str(e)}'

    @staticmethod
    def restore_database(app, backup_filepath):
        """
        Restore database from backup file.
        Returns (success, message).
        """
        db_path = RestoreService.get_db_path(app)
        backup_filename = os.path.basename(backup_filepath)

        # Validate backup file first
        is_valid, error = RestoreService.validate_backup_file(backup_filepath)
        if not is_valid:
            app_logger.warning(f"Database restore validation failed: {error}", module="RESTORE")
            return False, error

        try:
            # Close all database connections by disposing the engine
            db.session.remove()
            db.engine.dispose()

            # Safely copy data using SQLite Online Backup API to avoid file-locking on Windows
            src = sqlite3.connect(backup_filepath)
            dst = sqlite3.connect(db_path)
            with dst:
                src.backup(dst)
            dst.close()
            src.close()

            # 1. Application Log
            app_logger.info(f"Database restored successfully from backup file: {backup_filename}", module="RESTORE")

            # 2. Security Log (check if source was Imported)
            is_imported = False
            try:
                all_backups = BackupRepository.load_all(app)
                for bid, meta in all_backups.items():
                    if meta.get('filename') == backup_filename:
                        if meta.get('source') == 'Imported':
                            is_imported = True
                        break
            except Exception:
                pass
                
            if is_imported:
                app_logger.security(f"RESTORE_IMPORTED_BACKUP: restored imported database from backup: {backup_filename}", module="RESTORE")
            else:
                app_logger.security(f"System database restored from backup: {backup_filename}", module="RESTORE")

            # 3. Activity Log (Database)
            ActivityLogService.log_action(
                module=ActivityLogService.MODULE_SETTINGS,
                action='RESTORE_BACKUP',
                description=f'Khôi phục dữ liệu thành công từ file: {backup_filename}',
                severity=ActivityLogService.SEVERITY_SUCCESS
            )

            # Refresh system caches and db session state after database overwrite
            SystemRefreshService.after_restore()

            return True, 'Khôi phục dữ liệu thành công!'
        except Exception as e:
            app_logger.error("Failed to restore database", module="RESTORE", exc_info=True)
            
            # Log failure to activity log
            try:
                ActivityLogService.log_action(
                    module=ActivityLogService.MODULE_SETTINGS,
                    action='ERROR',
                    description=f'Khôi phục dữ liệu thất bại từ file {backup_filename}: {str(e)}',
                    severity=ActivityLogService.SEVERITY_CRITICAL
                )
            except Exception:
                pass
                
            return False, 'Lỗi khi khôi phục dữ liệu.'
