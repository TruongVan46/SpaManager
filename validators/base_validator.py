# validators/base_validator.py
from validators.result import ValidationResult
from core.exceptions import ValidationException


class BaseValidator:
    def __init__(self):
        self.result = ValidationResult()

    @property
    def errors(self):
        return self.result.field_errors

    @property
    def is_valid(self):
        return self.result.success

    def add_error(self, field, message):
        self.result.add_error(field, message)

    def raise_if_invalid(self, message="Dữ liệu không hợp lệ."):
        if not self.is_valid:
            raise ValidationException(message, field_errors=self.errors)

    def validate(self, data):
        raise NotImplementedError("Subclasses must implement validate method")
