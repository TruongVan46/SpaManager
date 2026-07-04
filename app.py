# app.py - SpaManager Project
import os
import time
from flask import Flask, abort, jsonify, request, redirect, url_for, send_from_directory
from werkzeug.exceptions import HTTPException
from extensions import db
from config import get_active_config
from utils.timezone_utils import to_local_datetime
from utils.media_storage import normalize_media_reference, resolve_media_file_path
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from routes import (
    dashboard_bp, 
    customer_bp, 
    service_bp, 
    appointment_bp, 
    invoice_bp, 
    statistics_bp,
    setting_bp,
    activity_log_bp,
    recycle_bin_bp,
    auth_bp,
    user_bp
)
from services.auth_service import AuthService
from core.csrf import validate_csrf_request, csrf_token, CSRFError
from core.migration_cli import register_migration_commands

# Tạo ứng dụng Flask
app = Flask(__name__)

# Đọc cấu hình từ config.py theo môi trường hoạt động
app.config.from_object(get_active_config())

# Kết nối SQLAlchemy với Flask
db.init_app(app)

# Đăng ký Blueprints
app.register_blueprint(dashboard_bp)
app.register_blueprint(customer_bp)
app.register_blueprint(service_bp)
app.register_blueprint(appointment_bp)
app.register_blueprint(invoice_bp)
app.register_blueprint(statistics_bp)
app.register_blueprint(activity_log_bp)
app.register_blueprint(setting_bp)
app.register_blueprint(recycle_bin_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(user_bp)
register_migration_commands(app)

BASELINE_TABLES = [
    "users",
    "customers",
    "services",
    "appointments",
    "invoices",
    "invoice_details",
    "activity_logs",
    "settings",
]

# Favicon handler
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static', 'img'),
                               'logo.png', mimetype='image/png')

@app.route('/media/<path:path>')
def media_file(path):
    normalized_path = normalize_media_reference(path)
    resolved_path = resolve_media_file_path(
        normalized_path,
        None,
        app.config['UPLOAD_ROOT'],
        app.root_path
    )
    if not resolved_path:
        abort(404)
    return send_from_directory(os.path.dirname(resolved_path), os.path.basename(resolved_path))


@app.route('/health', methods=['GET'])
def health_check():
    try:
        db.session.execute(text("SELECT 1"))
        response = jsonify({
            "status": "ok",
            "app": app.config.get("APP_NAME", "SpaManager"),
            "database": "connected",
        })
        response.headers["Cache-Control"] = "no-store"
        return response, 200
    except SQLAlchemyError:
        db.session.rollback()
        response = jsonify({
            "status": "unhealthy",
            "app": app.config.get("APP_NAME", "SpaManager"),
            "database": "unavailable",
        })
        response.headers["Cache-Control"] = "no-store"
        return response, 503

# Global Authentication filter and context injector
@app.before_request
def require_login():
    # Skip check for static assets, login route, and favicon
    if request.endpoint is None:
        return

    if request.endpoint in ['static', 'auth.login', 'auth.logout', 'favicon', 'media_file', 'health_check'] or request.path.startswith('/health'):
        return

    # Redirect to login if user is not authenticated
    if not AuthService.is_authenticated():
        from core.error_handler import ErrorHandler
        if ErrorHandler.is_json_request():
            return jsonify({
                "status": "error",
                "error": "unauthorized",
                "message": "Phiên đăng nhập không hợp lệ."
            }), 401
        next_url = request.full_path
        return redirect(url_for('auth.login', next=next_url))


@app.before_request
def validate_state_changing_request_csrf():
    validate_csrf_request()

@app.context_processor
def inject_user():
    return dict(current_user=AuthService.get_current_user())

@app.context_processor
def inject_asset_helpers():
    def asset_version(relative_path):
        try:
            absolute_path = os.path.join(app.root_path, relative_path)
            return str(int(os.path.getmtime(absolute_path)))
        except OSError:
            return str(int(time.time()))

    def media_url(media_value, media_type=None):
        normalized_path = normalize_media_reference(media_value, media_type)
        if not normalized_path or normalized_path.startswith(("http://", "https://")):
            return normalized_path

        resolved_path = resolve_media_file_path(
            normalized_path,
            media_type,
            app.config['UPLOAD_ROOT'],
            app.root_path
        )
        if not resolved_path:
            return None
        return url_for('media_file', path=normalized_path)

    return dict(asset_version=asset_version, media_url=media_url)

@app.context_processor
def inject_csrf_helper():
    return dict(csrf_token=csrf_token)

# Ensure the database directory exists before creating the SQLite file (only if using SQLite)
db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
if db_uri.startswith('sqlite:///'):
    db_path = db_uri.replace('sqlite:///', '')
    database_dir = os.path.dirname(db_path)
    if database_dir:
        os.makedirs(database_dir, exist_ok=True)

# Ensure persistent upload directories exist at runtime
os.makedirs(app.config['PERSISTENT_ROOT'], exist_ok=True)
os.makedirs(app.config['UPLOAD_ROOT'], exist_ok=True)
os.makedirs(app.config['LOGO_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['AVATAR_UPLOAD_FOLDER'], exist_ok=True)

# Initialize Logging Framework
from core.logger import app_logger
app_logger.init_app(app)
app_logger.info("SpaManager application initialized successfully", module="SYSTEM")


def _baseline_schema_is_ready():
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    return all(table in existing_tables for table in BASELINE_TABLES)


with app.app_context():
    if _baseline_schema_is_ready():
        AuthService.seed_owner_if_empty()
    else:
        app_logger.warning(
            "Database schema is not initialized. Run 'flask db upgrade' before using the app.",
            module="MIGRATION"
        )

@app.template_filter('format_currency')
def format_currency(value):
    if value is None:
        return "0 VND"
    try:
        # Format number with dot as thousand separator
        formatted = "{:,.0f}".format(float(value)).replace(",", ".")
        return f"{formatted} VND"
    except (ValueError, TypeError):
        return "0 VND"

@app.template_filter('vietnam_time')
def vietnam_time(dt):
    from datetime import date as date_type, datetime as datetime_type

    if dt is None or (isinstance(dt, date_type) and not isinstance(dt, datetime_type)):
        return dt
    return to_local_datetime(dt, assume_utc=True)

@app.template_filter('highlight')
def highlight_filter(text, keyword):
    if not keyword:
        return text
    import re
    from markupsafe import Markup, escape
    escaped_text = str(escape(text))
    escaped_keyword = str(escape(keyword))
    
    pattern = re.compile(re.escape(escaped_keyword), re.IGNORECASE)
    highlighted = pattern.sub(lambda m: f'<mark class="search-highlight">{m.group(0)}</mark>', escaped_text)
    return Markup(highlighted)

@app.context_processor
def inject_active_page():
    from flask import request

    endpoint = request.endpoint or ""

    return dict(active_page=endpoint)

# Global Exception Handler registration
from core.error_handler import ErrorHandler

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    return ErrorHandler.handle_csrf_error(e)

@app.errorhandler(HTTPException)
def handle_http_exception(e):
    return ErrorHandler.handle_http_exception(e)

@app.errorhandler(Exception)
def handle_global_exception(e):
    return ErrorHandler.handle_exception(e)
