# validators/rules/phone.py
import re

# Standard phone number format: exactly 10 digits, starting with 0 (and second digit not 0)
PHONE_REGEX = r'^0[1-9]\d{8}$'

def validate_phone(value):
    if not value:
        return True  # Optional field validation
    cleaned = re.sub(r'[\s\-().+]+', '', str(value).strip())
    return bool(re.match(PHONE_REGEX, cleaned))
