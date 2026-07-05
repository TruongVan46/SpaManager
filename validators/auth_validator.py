# validators/auth_validator.py
from validators.base_validator import BaseValidator
from validators.messages import ValidationMessages
from core.auth.security import PasswordPolicy
from validators.rules import validate_required


class AuthValidator(BaseValidator):
    def validate(self, data):
        # Default fallback
        self.result.field_errors.clear()
        self.result.success = True
        return self.result
        
    def validate_login(self, data):
        self.result.field_errors.clear()
        self.result.success = True
        
        username = data.get('username', '')
        password = data.get('password', '')
        
        if not validate_required(username):
            self.add_error('username', ValidationMessages.REQUIRED)
        if not validate_required(password):
            self.add_error('password', ValidationMessages.REQUIRED)
            
        return self.result

    def validate_change_password(self, data):
        self.result.field_errors.clear()
        self.result.success = True
        
        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')
        confirm_password = data.get('confirm_password', '')
        
        # 1. Required checks
        if not validate_required(current_password):
            self.add_error('current_password', ValidationMessages.REQUIRED)
        if not validate_required(new_password):
            self.add_error('new_password', ValidationMessages.REQUIRED)
        if not validate_required(confirm_password):
            self.add_error('confirm_password', ValidationMessages.REQUIRED)
            
        if not self.is_valid:
            return self.result

        policy_result = PasswordPolicy.validate_password(
            new_password,
            confirm_password=confirm_password,
            current_password=current_password,
            require_confirm=True,
            prevent_reuse=True,
        )
        for field, message in policy_result.errors.items():
            self.add_error(field, message)
            
        return self.result
