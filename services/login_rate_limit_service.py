import threading
import time
from dataclasses import dataclass

from flask import current_app, has_app_context


DEFAULT_MAX_FAILED_ATTEMPTS = 5
DEFAULT_FAILURE_WINDOW_SECONDS = 600
DEFAULT_LOCKOUT_SECONDS = 600

_LOGIN_ATTEMPTS = {}
_LOGIN_ATTEMPTS_LOCK = threading.RLock()


@dataclass(frozen=True)
class LoginRateLimitResult:
    allowed: bool
    remaining_attempts: int
    retry_after_seconds: int = 0
    locked_until: float | None = None
    reason: str = "allowed"


def _coerce_int(value, default):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _settings():
    if has_app_context():
        config = current_app.config
        return {
            "max_failed_attempts": _coerce_int(
                config.get("LOGIN_MAX_FAILED_ATTEMPTS", DEFAULT_MAX_FAILED_ATTEMPTS),
                DEFAULT_MAX_FAILED_ATTEMPTS,
            ),
            "failure_window_seconds": _coerce_int(
                config.get("LOGIN_FAILURE_WINDOW_SECONDS", DEFAULT_FAILURE_WINDOW_SECONDS),
                DEFAULT_FAILURE_WINDOW_SECONDS,
            ),
            "lockout_seconds": _coerce_int(
                config.get("LOGIN_LOCKOUT_SECONDS", DEFAULT_LOCKOUT_SECONDS),
                DEFAULT_LOCKOUT_SECONDS,
            ),
        }

    return {
        "max_failed_attempts": DEFAULT_MAX_FAILED_ATTEMPTS,
        "failure_window_seconds": DEFAULT_FAILURE_WINDOW_SECONDS,
        "lockout_seconds": DEFAULT_LOCKOUT_SECONDS,
    }


def normalize_login_identifier(username):
    return (username or "").strip().lower()


def get_request_ip(request_obj=None):
    request_source = request_obj
    if request_source is None and has_app_context():
        from flask import request as flask_request

        request_source = flask_request

    if request_source is None:
        return "unknown"

    forwarded_for = request_source.headers.get("X-Forwarded-For", "") if hasattr(request_source, "headers") else ""
    if forwarded_for:
        candidate = forwarded_for.split(",")[0].strip()
        if candidate:
            return candidate

    remote_addr = getattr(request_source, "remote_addr", None)
    return remote_addr or "unknown"


def _entry_key(username, request_ip):
    normalized_username = normalize_login_identifier(username) or "<empty>"
    normalized_ip = (request_ip or "unknown").strip() or "unknown"
    return f"{normalized_username}|{normalized_ip}"


def _now(now_value=None):
    return time.time() if now_value is None else float(now_value)


def _prune_entry(entry, now_value, failure_window_seconds):
    cutoff = now_value - failure_window_seconds
    entry["failures"] = [timestamp for timestamp in entry.get("failures", []) if timestamp >= cutoff]
    locked_until = entry.get("locked_until")
    if locked_until is not None and locked_until <= now_value:
        entry["locked_until"] = None
    return entry


def check_login_allowed(username, request_ip, now_value=None):
    settings = _settings()
    current_time = _now(now_value)
    key = _entry_key(username, request_ip)

    with _LOGIN_ATTEMPTS_LOCK:
        entry = _LOGIN_ATTEMPTS.get(key)
        if not entry:
            return LoginRateLimitResult(
                allowed=True,
                remaining_attempts=settings["max_failed_attempts"],
            )

        entry = _prune_entry(entry, current_time, settings["failure_window_seconds"])
        failures_count = len(entry["failures"])
        locked_until = entry.get("locked_until")

        if locked_until is not None and locked_until > current_time:
            return LoginRateLimitResult(
                allowed=False,
                remaining_attempts=0,
                retry_after_seconds=max(1, int(round(locked_until - current_time))),
                locked_until=locked_until,
                reason="locked",
            )

        if failures_count >= settings["max_failed_attempts"] and settings["lockout_seconds"] > 0:
            entry["locked_until"] = current_time + settings["lockout_seconds"]
            _LOGIN_ATTEMPTS[key] = entry
            return LoginRateLimitResult(
                allowed=False,
                remaining_attempts=0,
                retry_after_seconds=settings["lockout_seconds"],
                locked_until=entry["locked_until"],
                reason="threshold_exceeded",
            )

        _LOGIN_ATTEMPTS[key] = entry
        return LoginRateLimitResult(
            allowed=True,
            remaining_attempts=max(0, settings["max_failed_attempts"] - failures_count),
        )


def record_login_failure(username, request_ip, now_value=None):
    settings = _settings()
    current_time = _now(now_value)
    key = _entry_key(username, request_ip)

    with _LOGIN_ATTEMPTS_LOCK:
        entry = _LOGIN_ATTEMPTS.get(key, {"failures": [], "locked_until": None})
        entry = _prune_entry(entry, current_time, settings["failure_window_seconds"])
        entry.setdefault("failures", []).append(current_time)
        if len(entry["failures"]) >= settings["max_failed_attempts"] and settings["lockout_seconds"] > 0:
            entry["locked_until"] = current_time + settings["lockout_seconds"]
        _LOGIN_ATTEMPTS[key] = entry


def record_login_success(username, request_ip):
    reset_login_attempts(username, request_ip)


def reset_login_attempts(username, request_ip):
    key = _entry_key(username, request_ip)
    with _LOGIN_ATTEMPTS_LOCK:
        _LOGIN_ATTEMPTS.pop(key, None)


def reset_all_login_attempts():
    with _LOGIN_ATTEMPTS_LOCK:
        _LOGIN_ATTEMPTS.clear()
