# validators/rules/regex.py
import re

def validate_regex(value, pattern):
    if not value:
        return True  # Optional field validation
    return bool(re.match(pattern, str(value)))
