# validators/service_validator.py
from validators.base_validator import BaseValidator
from validators.messages import ValidationMessages
from validators.rules import validate_required, validate_number


class ServiceValidator(BaseValidator):
    def validate(self, data):
        self.result.field_errors.clear()
        self.result.success = True
        
        name = data.get('name', '')
        price = data.get('price', '')
        duration = data.get('duration', '')
        
        # 1. Name is required
        if not validate_required(name):
            self.add_error('name', ValidationMessages.REQUIRED)
            
        # 2. Price validation
        if not validate_required(price):
            self.add_error('price', ValidationMessages.REQUIRED)
        elif not validate_number(price, min_val=0):
            self.add_error('price', "Giá dịch vụ phải là số hợp lệ không âm.")
            
        # 3. Duration validation
        if duration is not None and duration != "":
            if not validate_number(duration, min_val=1):
                self.add_error('duration', "Thời lượng phải là số nguyên dương phút.")
                
        return self.result
