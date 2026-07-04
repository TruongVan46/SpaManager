import os
import uuid
import shutil
from datetime import datetime
from flask import render_template, request, flash, redirect, url_for, send_file, current_app, jsonify, abort
from werkzeug.utils import secure_filename
from routes import setting_bp
from models.setting import Setting
from models.customer import Customer
from models.service import Service
from models.appointment import Appointment
from models.invoice import Invoice
from services.backup_service import BackupService
from services.restore_service import RestoreService
from services.import_service import ImportService
from repositories.backup_repository import BackupRepository
from core.logger import app_logger
from services.activity_log_service import ActivityLogService
from services.auth_service import AuthService
from core.auth.permissions import can_manage_settings
from utils.media_storage import resolve_media_file_path
from utils.timezone_utils import local_now, to_local_datetime


class SimplePagination:
    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = (total + per_page - 1) // per_page
        self.has_prev = page > 1
        self.prev_num = page - 1
        self.has_next = page < self.pages
        self.next_num = page + 1

    def iter_pages(self, left_edge=1, right_edge=1, left_current=2, right_current=2):
        pages = []
        for i in range(1, self.pages + 1):
            if i <= left_edge or i > self.pages - right_edge or \
               (self.page - left_current <= i <= self.page + right_current):
                pages.append(i)
            else:
                if pages and pages[-1] is not None:
                    pages.append(None)
        return pages


@setting_bp.before_request
def _require_settings_permission():
    current_user = AuthService.get_current_active_user()
    if not current_user:
        abort(401)
    if not can_manage_settings(current_user):
        abort(403)


@setting_bp.route('/settings')
def index():
    """Main settings page."""
    # Get spa info
    spa_info = Setting.get_all_spa_info()

    # Get record counts for data management stats
    stats = {
        'customers': Customer.query.count(),
        'services': Service.query.count(),
        'appointments': Appointment.query.count(),
        'invoices': Invoice.query.count(),
    }

    # Fetch and sync all backups on disk
    backup_error = None
    try:
        backups = BackupService.sync_backups(current_app)
    except Exception:
        app_logger.error("Failed to load backup list", module="BACKUP", exc_info=True)
        backups = []
        backup_error = "Không thể tải danh sách sao lưu."

    # Sort backups by created_at desc (newest first)
    backups.sort(key=lambda x: x['created_at'], reverse=True)

    # Server-side pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    total = len(backups)
    
    start = (page - 1) * per_page
    end = start + per_page
    paginated_backups = backups[start:end]
    
    pagination_obj = SimplePagination(paginated_backups, page, per_page, total)

    return render_template(
        'setting/index.html', 
        spa_info=spa_info, 
        stats=stats, 
        backups=paginated_backups,
        backups_pagination=pagination_obj,
        page=page,
        per_page=per_page,
        backup_error=backup_error
    )


@setting_bp.route('/settings/save-spa-info', methods=['POST'])
def save_spa_info():
    """Save spa information."""
    data = {
        'spa_name': request.form.get('spa_name', '').strip(),
        'spa_owner': request.form.get('spa_owner', '').strip(),
        'spa_phone': request.form.get('spa_phone', '').strip(),
        'spa_email': request.form.get('spa_email', '').strip(),
        'spa_address': request.form.get('spa_address', '').strip(),
        'spa_open_time': request.form.get('spa_open_time', '').strip(),
        'spa_close_time': request.form.get('spa_close_time', '').strip(),
    }

    # Handle logo upload
    logo_file = request.files.get('spa_logo')
    old_logo_setting = Setting.get('spa_logo')
    new_logo_path = None
    if logo_file and logo_file.filename:
        # Save logo file into persistent storage
        upload_dir = current_app.config['LOGO_UPLOAD_FOLDER']
        os.makedirs(upload_dir, exist_ok=True)

        filename = secure_filename(logo_file.filename)
        ext = os.path.splitext(filename)[1].lower()
        allowed_exts = ['.png', '.jpg', '.jpeg', '.webp']
        if ext in allowed_exts:
            logo_filename = f'{uuid.uuid4().hex}{ext}'
            logo_path = os.path.join(upload_dir, logo_filename)
            logo_file.save(logo_path)
            new_logo_path = logo_path
            data['spa_logo'] = f'logos/{logo_filename}'
        else:
            flash('Định dạng logo không hợp lệ. Chấp nhận: PNG, JPG, JPEG, WEBP', 'warning')

    try:
        Setting.save_spa_info(data)
        if new_logo_path and old_logo_setting and old_logo_setting != data.get('spa_logo'):
            old_logo_file = resolve_media_file_path(
                old_logo_setting,
                'logo',
                current_app.config['UPLOAD_ROOT'],
                current_app.root_path
            )
            if old_logo_file and os.path.exists(old_logo_file):
                try:
                    os.remove(old_logo_file)
                except Exception:
                    pass
        flash('Lưu thông tin Spa thành công!', 'success')
    except Exception as e:
        if new_logo_path and os.path.exists(new_logo_path):
            try:
                os.remove(new_logo_path)
            except Exception:
                pass
        flash(f'Lỗi khi lưu thông tin: {str(e)}', 'danger')

    return redirect(url_for('setting.index'))


@setting_bp.route('/settings/delete-logo', methods=['POST'])
def delete_logo():
    """Delete spa logo."""
    try:
        # Get current logo setting
        logo_path_setting = Setting.get('spa_logo')
        if logo_path_setting:
            # Update database first, then delete file if it exists
            Setting.set('spa_logo', '')
            full_path = resolve_media_file_path(
                logo_path_setting,
                'logo',
                current_app.config['UPLOAD_ROOT'],
                current_app.root_path
            )
            if full_path and os.path.exists(full_path):
                try:
                    os.remove(full_path)
                except Exception:
                    pass
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500



# ──────────────────────────────────────────────
# Backup & Restore
# ──────────────────────────────────────────────

@setting_bp.route('/settings/backup', methods=['POST'])
def backup_database():
    """Create a database backup with metadata."""
    notes = request.form.get('notes', '').strip()
    backup_type = request.form.get('backup_type', 'Manual').strip()
    
    bid, filename, filepath = BackupService.create_backup(
        current_app, 
        notes=notes, 
        backup_type=backup_type
    )

    if bid:
        # Check if requested format is JSON (AJAX)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json' or request.form.get('format') == 'json':
            flash('Đã tạo bản sao lưu thành công.', 'success')
            return jsonify({
                'success': True,
                'message': 'Đã tạo bản sao lưu thành công.',
                'download_url': url_for('setting.download_backup', backup_id=bid)
            })
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
    else:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
            return jsonify({'success': False, 'message': 'Không thể tạo bản sao lưu.'}), 500
        flash('Không thể tạo bản sao lưu. Vui lòng thử lại.', 'danger')
        return redirect(url_for('setting.index'))


@setting_bp.route('/settings/backup/download/<string:backup_id>')
def download_backup(backup_id):
    """Download a backup file using its UUID."""
    meta = BackupRepository.get_by_id(current_app, backup_id)
    if not meta:
        flash('Không tìm thấy bản sao lưu.', 'danger')
        return redirect(url_for('setting.index'))
        
    filepath = BackupService.get_backup_file_path(current_app, meta.get('filename'))
    if not filepath or not os.path.exists(filepath):
        flash('File sao lưu không còn tồn tại trên đĩa.', 'danger')
        return redirect(url_for('setting.index'))
        
    return send_file(
        filepath,
        as_attachment=True,
        download_name=os.path.basename(meta.get('filename') or 'backup.sqlite'),
        mimetype='application/octet-stream'
    )


@setting_bp.route('/settings/backup/delete/<string:backup_id>', methods=['POST'])
def delete_backup(backup_id):
    """Delete a backup file and its metadata using its UUID."""
    success = BackupService.delete_backup(current_app, backup_id)
    if success:
        return jsonify({'success': True, 'message': 'Đã xóa bản sao lưu vĩnh viễn.'})
    return jsonify({'success': False, 'message': 'Không thể xóa bản sao lưu.'}), 400


@setting_bp.route('/settings/backup/notes/<string:backup_id>', methods=['POST'])
def update_notes(backup_id):
    """Update notes metadata for a backup using its UUID."""
    data = request.get_json() or {}
    new_notes = data.get('notes', '').strip()
    success = BackupService.update_notes(current_app, backup_id, new_notes)
    if success:
        return jsonify({'success': True, 'message': 'Cập nhật ghi chú thành công.'})
    return jsonify({'success': False, 'message': 'Không thể cập nhật ghi chú.'}), 400


@setting_bp.route('/settings/backup/restore/<string:backup_id>', methods=['POST'])
def restore_from_backup(backup_id):
    """Restore database from a specific backup file using its UUID."""
    meta = BackupRepository.get_by_id(current_app, backup_id)
    if not meta:
        return jsonify({'success': False, 'message': 'Không tìm thấy bản sao lưu.'}), 400
        
    filepath = BackupService.get_backup_file_path(current_app, meta.get('filename'))
    if not filepath or not os.path.exists(filepath):
        return jsonify({'success': False, 'message': 'File sao lưu không tồn tại trên đĩa.'}), 400
        
    # Check integrity
    status = BackupService.check_file_integrity(filepath)
    if status != 'Valid':
        return jsonify({'success': False, 'message': 'Bản sao lưu không hợp lệ hoặc đã bị hỏng.'}), 400
        
    try:
        success, message = RestoreService.restore_database(current_app, filepath)
        if success:
            ActivityLogService.log_action(
                module=ActivityLogService.MODULE_SETTINGS,
                action='RESTORE',
                description=f'Khôi phục dữ liệu từ bản sao lưu: {meta["display_name"]}',
                severity=ActivityLogService.SEVERITY_SUCCESS
            )
            flash(message, 'success')
            return jsonify({'success': True, 'message': message})
        else:
            flash(message, 'danger')
            return jsonify({'success': False, 'message': message}), 500
    except Exception as e:
        flash('Lỗi khi khôi phục dữ liệu.', 'danger')
        app_logger.error("Restore from backup failed", module="BACKUP", exc_info=True)
        return jsonify({'success': False, 'message': 'Lỗi khi khôi phục dữ liệu.'}), 500


@setting_bp.route('/settings/backup/upload', methods=['POST'])
def upload_backup():
    """Upload an external backup file and inspect it."""
    if 'backup_file' not in request.files:
        return jsonify({'success': False, 'message': 'Không tìm thấy tệp tải lên.'}), 400
        
    file = request.files['backup_file']
    notes = request.form.get('notes', '').strip()
    
    if file.filename == '':
        return jsonify({'success': False, 'message': 'Chưa chọn tệp tin.'}), 400
        
    # Check extension
    filename = file.filename
    _, ext = os.path.splitext(filename.lower())
    if ext not in ['.db', '.sqlite', '.sqlite3']:
        return jsonify({'success': False, 'message': 'Định dạng tệp không hợp lệ. Chỉ chấp nhận .db, .sqlite, .sqlite3.'}), 400
        
    # Save to a temporary file in the backup directory
    backup_dir = BackupService.get_backup_dir(current_app)
    temp_filename = f"temp_upload_{uuid.uuid4().hex}{ext}"
    temp_filepath = os.path.join(backup_dir, temp_filename)
    
    try:
        file.save(temp_filepath)
        size = os.path.getsize(temp_filepath)
        if size > 100 * 1024 * 1024: # 100 MB
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return jsonify({'success': False, 'message': 'Kích thước tệp vượt quá giới hạn cho phép (Tối đa 100MB).'}), 400
            
        # Verify SQLite signature (first 16 bytes)
        with open(temp_filepath, 'rb') as f:
            header = f.read(16)
        if header != b'SQLite format 3\x00':
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return jsonify({'success': False, 'message': 'Tệp tải lên không phải là một cơ sở dữ liệu SQLite hợp lệ.'}), 400
            
        # Inspect database and read metadata
        is_valid, metadata_or_error = BackupService.inspect_external_backup(temp_filepath)
        if not is_valid:
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return jsonify({'success': False, 'message': metadata_or_error}), 400
            
        # Check for duplicate SHA256 checksum in existing backup metadata
        checksum = metadata_or_error['checksum']
        existing_backups = BackupRepository.load_all(current_app)
        
        # Check duplicates
        for bid, meta in existing_backups.items():
            meta_checksum = meta.get('checksum')
            if not meta_checksum:
                # Calculate dynamically and save it in metadata to cache
                meta_path = BackupService.get_backup_file_path(current_app, meta.get('filename'))
                if meta_path and os.path.exists(meta_path):
                    meta_checksum = BackupService.calculate_sha256(meta_path)
                    if meta_checksum:
                        meta['checksum'] = meta_checksum
                        BackupRepository.save(current_app, bid, meta)
            
            if meta_checksum == checksum:
                if os.path.exists(temp_filepath):
                    os.remove(temp_filepath)
                return jsonify({'success': False, 'message': 'Backup này đã tồn tại trong hệ thống.'}), 400
                
        # Generate final file name and UUID
        backup_id = str(uuid.uuid4())
        timestamp_str = local_now().strftime('%Y-%m-%d_%H-%M-%S')
        db_version = metadata_or_error['database_version']
        safe_db_version = BackupService.sanitize_filename_component(db_version, 'v1.0')
        final_filename = f"SpaManager_Imported_{timestamp_str}_v{safe_db_version}{ext}"
        final_filepath = os.path.join(backup_dir, final_filename)
        
        # Rename temporary file to final path
        shutil.move(temp_filepath, final_filepath)
        
        # Save metadata to registry
        current_user = AuthService.get_current_user()
        created_by_name = current_user.username if current_user else None
        
        display_name = f"Backup Imported {local_now().strftime('%d/%m/%Y %H:%M')}"
        notes_str = notes if notes else f"Nhập từ tệp {filename}"
        
        meta_entry = {
            'id': backup_id,
            'filename': final_filename,
            'display_name': display_name,
            'created_at': metadata_or_error['created_at'],
            'size': size,
            'database_version': db_version,
            'app_version': metadata_or_error['app_version'],
            'notes': notes_str,
            'type': 'Manual',
            'created_by': created_by_name,
            'status': 'Valid',
            'source': 'Imported',
            'checksum': checksum
        }
        BackupRepository.save(current_app, backup_id, meta_entry)
        
        # 1. Application Log
        app_logger.info(f"Imported Backup: {final_filename} successfully registered in system (Size: {size} bytes)", module="BACKUP")
        
        # 2. Activity Log
        ActivityLogService.log_action(
            module=ActivityLogService.MODULE_SETTINGS,
            action='IMPORT_BACKUP',
            description=f'Tải lên bản sao lưu từ ngoài: {display_name}',
            severity=ActivityLogService.SEVERITY_SUCCESS
        )
        
        # Prepare backup info for wizard trigger
        dt_created = to_local_datetime(metadata_or_error['created_at'], assume_utc=True)
        backup_info = {
            'id': backup_id,
            'display_name': display_name,
            'created_at_timestamp': dt_created.timestamp(),
            'size_friendly': BackupService.format_size(size),
            'version_db': db_version,
            'version_app': metadata_or_error['app_version'],
            'notes': notes_str
        }
        
        return jsonify({
            'success': True,
            'message': 'Nhập bản sao lưu thành công.',
            'backup_id': backup_id,
            'backup_info': backup_info
        })
    except Exception as e:
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except Exception:
                pass
        app_logger.error("Error during backup upload", module="BACKUP", exc_info=True)
        return jsonify({'success': False, 'message': 'Lỗi khi xử lý tệp tải lên.'}), 500


# ──────────────────────────────────────────────
# Restore Wizard Endpoints
# ──────────────────────────────────────────────

@setting_bp.route('/settings/restore-wizard/validate/<string:backup_id>', methods=['GET'])
def restore_wizard_validate(backup_id):
    """Validate a backup for the Restore Wizard.
    Returns JSON with keys: exists, integrity, compatible, metadata.
    """
    result = BackupService.validate_backup(current_app, backup_id)
    return jsonify(result)

@setting_bp.route('/settings/restore-wizard/confirm', methods=['POST'])
def restore_wizard_confirm():
    """Confirm restore after validation.
    Expects JSON payload {"backup_id": "..."}.
    """
    data = request.get_json() or {}
    backup_id = data.get('backup_id')
    if not backup_id:
        return jsonify({'success': False, 'message': 'Missing backup_id'}), 400
    meta = BackupRepository.get_by_id(current_app, backup_id)
    if not meta:
        return jsonify({'success': False, 'message': 'Backup not found'}), 400
    filepath = BackupService.get_backup_file_path(current_app, meta.get('filename'))
    if not filepath or not os.path.exists(filepath):
        return jsonify({'success': False, 'message': 'File sao lưu không tồn tại trên đĩa.'}), 400
    success, message = RestoreService.restore_database(current_app, filepath)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')
    return jsonify({'success': success, 'message': message})

@setting_bp.route('/settings/restore', methods=['POST'])
def restore_database():
    """Restore database from uploaded backup file."""
    file = request.files.get('restore_file')
    if not file or not file.filename:
        flash('Vui lòng chọn file backup để khôi phục.', 'warning')
        return redirect(url_for('setting.index'))

    # Save uploaded file temporarily
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'import')
    os.makedirs(upload_dir, exist_ok=True)
    temp_path = os.path.join(upload_dir, 'restore_temp.sqlite')
    file.save(temp_path)

    try:
        success, message = RestoreService.restore_database(current_app, temp_path)
        if success:
            flash(message, 'success')
        else:
            flash(message, 'danger')
    except Exception as e:
        app_logger.error("Restore uploaded backup failed", module="BACKUP", exc_info=True)
        flash('Lỗi khi khôi phục dữ liệu.', 'danger')
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

    return redirect(url_for('setting.index'))


# ──────────────────────────────────────────────
# Import Templates
# ──────────────────────────────────────────────

@setting_bp.route('/settings/template/customers')
def download_customer_template():
    """Download the customer import template."""
    filepath = ImportService.generate_customer_template(current_app)
    return send_file(
        filepath,
        as_attachment=True,
        download_name='customers_template.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@setting_bp.route('/settings/template/services')
def download_service_template():
    """Download the service import template."""
    filepath = ImportService.generate_service_template(current_app)
    return send_file(
        filepath,
        as_attachment=True,
        download_name='services_template.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ──────────────────────────────────────────────
# Import Data
# ──────────────────────────────────────────────


@setting_bp.route('/settings/import/analyze', methods=['POST'])
def import_analyze():
    """Analyze uploaded Excel file for preview, validation, and duplicates."""
    file = request.files.get('import_file')
    import_type = request.form.get('import_type')  # 'customers' or 'services'
    
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'Vui lòng chọn file để import.'}), 400
    if import_type not in ('customers', 'services'):
        return jsonify({'success': False, 'message': 'Kiểu import không hợp lệ.'}), 400

    upload_dir = ImportService.get_upload_dir(current_app)
    # Generate unique filename to avoid collision
    temp_filename = f"temp_import_{uuid.uuid4().hex}.xlsx"
    temp_path = os.path.join(upload_dir, temp_filename)
    file.save(temp_path)

    try:
        result = ImportService.analyze_file(current_app, temp_path, import_type)
        if result.get('success'):
            result['temp_file_id'] = temp_filename
        else:
            # Clean up immediately if analysis failed
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        return jsonify(result)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        app_logger.error("Import analysis failed", module="IMPORT", exc_info=True)
        return jsonify({'success': False, 'message': 'Lỗi phân tích file.'}), 500


@setting_bp.route('/settings/import/execute', methods=['POST'])
def import_execute():
    """Execute the import process on analyzed file with user choices."""
    data = request.get_json() or {}
    temp_file_id = data.get('temp_file_id')
    import_type = data.get('import_type')
    duplicate_action = data.get('duplicate_action', 'skip')  # 'skip', 'overwrite', 'insert_only'
    all_or_nothing = data.get('all_or_nothing', False)

    if not temp_file_id or import_type not in ('customers', 'services'):
        return jsonify({'success': False, 'message': 'Tham số yêu cầu không hợp lệ.'}), 400

    upload_dir = ImportService.get_upload_dir(current_app)
    temp_path = os.path.join(upload_dir, os.path.basename(temp_file_id))

    if not os.path.exists(temp_path):
        return jsonify({'success': False, 'message': 'File tạm đã hết hạn hoặc không tồn tại.'}), 400

    try:
        report = ImportService.execute_import(
            current_app, temp_path, import_type, duplicate_action, all_or_nothing
        )
        return jsonify({'success': True, 'report': report})
    except Exception as e:
        app_logger.error("Import execution failed", module="IMPORT", exc_info=True)
        return jsonify({'success': False, 'message': 'Lỗi thực thi import.'}), 500


@setting_bp.route('/settings/import/errors/download/<string:filename>')
def download_import_errors(filename):
    """Download import error report text file."""
    # Prevent directory traversal attacks
    filename = os.path.basename(filename)
    upload_dir = ImportService.get_upload_dir(current_app)
    filepath = os.path.join(upload_dir, filename)
    if not os.path.exists(filepath):
        flash('Không tìm thấy báo cáo lỗi.', 'danger')
        return redirect(url_for('setting.index'))
    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
        mimetype='text/plain'
    )

