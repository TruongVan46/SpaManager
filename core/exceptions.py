# core/exceptions.py

class SpaManagerException(Exception):
    def __init__(self, message, code="SYSTEM_ERROR", status_code=500, severity="ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.severity = severity

class BusinessException(SpaManagerException):
    def __init__(self, message, code="BUSINESS_ERROR", status_code=400, severity="WARNING"):
        super().__init__(message, code=code, status_code=status_code, severity=severity)

class ValidationException(BusinessException):
    def __init__(self, message, field_errors=None, code="VALIDATION_ERROR", status_code=400, severity="WARNING"):
        super().__init__(message, code=code, status_code=status_code, severity=severity)
        self.field_errors = field_errors or {}

class NotFoundException(BusinessException):
    def __init__(self, message, code="NOT_FOUND", status_code=404, severity="WARNING"):
        super().__init__(message, code=code, status_code=status_code, severity=severity)

class PermissionDeniedException(BusinessException):
    def __init__(self, message, code="PERMISSION_DENIED", status_code=403, severity="ERROR"):
        super().__init__(message, code=code, status_code=status_code, severity=severity)

class AuthenticationException(BusinessException):
    def __init__(self, message, code="AUTHENTICATION_FAILED", status_code=401, severity="WARNING"):
        super().__init__(message, code=code, status_code=status_code, severity=severity)

class ConflictException(BusinessException):
    def __init__(self, message, code="CONFLICT", status_code=409, severity="WARNING"):
        super().__init__(message, code=code, status_code=status_code, severity=severity)

class SystemException(SpaManagerException):
    def __init__(self, message, code="SYSTEM_ERROR", status_code=500, severity="CRITICAL"):
        super().__init__(message, code=code, status_code=status_code, severity=severity)
