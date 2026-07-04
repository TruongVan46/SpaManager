from functools import wraps

from flask import abort

from core.auth.permissions import can_manage_users
from services.auth_service import AuthService


def _require_current_user():
    user = AuthService.get_current_active_user()
    if not user:
        abort(401)
    return user


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        _require_current_user()
        return f(*args, **kwargs)
    return decorated_function


def permission_required(permission=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            current_user = _require_current_user()
            if permission is not None and not permission(current_user):
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


manager_required = permission_required(can_manage_users)
