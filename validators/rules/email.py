# validators/rules/email.py
import re

EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

def validate_email(value):
    if not value:
        return True  # Optional field validation
    return bool(re.match(EMAIL_REGEX, str(value).strip()))
