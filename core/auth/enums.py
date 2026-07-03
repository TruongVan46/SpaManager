# core/auth/enums.py
import enum

class UserRole(enum.Enum):
    OWNER = "OWNER"
    # Future roles:
    # MANAGER = "MANAGER"
    # RECEPTIONIST = "RECEPTIONIST"
    # STAFF = "STAFF"
