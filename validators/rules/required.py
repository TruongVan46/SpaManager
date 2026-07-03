# validators/rules/required.py

def validate_required(value):
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True
