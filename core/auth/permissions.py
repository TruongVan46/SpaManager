from core.auth.enums import UserRole, normalize_role_value


MANAGER_ROLES = {UserRole.OWNER.value, UserRole.ADMIN.value}
STAFF_ROLES = {UserRole.STAFF.value}


def _is_active_user(user):
    return bool(user and getattr(user, "is_active", False))


def _normalized_role(user):
    if not _is_active_user(user):
        return None
    return normalize_role_value(getattr(user, "role", None))


def is_owner(user=None):
    return _normalized_role(user) == UserRole.OWNER.value


def is_admin(user=None):
    return _normalized_role(user) == UserRole.ADMIN.value


def is_staff(user=None):
    return _normalized_role(user) in STAFF_ROLES


def is_manager(user=None):
    return _normalized_role(user) in MANAGER_ROLES


def can_manage_users(user=None):
    return is_manager(user)


def can_manage_settings(user=None):
    return is_manager(user)


def can_view_activity_logs(user=None):
    return is_manager(user)


def can_manage_backups(user=None):
    return is_manager(user)


def can_manage_business_data(user=None):
    return _is_active_user(user)
