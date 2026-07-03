# validators/auth_validator.py
from validators.base_validator import BaseValidator
from validators.messages import ValidationMessages
from validators.rules import validate_required, validate_length


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
            
        # 2. Complexity check (Password Policy)
        if not validate_length(new_password, min_len=8):
            self.add_error('new_password', ValidationMessages.PASSWORD_LENGTH)
            
        # 3. Match check
        if new_password != confirm_password:
            self.add_error('confirm_password', ValidationMessages.PASSWORD_MATCH)
            
        # 4. Same as old check
        if current_password == new_password:
            self.add_error('new_password', ValidationMessages.PASSWORD_SAME)
            
        return self.result
