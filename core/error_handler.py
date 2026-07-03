# core/error_handler.py
from flask import jsonify, redirect, render_template, url_for, request, make_response
from werkzeug.exceptions import HTTPException

from extensions import db
from core.exceptions import SpaManagerException
from core.logger import app_logger
from models.activity_log import ActivityLog
from services.notification_service import NotificationService
from services.auth_service import AuthService
from sqlalchemy.exc import SQLAlchemyError

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
    def is_json_request():
        if request.is_json:
            return True

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return True

        accept = request.accept_mimetypes
        json_quality = accept['application/json']
        html_quality = accept['text/html']
        best_match = accept.best_match(['application/json', 'text/html'])
        return best_match == 'application/json' and json_quality > html_quality

    @staticmethod
    def is_media_or_static_request():
        return (
            request.path.startswith('/media/')
            or request.endpoint == 'media_file'
            or request.path.startswith('/static/')
            or request.endpoint == 'static'
        )

    @staticmethod
    def is_health_request():
        return request.path.startswith('/health') or request.endpoint == 'health_check'

    @staticmethod
    def json_error_payload(error, message, status_code, fields=None):
        payload = {
            "status": "error",
            "error": error,
            "message": message,
        }
        if fields:
            payload["fields"] = fields
        response = jsonify(payload)
        response.status_code = status_code
        response.headers["Cache-Control"] = "no-store"
        return response

    @staticmethod
    def render_html_status(template_name, status_code):
        response = make_response(render_template(template_name), status_code)
        response.headers["Cache-Control"] = "no-store"
        return response

    @staticmethod
    def handle_http_exception(e):
        if ErrorHandler.is_health_request() or ErrorHandler.is_media_or_static_request():
            return e.get_response()

        status_code = e.code or 500
        description = getattr(e, "description", "")

        if ErrorHandler.is_json_request():
            error_map = {
                400: "bad_request",
                401: "unauthorized",
                403: "forbidden",
                404: "not_found",
                405: "method_not_allowed",
                422: "validation_error",
            }
            error = error_map.get(status_code, "http_error")
            message = "Không tìm thấy tài nguyên." if status_code == 404 else description
            return ErrorHandler.json_error_payload(error, message, status_code)

        if status_code == 404:
            app_logger.warning(
                f"Path: {request.path} | Method: {request.method} | Status: 404 | Msg: not found",
                module="HTTP_404"
            )
            return ErrorHandler.render_html_status("errors/404.html", 404)

        if status_code == 401:
            next_url = request.full_path if request.full_path else request.path
            return redirect(url_for('auth.login', next=next_url))

        if status_code == 403:
            response = make_response(description or "Forbidden", 403)
            response.headers["Cache-Control"] = "no-store"
            return response

        return e.get_response()

    @staticmethod
    def handle_exception(e):
        """
        Standardized exception handler.
        Logs to file, maps to activity log if critical, flashes/returns JSON/HTML.
        """
        if isinstance(e, HTTPException):
            return ErrorHandler.handle_http_exception(e)

        message, code, status_code, severity = ExceptionMapper.map_exception(e)

        if status_code >= 500 or isinstance(e, SQLAlchemyError):
            try:
                db.session.rollback()
            except Exception:
                pass

        current_user = AuthService.get_current_user()
        user_identity = f"user_id={current_user.id}, username={current_user.username}" if current_user else "anonymous"
        log_msg = f"Path: {request.path} | Method: {request.method} | Status: {status_code} | User: {user_identity} | Msg: {message}"
        use_exc_info = (status_code >= 500 or severity == "CRITICAL")
        
        if status_code >= 500 or severity in ["ERROR", "CRITICAL"]:
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

        if ErrorHandler.is_health_request():
            return ErrorHandler.json_error_payload("internal_server_error", "Đã xảy ra lỗi hệ thống.", 500)

        if ErrorHandler.is_media_or_static_request():
            if isinstance(e, HTTPException):
                return e.get_response()
            return ErrorHandler.render_html_status("errors/500.html", 500)

        if ErrorHandler.is_json_request():
            error_map = {
                "AUTHENTICATION_FAILED": "unauthorized",
                "NOT_FOUND": "not_found",
                "VALIDATION_ERROR": "validation_error",
                "PERMISSION_DENIED": "forbidden",
                "CONFLICT": "conflict",
            }
            payload = {
                "status": "error",
                "error": "internal_server_error" if status_code >= 500 else error_map.get(code, code.lower()),
                "message": "Đã xảy ra lỗi hệ thống." if status_code >= 500 else message,
            }
            if hasattr(e, "field_errors") and e.field_errors:
                payload["fields"] = e.field_errors
            response = jsonify(payload)
            response.status_code = status_code
            response.headers["Cache-Control"] = "no-store"
            return response

        if isinstance(e, SpaManagerException) and status_code == 401:
            next_url = request.full_path if request.full_path else request.path
            return redirect(url_for('auth.login', next=next_url))

        if isinstance(e, SpaManagerException) and status_code == 404:
            return ErrorHandler.render_html_status("errors/404.html", 404)

        if isinstance(e, SpaManagerException) and status_code == 403:
            response = make_response(message, 403)
            response.headers["Cache-Control"] = "no-store"
            return response

        if status_code >= 500:
            return ErrorHandler.render_html_status("errors/500.html", 500)

        if isinstance(e, SpaManagerException):
            NotificationService.flash_error(message)
            referer = request.headers.get('Referer')
            if referer and request.path not in referer:
                return redirect(referer)
            return redirect(url_for('dashboard.index'))

        return ErrorHandler.render_html_status("errors/500.html", 500)

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
