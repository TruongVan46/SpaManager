# validators/rules/number.py

def validate_number(value, min_val=None, max_val=None):
    if value is None or value == "":
        return True  # Optional field validation
    try:
        val = float(value)
        if min_val is not None and val < min_val:
            return False
        if max_val is not None and val > max_val:
            return False
        return True
    except (ValueError, TypeError):
        return False
