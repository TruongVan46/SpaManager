# validators/result.py

class ValidationResult:
    def __init__(self, success=True, errors=None, warnings=None, field_errors=None):
        self.field_errors = field_errors or {}
        self.errors = errors or []
        self.warnings = warnings or []
        self.success = success if not self.field_errors else False

    def add_error(self, field, message):
        self.success = False
        self.field_errors[field] = message

    def to_dict(self):
        return {
            "success": self.success,
            "errors": self.errors,
            "warnings": self.warnings,
            "field_errors": self.field_errors
        }
