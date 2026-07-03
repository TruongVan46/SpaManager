# validators/rules/date.py
from datetime import datetime

def validate_date(value, format="%Y-%m-%d"):
    if not value:
        return True  # Optional field validation
    if isinstance(value, datetime):
        return True
    try:
        datetime.strptime(str(value).strip(), format)
        return True
    except (ValueError, TypeError):
        return False
