# validators/customer_validator.py
from validators.base_validator import BaseValidator
from validators.messages import ValidationMessages
from validators.rules import validate_required, validate_phone, validate_email, validate_date


class CustomerValidator(BaseValidator):
    def validate(self, data):
        self.result.field_errors.clear()
        self.result.success = True
        
        name = data.get('name', '')
        phone = data.get('phone', '')
        email = data.get('email', '')
        birthday = data.get('birthday', '')
        gender = data.get('gender', '')
        
        # 1. Name is required
        if not validate_required(name):
            self.add_error('name', ValidationMessages.REQUIRED)
            
        # 2. Phone format validation
        if phone and not validate_phone(phone):
            self.add_error('phone', ValidationMessages.INVALID_PHONE)
            
        # 3. Email format validation
        if email and not validate_email(email):
            self.add_error('email', ValidationMessages.INVALID_EMAIL)
            
        # 4. Birthday format validation
        if birthday and not validate_date(birthday, "%Y-%m-%d"):
            self.add_error('birthday', ValidationMessages.INVALID_DATE)
            
        return self.result
