import json
import re

from models.activity_log import ActivityLog

SENSITIVE_KEYS = {
    "password",
    "confirm_password",
    "old_password",
    "new_password",
    "password_hash",
    "secret",
    "token",
    "csrf",
    "csrf_token",
    "session",
    "cookie",
    "database_url",
    "oauth",
    "api_key",
}

SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)\b(" + "|".join(sorted(SENSITIVE_KEYS)) + r")\b\s*[:=]\s*([^,;\s}]+)"
)


def normalize_activity_action(action):
    if action is None:
        return ""
    normalized = str(action).strip()
    if not normalized:
        return ""
    return normalized.upper().replace(" ", "_").replace("-", "_")


def normalize_activity_severity(severity):
    if severity is None:
        return "INFO"
    normalized = str(severity).strip()
    return normalized.upper() if normalized else "INFO"


def sanitize_activity_log_value(value, max_length=2000):
    if value is None:
        return None

    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SENSITIVE_KEYS:
                sanitized[key_text] = "***REDACTED***"
            else:
                sanitized[key_text] = sanitize_activity_log_value(item, max_length=max_length)
        rendered = json.dumps(sanitized, ensure_ascii=False, default=str)
        return rendered[:max_length]

    if isinstance(value, (list, tuple, set)):
        rendered = json.dumps([sanitize_activity_log_value(item, max_length=max_length) for item in value], ensure_ascii=False, default=str)
        return rendered[:max_length]

    text = str(value)
    text = SENSITIVE_VALUE_PATTERN.sub(lambda match: f"{match.group(1)}=***REDACTED***", text)
    text = re.sub(r"(?i)(csrf[_-]?token|session(?:_id)?|oauth[_-]?token|api[_-]?key)\s*[:=]\s*([^,;\s}]+)", r"\1=***REDACTED***", text)
    return text[:max_length]


def build_activity_log_entry(module, action, description, reference_id=None, severity="INFO", user_id=None):
    return ActivityLog(
        module=module,
        action=normalize_activity_action(action),
        severity=normalize_activity_severity(severity),
        description=sanitize_activity_log_value(description),
        reference_id=reference_id,
        user_id=user_id,
    )
