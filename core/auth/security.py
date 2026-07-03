# core/auth/security.py
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

class PasswordPolicy:
    @staticmethod
    def validate(password):
        """
        Validate password complexity.
        Returns: (is_valid_bool, error_message_str)
        """
        if not password:
            return False, "Mật khẩu không được để trống."
        if len(password) < 8:
            return False, "Mật khẩu mới phải chứa ít nhất 8 ký tự."
        # Extensible: add complexity checks here in the future
        return True, ""
