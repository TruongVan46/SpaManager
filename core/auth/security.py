# core/auth/security.py
from dataclasses import dataclass, field

from werkzeug.security import generate_password_hash, check_password_hash


class PasswordHasher:
    @staticmethod
    def hash_password(password):
        """Hash a password string using Werkzeug security default."""
        return generate_password_hash(password)

    @staticmethod
    def verify_password(hash_val, password):
        """Verify a password string against its hashed representation."""
        return check_password_hash(hash_val, password)


@dataclass
class PasswordPolicyResult:
    valid: bool
    errors: dict = field(default_factory=dict)
    message: str = ""

    @property
    def is_valid(self):
        return self.valid


class PasswordPolicy:
    MIN_LENGTH = 8

    @staticmethod
    def _is_empty(password):
        return password is None or (isinstance(password, str) and password.strip() == "")

    @staticmethod
    def _normalize_identity(value):
        return (value or "").strip().lower()

    @staticmethod
    def validate_strength(password, min_length=None):
        """
        Validate required password strength rules.
        Returns: PasswordPolicyResult
        """
        min_length = min_length or PasswordPolicy.MIN_LENGTH
        errors = {}

        if PasswordPolicy._is_empty(password):
            errors["password"] = "Mật khẩu không được để trống."
        elif len(password) < min_length:
            errors["password"] = f"Mật khẩu mới phải có ít nhất {min_length} ký tự."

        if errors:
            return PasswordPolicyResult(valid=False, errors=errors, message=next(iter(errors.values())))
        return PasswordPolicyResult(valid=True, errors={}, message="")

    @staticmethod
    def validate_confirmation(password, confirm_password=None, require_confirm=True):
        errors = {}
        if require_confirm and PasswordPolicy._is_empty(confirm_password):
            errors["confirm_password"] = "Xác nhận mật khẩu không được để trống."
        elif require_confirm and password != confirm_password:
            errors["confirm_password"] = "Xác nhận mật khẩu không khớp."

        if errors:
            return PasswordPolicyResult(valid=False, errors=errors, message=next(iter(errors.values())))
        return PasswordPolicyResult(valid=True, errors={}, message="")

    @staticmethod
    def validate_reuse(password, current_password=None, current_password_hash=None, prevent_reuse=False):
        if not prevent_reuse:
            return PasswordPolicyResult(valid=True, errors={}, message="")

        if current_password is not None and password == current_password:
            return PasswordPolicyResult(
                valid=False,
                errors={"password": "Mật khẩu mới không được giống mật khẩu hiện tại."},
                message="Mật khẩu mới không được giống mật khẩu hiện tại.",
            )

        if current_password_hash and check_password_hash(current_password_hash, password):
            return PasswordPolicyResult(
                valid=False,
                errors={"password": "Mật khẩu mới không được giống mật khẩu hiện tại."},
                message="Mật khẩu mới không được giống mật khẩu hiện tại.",
            )

        return PasswordPolicyResult(valid=True, errors={}, message="")

    @staticmethod
    def validate_identity_similarity(password, username=None, email=None):
        errors = {}
        password_normalized = PasswordPolicy._normalize_identity(password)
        username_normalized = PasswordPolicy._normalize_identity(username)
        email_normalized = PasswordPolicy._normalize_identity(email)

        if password_normalized and username_normalized and password_normalized == username_normalized:
            errors["password"] = "Mật khẩu mới không được giống tên đăng nhập."
        elif password_normalized and email_normalized and password_normalized == email_normalized:
            errors["password"] = "Mật khẩu mới không được giống email."

        if errors:
            return PasswordPolicyResult(valid=False, errors=errors, message=next(iter(errors.values())))
        return PasswordPolicyResult(valid=True, errors={}, message="")

    @staticmethod
    def validate_password(password, confirm_password=None, current_password=None, current_password_hash=None, username=None, email=None, require_confirm=True, prevent_reuse=False):
        policy_checks = [
            PasswordPolicy.validate_strength(password),
            PasswordPolicy.validate_confirmation(password, confirm_password=confirm_password, require_confirm=require_confirm),
            PasswordPolicy.validate_reuse(password, current_password=current_password, current_password_hash=current_password_hash, prevent_reuse=prevent_reuse),
            PasswordPolicy.validate_identity_similarity(password, username=username, email=email),
        ]
        errors = {}
        for check in policy_checks:
            if not check.valid:
                errors.update(check.errors)

        if errors:
            return PasswordPolicyResult(valid=False, errors=errors, message=next(iter(errors.values())))
        return PasswordPolicyResult(valid=True, errors={}, message="")
