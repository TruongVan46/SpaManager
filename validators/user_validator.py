from validators.base_validator import BaseValidator
from validators.messages import ValidationMessages
from validators.rules import validate_required, validate_length, validate_email


class UserValidator(BaseValidator):
    def validate_create(self, data):
        self.result.field_errors.clear()
        self.result.success = True

        username = (data.get("username") or "").strip()
        full_name = (data.get("full_name") or "").strip()
        email = (data.get("email") or "").strip()
        password = data.get("password") or ""
        confirm_password = data.get("confirm_password") or ""
        role = (data.get("role") or "").strip()

        self._validate_common(username, full_name, email, role)

        if not validate_required(password):
            self.add_error("password", ValidationMessages.REQUIRED)
        elif not validate_length(password, min_len=8):
            self.add_error("password", ValidationMessages.PASSWORD_LENGTH)

        if not validate_required(confirm_password):
            self.add_error("confirm_password", ValidationMessages.REQUIRED)
        elif password != confirm_password:
            self.add_error("confirm_password", ValidationMessages.PASSWORD_MATCH)

        return self.result

    def validate_update(self, data):
        self.result.field_errors.clear()
        self.result.success = True

        username = (data.get("username") or "").strip()
        full_name = (data.get("full_name") or "").strip()
        email = (data.get("email") or "").strip()
        role = (data.get("role") or "").strip()

        self._validate_common(username, full_name, email, role)
        return self.result

    def validate_reset_password(self, data):
        self.result.field_errors.clear()
        self.result.success = True

        password = data.get("new_password") or ""
        confirm_password = data.get("confirm_password") or ""

        if not validate_required(password):
            self.add_error("new_password", ValidationMessages.REQUIRED)
        elif not validate_length(password, min_len=8):
            self.add_error("new_password", ValidationMessages.PASSWORD_LENGTH)

        if not validate_required(confirm_password):
            self.add_error("confirm_password", ValidationMessages.REQUIRED)
        elif password != confirm_password:
            self.add_error("confirm_password", ValidationMessages.PASSWORD_MATCH)

        return self.result

    def _validate_common(self, username, full_name, email, role):
        if not validate_required(username):
            self.add_error("username", ValidationMessages.REQUIRED)
        elif not validate_length(username, min_len=3, max_len=100):
            self.add_error("username", ValidationMessages.LENGTH.format(min=3, max=100))

        if not validate_required(full_name):
            self.add_error("full_name", ValidationMessages.REQUIRED)
        elif not validate_length(full_name, min_len=2, max_len=100):
            self.add_error("full_name", ValidationMessages.LENGTH.format(min=2, max=100))

        if email and not validate_email(email):
            self.add_error("email", ValidationMessages.INVALID_EMAIL)

        if not validate_required(role):
            self.add_error("role", ValidationMessages.REQUIRED)

