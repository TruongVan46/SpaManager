# validators/backup_validator.py
from validators.base_validator import BaseValidator
from validators.rules import validate_length


class BackupValidator(BaseValidator):
    def validate(self, data):
        self.result.field_errors.clear()
        self.result.success = True
        
        notes = data.get('notes', '')
        if notes and not validate_length(notes, max_len=255):
            self.add_error('notes', "Ghi chú không được vượt quá 255 ký tự.")
            
        return self.result
