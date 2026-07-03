# core/auth/decorators.py
from functools import wraps
from flask import abort
from services.auth_service import AuthService

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not AuthService.is_authenticated():
            abort(401)
        return f(*args, **kwargs)
    return decorated_function

def permission_required(permission=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not AuthService.is_authenticated():
                abort(401)
            # Future authorization checks will happen here
            return f(*args, **kwargs)
        return decorated_function
    return decorator
