import os
import uuid
import shutil
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

from werkzeug.utils import secure_filename

from core.logger import app_logger
from repositories.backup_repository import BackupRepository
from models.setting import Setting
from validators.backup_validator import BackupValidator
from services.activity_log_service import ActivityLogService
from utils.timezone_utils import get_app_timezone, local_now, to_local_datetime



class BackupService:
    """Service for backing up the SQLite database and managing its metadata."""
    APP_VERSION = "5.4.0"

    @staticmethod
    def get_app_version(app):
        """Get the application version used for backup metadata."""
        return app.config.get('APP_VERSION', BackupService.APP_VERSION)

    @staticmethod
    def get_db_path(app):
        """Get the absolute path to the SQLite database file from configuration."""
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if db_uri.startswith('sqlite:///'):
            return db_uri.replace('sqlite:///', '')
        return os.path.join(app.root_path, 'database', 'spa.db')

    @staticmethod
    def get_backup_dir(app):
        """Get the backup directory path, creating it if needed."""
        backup_dir = app.config.get('BACKUP_FOLDER') or os.path.join(app.root_path, 'backup')
        os.makedirs(backup_dir, exist_ok=True)
        return backup_dir

    @staticmethod
    def get_legacy_backup_dir(app):
        """Get the historical backup directory path used before the persistent volume move."""
        legacy_backup_dir = os.path.join(app.root_path, 'backup')
        primary_backup_dir = BackupService.get_backup_dir(app)
        if os.path.abspath(legacy_backup_dir) == os.path.abspath(primary_backup_dir):
            return None
        return legacy_backup_dir

    @staticmethod
    def get_backup_dirs(app):
        """Return backup directories in read-only compatibility order."""
        backup_dirs = [BackupService.get_backup_dir(app)]
        legacy_backup_dir = BackupService.get_legacy_backup_dir(app)
        if legacy_backup_dir:
            backup_dirs.append(legacy_backup_dir)
        return backup_dirs

    @staticmethod
    def sanitize_filename_component(value, default='v1.0'):
        """Sanitize a value before using it inside a filename."""
        cleaned = secure_filename(str(value or '')).strip('._')
        return cleaned or default

    @staticmethod
    def get_backup_file_path(app, filename):
        """Resolve a backup file path safely within the backup directory."""
        candidate_name = os.path.basename(str(filename or ''))
        if not candidate_name:
            return None

        for backup_dir in BackupService.get_backup_dirs(app):
            resolved_dir = Path(backup_dir).resolve()
            candidate = (resolved_dir / candidate_name).resolve()
            try:
                candidate.relative_to(resolved_dir)
            except ValueError:
                continue
            if candidate.exists():
                return str(candidate)
        primary_dir = Path(BackupService.get_backup_dir(app)).resolve()
        fallback_candidate = (primary_dir / candidate_name).resolve()
        try:
            fallback_candidate.relative_to(primary_dir)
        except ValueError:
            return None
        return str(fallback_candidate)

    @staticmethod
    def create_backup(app, notes=None, backup_type='Manual', created_by=None):
        """
        Create a backup of the SQLite database.
        Returns (backup_id, backup_filename, backup_filepath) on success, or (None, None, None) on failure.

        NOTE: This feature is SQLite-only. When PostgreSQL or another database is configured,
        this method returns None immediately. Use pg_dump for PostgreSQL backups.
        """
        # Guard: Backup Center only supports SQLite
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if not db_uri.startswith('sqlite:///'):
            app_logger.warning(
                "Backup Center is disabled: only supported on SQLite databases. "
                "Use pg_dump for PostgreSQL backups.",
                module="BACKUP"
            )
            return None, None, None

        # 1. Validation
        data = {'notes': notes}
        validator = BackupValidator()
        validator.validate(data)
        validator.raise_if_invalid("Thông tin sao lưu không hợp lệ.")

        db_path = BackupService.get_db_path(app)
        if not os.path.exists(db_path):
            return None, None, None

        backup_dir = BackupService.get_backup_dir(app)
        timestamp = local_now().strftime('%Y-%m-%d_%H-%M-%S')
        app_version = BackupService.get_app_version(app)
        backup_filename = f"SpaManager_Backup_{timestamp}_v{app_version}.sqlite"
        backup_filepath = os.path.join(backup_dir, backup_filename)

        try:
            shutil.copy2(db_path, backup_filepath)
            
            # Retrieve DB version from setting
            db_version = Setting.get('db_version', 'v1.0')
            
            # Generate UUID and metadata
            backup_id = str(uuid.uuid4())
            created_at = local_now()
            
            # Default note if blank
            if not notes or not notes.strip():
                notes = f"Backup tạo lúc {created_at.strftime('%H:%M %d/%m/%Y')}"
            else:
                notes = notes.strip()
                
            size = os.path.getsize(backup_filepath)
            
            metadata = {
                'id': backup_id,
                'filename': backup_filename,
                'display_name': f"Backup ngày {created_at.strftime('%d/%m/%Y %H:%M')}",
                'created_at': created_at.isoformat(),
                'size': size,
                'database_version': db_version,
                'app_version': f"SpaManager v{app_version}",
                'notes': notes,
                'type': backup_type,
                'created_by': created_by,
                'status': 'Valid'
            }
            
            # Save using BackupRepository
            BackupRepository.save(app, backup_id, metadata)
            
            app_logger.info(f"Database backup created successfully: {metadata['display_name']} (Size: {size} bytes)", module="BACKUP")

            ActivityLogService.log_action(
                module=ActivityLogService.MODULE_SETTINGS,
                action='BACKUP',
                description=f'Tạo bản sao lưu: {metadata["display_name"]}',
                reference_id=None,
                severity=ActivityLogService.SEVERITY_SUCCESS
            )

            return backup_id, backup_filename, backup_filepath
        except Exception as e:
            app_logger.error(f"Failed to create database backup: {str(e)}", module="BACKUP", exc_info=True)
            return None, None, None

    @staticmethod
    def sync_backups(app):
        """
        Synchronize backup directory files with metadata.json.
        Performs integrity checks and registers new files automatically.
        """
        backup_dirs = BackupService.get_backup_dirs(app)
        metadata = BackupRepository.load_all(app)
        
        # 1. Get all backup files currently on disk
        disk_files = {}
        for backup_dir in backup_dirs:
            if not backup_dir or not os.path.isdir(backup_dir):
                continue
            for filename in os.listdir(backup_dir):
                if filename == 'metadata.json' or not (filename.endswith('.sqlite') or filename.endswith('.db')):
                    continue
                filepath = os.path.join(backup_dir, filename)
                if os.path.isfile(filepath):
                    disk_files.setdefault(filename, filepath)
                
        # 2. Track filenames registered in metadata
        registered_files = {}
        for bid, meta in list(metadata.items()):
            if not isinstance(meta, dict):
                continue
            filename = meta.get('filename')
            if filename:
                registered_files[filename] = bid
            
        changes_detected = False
        
        # 3. Handle files on disk that have no metadata -> Register them
        for filename, filepath in disk_files.items():
            if filename not in registered_files:
                # Generate new metadata entry for this file
                bid = str(uuid.uuid4())
                mtime = os.path.getmtime(filepath)
                dt_created = datetime.fromtimestamp(mtime, tz=get_app_timezone())
                size = os.path.getsize(filepath)
                
                # Check status
                status = BackupService.check_file_integrity(filepath)
                
                metadata[bid] = {
                    'id': bid,
                    'filename': filename,
                    'display_name': f"Backup ngày {dt_created.strftime('%d/%m/%Y %H:%M')}",
                    'created_at': dt_created.isoformat(),
                    'size': size,
                    'database_version': 'v1.0',
                    'app_version': f"SpaManager v{BackupService.get_app_version(app)}",
                    'notes': 'Tự động đồng bộ từ đĩa cứng',
                    'type': 'Manual',
                    'created_by': None,
                    'status': status
                }
                changes_detected = True
                
        # 4. Handle registered metadata entries
        for bid, meta in list(metadata.items()):
            if not isinstance(meta, dict):
                continue
            filename = meta.get('filename')
            if not filename:
                continue
            filepath = BackupService.get_backup_file_path(app, filename)
            
            current_status = meta.get('status', 'Valid')
            new_status = current_status
            
            if not filepath or filename not in disk_files:
                # File is missing
                if current_status != 'File Missing':
                    new_status = 'File Missing'
                    changes_detected = True
            else:
                # File exists on disk, check integrity
                tested_status = BackupService.check_file_integrity(filepath)
                if current_status != tested_status:
                    new_status = tested_status
                    changes_detected = True
                    
            if new_status != current_status:
                metadata[bid]['status'] = new_status
                
        # 5. Save metadata if changes were made
        if changes_detected:
            BackupRepository.save_all(app, metadata)
            ActivityLogService.log_action(
                module=ActivityLogService.MODULE_SETTINGS,
                action='SYNC',
                description='Tự động đồng bộ và quét lỗi danh sách sao lưu',
                severity=ActivityLogService.SEVERITY_SUCCESS
            )
            
        # 6. Format and return list of backups for UI rendering
        formatted_list = []
        for bid, meta in metadata.items():
            if not isinstance(meta, dict):
                continue
            filename = meta.get('filename')
            if not filename:
                continue
            created_at_value = meta.get('created_at')
            dt = None
            if created_at_value:
                try:
                    dt = to_local_datetime(created_at_value, assume_utc=True)
                except Exception:
                    dt = None
            filepath = BackupService.get_backup_file_path(app, filename)
            if not dt and filepath and os.path.exists(filepath):
                dt = datetime.fromtimestamp(os.path.getmtime(filepath), tz=get_app_timezone())
            if not dt:
                dt = local_now()
            size_value = meta.get('size')
            if size_value is None and filepath and os.path.exists(filepath):
                size_value = os.path.getsize(filepath)
            formatted_list.append({
                'id': bid,
                'filename': filename,
                'display_name': meta.get('display_name') or f"Backup ngày {dt.strftime('%d/%m/%Y %H:%M')}",
                'created_at': dt,
                'created_at_timestamp': dt.timestamp() if dt else 0,
                'created_at_friendly': BackupService.format_friendly_time(dt) if dt else 'N/A',
                'size': size_value or 0,
                'size_friendly': BackupService.format_size(size_value or 0),
                'version_db': meta.get('database_version', 'v1.0'),
                'version_app': meta.get('app_version', 'SpaManager v1.0'),
                'notes': meta.get('notes', '-'),
                'type': meta.get('type', 'Manual'),
                'status': meta.get('status', 'Valid'),
                'created_by': meta.get('created_by'),
                'source': meta.get('source', 'Local')
            })
            
        return formatted_list

    @staticmethod
    def check_file_integrity(filepath):
        """Perform database integrity validation checks."""
        if not os.path.exists(filepath):
            return 'File Missing'
        if os.path.getsize(filepath) == 0:
            return 'Invalid'
        
        # Verify SQLite integrity
        conn = None
        try:
            conn = sqlite3.connect(filepath)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            result = cursor.fetchone()
            if result and result[0] == "ok":
                return 'Valid'
            else:
                return 'Invalid'
        except Exception:
            return 'Invalid'
        finally:
            if conn:
                conn.close()

    @staticmethod
    def delete_backup(app, backup_id):
        """Permanently delete backup file from disk and metadata."""
        meta = BackupRepository.get_by_id(app, backup_id)
        if not meta:
            return False
            
        filepath = BackupService.get_backup_file_path(app, meta.get('filename'))
        
        # Delete file from disk if exists
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
                
        # Delete metadata
        BackupRepository.delete(app, backup_id)
        
        ActivityLogService.log_action(
            module=ActivityLogService.MODULE_SETTINGS,
            action='DELETE',
            description=f'Xóa vĩnh viễn bản sao lưu: {meta["display_name"]}',
            severity=ActivityLogService.SEVERITY_WARNING
        )
        return True

    @staticmethod
    def update_notes(app, backup_id, new_notes):
        """Update notes metadata field of a backup."""
        meta = BackupRepository.get_by_id(app, backup_id)
        if not meta:
            return False
            
        meta['notes'] = new_notes.strip() if new_notes else '-'
        BackupRepository.save(app, backup_id, meta)
        
        ActivityLogService.log_action(
            module=ActivityLogService.MODULE_SETTINGS,
            action='UPDATE',
            description=f'Cập nhật ghi chú bản sao lưu: {meta["display_name"]}',
            severity=ActivityLogService.SEVERITY_SUCCESS
        )
        return True

    @staticmethod
    def format_size(size_in_bytes):
        if size_in_bytes >= 1024 * 1024 * 1024:
            return f"{size_in_bytes / (1024 * 1024 * 1024):.1f} GB"
        elif size_in_bytes >= 1024 * 1024:
            return f"{size_in_bytes / (1024 * 1024):.1f} MB"
        elif size_in_bytes >= 1024:
            return f"{size_in_bytes / 1024:.1f} KB"
        else:
            return f"{size_in_bytes} Bytes"

    @staticmethod
    def format_friendly_time(dt):
        now = local_now()
        if dt.date() == now.date():
            return f"Hôm nay {dt.strftime('%H:%M')}"
        elif dt.date() == (now - timedelta(days=1)).date():
            return f"Hôm qua {dt.strftime('%H:%M')}"
        else:
            return dt.strftime('%d/%m/%Y %H:%M')
    
    @staticmethod
    def validate_backup(app, backup_id):
        """Validate a backup for restore wizard.
        Returns a dict with keys: exists (bool), integrity (str), compatible (bool), metadata (dict|None).
        """
        meta = BackupRepository.get_by_id(app, backup_id)
        if not meta:
            return {'exists': False, 'integrity': 'File Missing', 'compatible': False, 'metadata': None}
        filepath = BackupService.get_backup_file_path(app, meta.get('filename'))
        if not filepath or not os.path.exists(filepath):
            return {'exists': True, 'integrity': 'File Missing', 'compatible': False, 'metadata': meta}
        integrity = BackupService.check_file_integrity(filepath)
        # Check version compatibility â€“ compare backup DB version with current DB version setting
        current_db_version = Setting.get('db_version', 'v1.0')
        backup_db_version = meta.get('database_version', 'v1.0')
        compatible = (backup_db_version == current_db_version)
        return {'exists': True, 'integrity': integrity, 'compatible': compatible, 'metadata': meta}

    @staticmethod
    def calculate_sha256(filepath):
        """Calculate the SHA256 checksum of a file."""
        sha256 = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception:
            return None

    @staticmethod
    def inspect_external_backup(filepath):
        """
        Validate and extract metadata from an external SQLite backup file.
        Returns (is_valid, metadata_dict_or_error_msg).
        """
        # 1. Check integrity check
        tested = BackupService.check_file_integrity(filepath)
        if tested != 'Valid':
            return False, "Cơ sở dữ liệu SQLite bị lỗi hoặc không thể đọc."

        # 2. Check schema (required tables of SpaManager)
        conn = None
        try:
            conn = sqlite3.connect(filepath)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}
            required_tables = {'users', 'customers', 'services', 'appointments', 'invoices', 'activity_logs', 'settings'}
            if not required_tables.issubset(tables):
                return False, "Tệp tin không chứa cấu trúc bảng hợp lệ của SpaManager."
                
            # 3. Read metadata from settings table
            db_version = 'v1.0'
            app_version = 'SpaManager v1.0'
            
            cursor.execute("SELECT value FROM settings WHERE key='db_version' LIMIT 1")
            row = cursor.fetchone()
            if row:
                db_version = row[0]
                
            cursor.execute("SELECT value FROM settings WHERE key='software_version' LIMIT 1")
            row = cursor.fetchone()
            if row:
                app_version = row[0]
            
            # Find original backup time if recorded in activity_logs
            original_date = None
            try:
                cursor.execute("SELECT created_at FROM activity_logs WHERE action='BACKUP' ORDER BY id DESC LIMIT 1")
                row_date = cursor.fetchone()
                if row_date:
                    original_date = row_date[0]
            except Exception:
                pass
                
            checksum = BackupService.calculate_sha256(filepath)
            size = os.path.getsize(filepath)
            
            return True, {
                'database_version': db_version,
                'app_version': app_version,
                'created_at': original_date or local_now().isoformat(),
                'size': size,
                'checksum': checksum
            }
        except Exception:
            return False, "Không thể đọc thông tin Metadata từ cơ sở dữ liệu."
        finally:
            if conn:
                conn.close()
