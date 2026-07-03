# validators/rules/length.py

def validate_length(value, min_len=None, max_len=None):
    if value is None:
        return True  # Optional field validation
    length = len(str(value))
    if min_len is not None and length < min_len:
        return False
    if max_len is not None and length > max_len:
        return False
    return True
