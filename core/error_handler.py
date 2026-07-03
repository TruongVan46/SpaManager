# core/error_handler.py
from flask import jsonify, redirect, url_for, request
from werkzeug.exceptions import HTTPException

from extensions import db
from core.exceptions import SpaManagerException
from core.logger import app_logger
from models.activity_log import ActivityLog
from services.notification_service import NotificationService
from services.auth_service import AuthService

class ExceptionMapper:
    @staticmethod
    def map_exception(e):
        """
        Map any Python exception to: (message, code, status_code, severity)
        """
        if isinstance(e, SpaManagerException):
            return e.message, e.code, e.status_code, e.severity
        
        if isinstance(e, HTTPException):
            return (
                e.description,
                f"HTTP_{e.code}",
                e.code,
                "INFO"
            )
        
        # Python built-in standard exceptions
        if isinstance(e, ValueError):
            return str(e), "VALIDATION_ERROR", 400, "WARNING"
        if isinstance(e, KeyError):
            return f"Thiếu thông tin yêu cầu: {str(e)}", "VALIDATION_ERROR", 400, "WARNING"
        
        # Fallback for general unexpected exceptions
        return f"Hệ thống gặp sự cố: {str(e)}", "SYSTEM_ERROR", 500, "CRITICAL"

class ErrorHandler:
    @staticmethod
    def handle_exception(e):
        """
        Standardized exception handler.
        Logs to file, maps to activity log if critical, flashes/returns JSON.
        """
        message, code, status_code, severity = ExceptionMapper.map_exception(e)

        # Log to file using app_logger (only log stacktrace for SYSTEM_ERROR or CRITICAL)
        log_msg = f"Path: {request.path} | Method: {request.method} | Msg: {message}"
        use_exc_info = (code == "SYSTEM_ERROR" or severity == "CRITICAL")
        
        if severity in ["ERROR", "CRITICAL"]:
            app_logger.error(log_msg, module=code, exc_info=use_exc_info)
        else:
            app_logger.warning(log_msg, module=code)

        # Log to Database ActivityLog if severity is high and not simple validation or HTTP exceptions
        if code != "VALIDATION_ERROR" and not code.startswith("HTTP_") and severity in ["WARNING", "ERROR", "CRITICAL"]:
            try:
                ErrorHandler.log_to_activity_log(message, code, severity)
            except Exception as log_ex:
                # Direct app_logger fallback if database fails
                app_logger.critical(f"Failed to save ActivityLog: {log_ex}", module="SYSTEM")

        # Check if request is AJAX
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json

        if request.path.startswith('/media/') or request.endpoint == 'media_file' or request.path.startswith('/static/'):
            return e.get_response()
        
        if is_ajax:
            payload = {
                "success": False,
                "code": code,
                "message": message
            }
            if hasattr(e, "field_errors") and e.field_errors:
                payload["field_errors"] = e.field_errors
            return jsonify(payload), status_code
        else:
            NotificationService.flash_error(message)

            # Smart redirect: try referer, fallback to index
            referer = request.headers.get('Referer')
            if referer and request.path not in referer:
                return redirect(referer)
            return redirect(url_for('dashboard.index'))

    @staticmethod
    def log_to_activity_log(message, code, severity):
        if code.startswith("HTTP_"):
            return
            
        current_user = AuthService.get_current_user()
        user_id = current_user.id if current_user else None
        
        # Build unique log entry
        log = ActivityLog(
            module="SYSTEM",
            action=code,
            severity=severity,
            description=message,
            user_id=user_id
        )
        
        # Rollback active failed transactions to allow logging
        try:
            db.session.rollback()
        except Exception:
            pass
            
        db.session.add(log)
        db.session.commit()
