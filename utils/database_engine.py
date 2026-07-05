from urllib.parse import urlparse


def get_database_engine(database_url):
    """Return the logical database engine name from a SQLAlchemy URL."""
    if not database_url:
        return "unknown"

    normalized_url = str(database_url).strip()
    if normalized_url.startswith("postgres://"):
        normalized_url = "postgresql://" + normalized_url[len("postgres://"):]

    parsed = urlparse(normalized_url)
    scheme = (parsed.scheme or "").lower()
    if scheme in {"sqlite", "postgresql", "postgres"}:
        return "postgresql" if scheme == "postgres" else scheme
    return "unknown"


def is_sqlite_database(database_url):
    return get_database_engine(database_url) == "sqlite"


def is_postgresql_database(database_url):
    return get_database_engine(database_url) == "postgresql"


def get_postgresql_backup_center_message():
    return (
        "Tính năng sao lưu/khôi phục của SpaManager đang tạm khóa trong chế độ PostgreSQL. "
        "Vui lòng dùng quy trình sao lưu PostgreSQL theo runbook thay vì Backup Center."
    )


def get_postgresql_restore_guard_message():
    return (
        "Khôi phục từ bản sao lưu SQLite không khả dụng khi hệ thống đang chạy PostgreSQL. "
        "Vui lòng theo runbook PostgreSQL hoặc dùng dữ liệu đã sao lưu đúng engine."
    )
