# validators/import_validator.py
from validators.base_validator import BaseValidator
from validators.messages import ValidationMessages
from validators.rules import validate_required


class ImportValidator(BaseValidator):
    def validate(self, data):
        self.result.field_errors.clear()
        self.result.success = True
        
        import_type = data.get('import_type')
        duplicate_action = data.get('duplicate_action')
        
        # 1. Type validation
        if not validate_required(import_type):
            self.add_error('import_type', ValidationMessages.REQUIRED)
        elif import_type not in ['customers', 'services']:
            self.add_error('import_type', "Loại dữ liệu nhập khẩu không hợp lệ.")
            
        # 2. Duplicate action validation
        if not validate_required(duplicate_action):
            self.add_error('duplicate_action', ValidationMessages.REQUIRED)
        elif duplicate_action not in ['skip', 'overwrite', 'insert_only']:
            self.add_error('duplicate_action', "Phương thức xử lý trùng lặp không hợp lệ.")
            
        return self.result
