# core/auth/enums.py
import enum

class UserRole(enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    STAFF = "STAFF"
    APPROVAL_OWNER = "APPROVAL_OWNER"


ROLE_ALIASES = {
    "owner": UserRole.OWNER.value,
    "admin": UserRole.ADMIN.value,
    "staff": UserRole.STAFF.value,
    "user": UserRole.STAFF.value,
}


def normalize_role_value(role):
    if role is None:
        return None
    normalized = str(role).strip()
    if not normalized:
        return None
    upper_normalized = normalized.upper()
    if upper_normalized in {member.value for member in UserRole}:
        return upper_normalized
    return ROLE_ALIASES.get(normalized.lower(), upper_normalized)
