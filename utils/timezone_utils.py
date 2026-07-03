import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_APP_TIMEZONE = "Asia/Ho_Chi_Minh"


def get_app_timezone(timezone_name=None):
    name = timezone_name or os.getenv("APP_TIMEZONE", DEFAULT_APP_TIMEZONE)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        if name in {DEFAULT_APP_TIMEZONE, "Asia/Saigon", "Vietnam"}:
            return timezone(timedelta(hours=7), name)
        raise ValueError(f"Invalid application timezone: {name}") from exc


def parse_datetime_value(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(cleaned, fmt)
                    if fmt == "%Y-%m-%d":
                        return parsed
                    return parsed
                except ValueError:
                    continue
    raise ValueError(f"Unsupported datetime value: {value!r}")


def utc_now():
    return datetime.utcnow()


def local_now(now_utc=None):
    tz = get_app_timezone()
    if now_utc is None:
        return datetime.now(tz)
    return to_local_datetime(now_utc, assume_utc=True)


def local_now_naive(now_utc=None):
    return local_now(now_utc).replace(tzinfo=None)


def local_today(now_utc=None):
    return local_now(now_utc).date()


def local_day_bounds(target_date=None):
    if target_date is None:
        target_date = local_today()
    if isinstance(target_date, str):
        target_date = parse_datetime_value(target_date).date()
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    start_dt = datetime.combine(target_date, time.min)
    end_dt = datetime.combine(target_date, time.max)
    return start_dt, end_dt


def local_day_bounds_utc(target_date=None):
    start_local, end_local = local_day_bounds(target_date)
    start_utc = to_utc_datetime(start_local, assume_local=True)
    end_utc = to_utc_datetime(end_local, assume_local=True)
    return start_utc.replace(tzinfo=None), end_utc.replace(tzinfo=None)


def to_local_datetime(value, assume_utc=True):
    dt = parse_datetime_value(value)
    if dt is None:
        return None

    tz = get_app_timezone()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc if assume_utc else tz)
    return dt.astimezone(tz)


def to_local_naive_datetime(value, assume_utc=True):
    local_dt = to_local_datetime(value, assume_utc=assume_utc)
    return local_dt.replace(tzinfo=None) if local_dt else None


def to_utc_datetime(value, assume_local=True):
    dt = parse_datetime_value(value)
    if dt is None:
        return None

    tz = get_app_timezone()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz if assume_local else timezone.utc)
    return dt.astimezone(timezone.utc)


def format_local_datetime(value, assume_utc=True, fmt="%d/%m/%Y %H:%M"):
    local_dt = to_local_datetime(value, assume_utc=assume_utc)
    return local_dt.strftime(fmt) if local_dt else "N/A"
