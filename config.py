# config.py - SpaManager Project
import os
import sys
from datetime import timedelta
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

basedir = os.path.abspath(os.path.dirname(__file__))

# Load environment variables from .env file at the project root
load_dotenv(os.path.join(basedir, '.env'))


def _normalize_database_url(database_url):
    if not database_url:
        return database_url
    if database_url.startswith("postgres://"):
        return "postgresql://" + database_url[len("postgres://"):]
    return database_url


def _parse_bool_env(value, default=False):
    if value is None:
        return default
    normalized_value = str(value).strip().lower()
    if not normalized_value:
        return False
    return normalized_value in {"1", "true", "yes", "on", "y", "t"}


def is_permanent_purge_ui_enabled(value):
    return value is True


def is_permanent_purge_execution_enabled(value):
    return value is True


def _is_test_process():
    return (
        os.getenv("SPAMANAGER_TEST_PROCESS") == "1"
        or any("unittest" in str(arg).lower() or "pytest" in str(arg).lower() for arg in sys.argv)
        or os.getenv("PYTEST_CURRENT_TEST") is not None
    )


def _safe_test_database_url():
    database_url = _normalize_database_url(os.getenv("TEST_DATABASE_URL"))
    if not database_url:
        raise RuntimeError("Test database safety guard: TEST_DATABASE_URL must be configured.")
    try:
        parsed_url = make_url(database_url)
    except Exception as exc:
        raise RuntimeError("Test database safety guard: TEST_DATABASE_URL is invalid.") from exc
    dialect = parsed_url.get_backend_name()
    if dialect == "sqlite":
        return database_url
    if dialect == "postgresql":
        database_name = (parsed_url.database or "").lower()
        if os.getenv("SPAMANAGER_ALLOW_POSTGRES_TESTS") != "1" or not database_name.endswith("_test"):
            raise RuntimeError("Test database safety guard: PostgreSQL requires explicit opt-in and a database name ending in _test.")
        return database_url
    raise RuntimeError("Test database safety guard: only SQLite is allowed by default.")

class BaseConfig:
    """
    Base configuration containing settings common to all environments.
    """
    # Application identity
    APP_NAME = os.getenv("APP_NAME", "SpaManager")
    APP_VERSION = os.getenv("APP_VERSION", "6.6")
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Ho_Chi_Minh")
    PERMANENT_PURGE_UI_ENABLED = _parse_bool_env(os.getenv("PERMANENT_PURGE_UI_ENABLED"), False)
    PERMANENT_PURGE_EXECUTION_ENABLED = _parse_bool_env(os.getenv("PERMANENT_PURGE_EXECUTION_ENABLED"), False)

    # SQLAlchemy Configurations
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Max upload file size limit (default: 100MB)
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_SIZE", 100 * 1024 * 1024))

    # Session lifetime duration
    PERMANENT_SESSION_LIFETIME = timedelta(days=int(os.getenv("SESSION_LIFETIME_DAYS", 30)))

    # Static Assets Caching Header (default: 1 year cache for maximum performance)
    SEND_FILE_MAX_AGE_DEFAULT = timedelta(days=int(os.getenv("SEND_FILE_MAX_AGE_DAYS", 365)))

    # CSRF protection
    CSRF_ENABLED = os.getenv("CSRF_ENABLED", "1") != "0"
    CSRF_TIME_LIMIT = int(os.getenv("CSRF_TIME_LIMIT", 3600))
    CSRF_METHODS = ("POST", "PUT", "PATCH", "DELETE")
    CSRF_HEADER_NAMES = ("X-CSRFToken", "X-CSRF-Token")

    # Folders paths
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(basedir, 'static', 'uploads'))
    EXPORT_FOLDER = os.getenv("EXPORT_FOLDER", os.path.join(basedir, 'exports'))
    LOG_DIR = os.getenv("LOG_DIR", os.path.join(basedir, 'logs'))
    LOG_FOLDER = LOG_DIR  # Alias for backward compatibility

    # Logging configurations
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_ROTATION_SIZE = int(os.getenv('LOG_ROTATION_SIZE', 5 * 1024 * 1024)) # 5 MB
    LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', 5))

    # Google OAuth 2.0 Configurations
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
    GOOGLE_DISCOVERY_URL = os.getenv("GOOGLE_DISCOVERY_URL", "https://accounts.google.com/.well-known/openid-configuration")
    GOOGLE_SCOPES = os.getenv("GOOGLE_SCOPES", "openid email profile").split()

    # Login protection
    LOGIN_MAX_FAILED_ATTEMPTS = int(os.getenv("LOGIN_MAX_FAILED_ATTEMPTS", 5))
    LOGIN_FAILURE_WINDOW_SECONDS = int(os.getenv("LOGIN_FAILURE_WINDOW_SECONDS", 600))
    LOGIN_LOCKOUT_SECONDS = int(os.getenv("LOGIN_LOCKOUT_SECONDS", 600))

    # Default owner account seed settings
    DEFAULT_OWNER_USERNAME = os.getenv("DEFAULT_OWNER_USERNAME", "owner")
    DEFAULT_OWNER_PASSWORD = os.getenv("DEFAULT_OWNER_PASSWORD", "owner123")
    DEFAULT_OWNER_EMAIL = os.getenv("DEFAULT_OWNER_EMAIL", "")
    # Account bootstrap remains enabled by default. Isolated rehearsal sets this
    # explicitly before importing the application module.
    BOOTSTRAP_ACCOUNTS_ENABLED = _parse_bool_env(
        os.getenv("SPAMANAGER_BOOTSTRAP_ACCOUNTS_ENABLED"), True
    )

    # Approval owner account bootstrap settings
    APPROVAL_OWNER_USERNAME = os.getenv("APPROVAL_OWNER_USERNAME", "")
    APPROVAL_OWNER_PASSWORD = os.getenv("APPROVAL_OWNER_PASSWORD", "")
    APPROVAL_OWNER_EMAIL = os.getenv("APPROVAL_OWNER_EMAIL", "")

    # Persistent media storage
    PERSISTENT_ROOT = os.getenv("PERSISTENT_ROOT") or os.path.join(basedir, "database")
    BACKUP_FOLDER = os.getenv("BACKUP_FOLDER") or os.path.join(PERSISTENT_ROOT, "backup")
    UPLOAD_ROOT = os.getenv("UPLOAD_ROOT") or os.path.join(PERSISTENT_ROOT, "uploads")
    LOGO_UPLOAD_FOLDER = os.getenv("LOGO_UPLOAD_FOLDER") or os.path.join(UPLOAD_ROOT, "logos")
    AVATAR_UPLOAD_FOLDER = os.getenv("AVATAR_UPLOAD_FOLDER") or os.path.join(UPLOAD_ROOT, "avatars")

    def __init__(self):
        self.GOOGLE_AUTH_ENABLED = _parse_bool_env(os.getenv("GOOGLE_AUTH_ENABLED"), False)
        self.GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
        self.GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
        self.GOOGLE_ALLOWED_DOMAIN = os.getenv("GOOGLE_ALLOWED_DOMAIN", "")
        self.GOOGLE_DISCOVERY_URL = os.getenv(
            "GOOGLE_DISCOVERY_URL",
            "https://accounts.google.com/.well-known/openid-configuration",
        )
        self.GOOGLE_SCOPES = [scope for scope in os.getenv("GOOGLE_SCOPES", "openid email profile").split() if scope]

    def validate_google_oauth_config(self):
        if not getattr(self, "GOOGLE_AUTH_ENABLED", False):
            return []
        missing = []
        if not getattr(self, "GOOGLE_CLIENT_ID", ""):
            missing.append("GOOGLE_CLIENT_ID")
        if not getattr(self, "GOOGLE_CLIENT_SECRET", ""):
            missing.append("GOOGLE_CLIENT_SECRET")
        return missing


class DevelopmentConfig(BaseConfig):
    """
    Configuration for local development environment.
    """
    DEBUG = True
    TESTING = False
    
    # Development mode cookies (no HTTPS constraint for localhost)
    SESSION_COOKIE_SECURE = False
    
    # Fallback to local developer key
    SECRET_KEY = os.getenv("SECRET_KEY", "spa_manager_dev_key")

    def __init__(self):
        super().__init__()
        self.SQLITE_LEGACY_ENABLED = os.getenv("SPA_ENABLE_SQLITE_LEGACY", "0") == "1"
        self.LOCAL_POSTGRESQL_DATABASE_URL = os.getenv(
            "LOCAL_POSTGRESQL_DATABASE_URL",
            "postgresql://spamanager:spamanager_dev_password@localhost:5433/spamanager_dev",
        )
        self.LEGACY_SQLITE_DATABASE_URL = os.getenv(
            "LEGACY_SQLITE_DATABASE_URL",
            "sqlite:///" + os.path.join(basedir, 'database', 'spa.db').replace('\\', '/'),
        )

        # PostgreSQL-first local development with explicit legacy SQLite fallback
        self.SQLALCHEMY_DATABASE_URI = (
            _normalize_database_url(os.getenv("DATABASE_URL")) or
            _normalize_database_url(os.getenv("SQLALCHEMY_DATABASE_URI")) or
            (_normalize_database_url(self.LEGACY_SQLITE_DATABASE_URL) if self.SQLITE_LEGACY_ENABLED else self.LOCAL_POSTGRESQL_DATABASE_URL)
        )


class TestingConfig(BaseConfig):
    """
    Configuration for automated unit and integration tests.
    """
    DEBUG = False
    TESTING = True
    
    SESSION_COOKIE_SECURE = False
    SECRET_KEY = "spa_manager_testing_key"
    CSRF_ENABLED = True

    # SQLite in-memory database for fast test isolation
    SQLALCHEMY_DATABASE_URI = None

    def __init__(self):
        super().__init__()
        self.SQLALCHEMY_DATABASE_URI = _safe_test_database_url()


class ProductionConfig(BaseConfig):
    """
    Strict configuration for live production environment.
    """
    DEBUG = False
    TESTING = False
    CSRF_ENABLED = True

    # Production session cookie security flags (anti-session hijacking / CSRF)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Database configuration (no default SQLite fallback, must be supplied)
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(os.getenv("DATABASE_URL"))

    def __init__(self):
        super().__init__()
        # In python-dotenv or environment variables, SECRET_KEY must be defined
        self.SECRET_KEY = os.getenv("SECRET_KEY")
        if not self.SECRET_KEY:
            raise RuntimeError("SECRET_KEY must be configured in Production.")

        self.SQLALCHEMY_DATABASE_URI = _normalize_database_url(os.getenv("DATABASE_URL"))
        if not self.SQLALCHEMY_DATABASE_URI:
            raise RuntimeError("DATABASE_URL must be configured in Production.")

        self.DEFAULT_OWNER_USERNAME = os.getenv("DEFAULT_OWNER_USERNAME", "owner")
        self.DEFAULT_OWNER_EMAIL = os.getenv("DEFAULT_OWNER_EMAIL", "")
        self.DEFAULT_OWNER_PASSWORD = os.getenv("DEFAULT_OWNER_PASSWORD")
        if not self.DEFAULT_OWNER_PASSWORD:
            raise RuntimeError("DEFAULT_OWNER_PASSWORD must be configured in Production.")
        self.APPROVAL_OWNER_USERNAME = os.getenv("APPROVAL_OWNER_USERNAME", "")
        self.APPROVAL_OWNER_PASSWORD = os.getenv("APPROVAL_OWNER_PASSWORD", "")
        self.APPROVAL_OWNER_EMAIL = os.getenv("APPROVAL_OWNER_EMAIL", "")
        self.APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Ho_Chi_Minh")

        self.PERSISTENT_ROOT = os.getenv("PERSISTENT_ROOT") or "/app/database"
        self.BACKUP_FOLDER = os.getenv("BACKUP_FOLDER") or os.path.join(self.PERSISTENT_ROOT, "backup")
        self.UPLOAD_ROOT = os.getenv("UPLOAD_ROOT") or os.path.join(self.PERSISTENT_ROOT, "uploads")
        self.LOGO_UPLOAD_FOLDER = os.getenv("LOGO_UPLOAD_FOLDER") or os.path.join(self.UPLOAD_ROOT, "logos")
        self.AVATAR_UPLOAD_FOLDER = os.getenv("AVATAR_UPLOAD_FOLDER") or os.path.join(self.UPLOAD_ROOT, "avatars")


# Map configurations by environment name
config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig
}

def get_active_config():
    """
    Resolve the active configuration instance based on the APP_ENV environment variable.
    Defaults to DevelopmentConfig instance if not defined.
    """
    env_name = "testing" if _is_test_process() else os.getenv("APP_ENV", "development").lower()
    config_cls = config_by_name.get(env_name, DevelopmentConfig)
    return config_cls()

# Instantiate active config to preserve Config import usage
Config = get_active_config()
