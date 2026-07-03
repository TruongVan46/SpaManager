import hmac
import secrets
import time

from flask import current_app, jsonify, request, session

CSRF_SESSION_KEY = "_csrf_token"
CSRF_ISSUED_AT_KEY = "_csrf_issued_at"
CSRF_HEADER_NAMES = ("X-CSRFToken", "X-CSRF-Token")
CSRF_METHODS = ("POST", "PUT", "PATCH", "DELETE")
CSRF_SAFE_PATH_PREFIXES = ("/health", "/static/", "/media/")


class CSRFError(Exception):
    def __init__(self, message="Phiên làm việc đã hết hạn hoặc yêu cầu không hợp lệ. Vui lòng tải lại trang.", status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = "csrf_failed"


def _is_enabled():
    return current_app.config.get("CSRF_ENABLED", True)


def _time_limit():
    value = current_app.config.get("CSRF_TIME_LIMIT", 3600)
    return None if value in (None, 0, "0") else int(value)


def _issue_token():
    token = secrets.token_urlsafe(32)
    session[CSRF_SESSION_KEY] = token
    session[CSRF_ISSUED_AT_KEY] = int(time.time())
    return token


def get_csrf_token():
    if not _is_enabled():
        return ""

    token = session.get(CSRF_SESSION_KEY)
    issued_at = session.get(CSRF_ISSUED_AT_KEY)
    time_limit = _time_limit()

    if not token or not issued_at:
        return _issue_token()

    if time_limit is not None and int(time.time()) - int(issued_at) > time_limit:
        return _issue_token()

    return token


def rotate_csrf_token():
    if not _is_enabled():
        return ""

    return _issue_token()


def clear_csrf_token():
    session.pop(CSRF_SESSION_KEY, None)
    session.pop(CSRF_ISSUED_AT_KEY, None)


def _extract_request_token():
    token = request.form.get("csrf_token")
    if token:
        return token

    for header_name in current_app.config.get("CSRF_HEADER_NAMES", CSRF_HEADER_NAMES):
        token = request.headers.get(header_name)
        if token:
            return token

    return None


def _is_safe_path():
    return any(request.path.startswith(prefix) for prefix in CSRF_SAFE_PATH_PREFIXES)


def requires_csrf_protection():
    if not _is_enabled():
        return False

    if request.method not in current_app.config.get("CSRF_METHODS", CSRF_METHODS):
        return False

    if request.endpoint is None:
        return False

    if _is_safe_path():
        return False

    return True


def validate_csrf_request():
    if not requires_csrf_protection():
        return

    expected_token = session.get(CSRF_SESSION_KEY)
    issued_at = session.get(CSRF_ISSUED_AT_KEY)
    if not expected_token or not issued_at:
        raise CSRFError()

    time_limit = _time_limit()
    if time_limit is not None and int(time.time()) - int(issued_at) > time_limit:
        session.pop(CSRF_SESSION_KEY, None)
        session.pop(CSRF_ISSUED_AT_KEY, None)
        raise CSRFError()

    supplied_token = _extract_request_token()
    if not supplied_token or not hmac.compare_digest(expected_token, supplied_token):
        raise CSRFError()


def csrf_token():
    return get_csrf_token()


def csrf_error_json(message, status_code=400):
    response = jsonify({
        "status": "error",
        "error": "csrf_failed",
        "message": message,
    })
    response.status_code = status_code
    response.headers["Cache-Control"] = "no-store"
    return response
