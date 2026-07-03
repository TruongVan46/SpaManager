# validators/profile_validator.py
import os
from validators.base_validator import BaseValidator
from validators.messages import ValidationMessages
from validators.rules import validate_required


class ProfileValidator(BaseValidator):
    def validate(self, data):
        self.result.field_errors.clear()
        self.result.success = True
        
        full_name = data.get('full_name', '')
        avatar_file = data.get('avatar_file')
        
        # 1. Full Name required
        if not validate_required(full_name):
            self.add_error('full_name', ValidationMessages.REQUIRED)
            
        # 2. Avatar file validation
        if avatar_file and hasattr(avatar_file, 'filename') and avatar_file.filename:
            filename = avatar_file.filename
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png']:
                self.add_error('avatar_file', "Định dạng file không hợp lệ. Chỉ chấp nhận JPG, JPEG, PNG.")
            else:
                try:
                    avatar_file.seek(0, 2)
                    size = avatar_file.tell()
                    avatar_file.seek(0)
                    if size > 2 * 1024 * 1024:
                        self.add_error('avatar_file', "Kích thước ảnh vượt quá giới hạn 2MB.")
                except Exception:
                    pass
                    
        return self.result
