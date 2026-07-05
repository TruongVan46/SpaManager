# config.py - SpaManager Project
import os
from datetime import timedelta
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))

# Load environment variables from .env file at the project root
load_dotenv(os.path.join(basedir, '.env'))

class BaseConfig:
    """
    Base configuration containing settings common to all environments.
    """
    # Application identity
    APP_NAME = os.getenv("APP_NAME", "SpaManager")
    APP_VERSION = os.getenv("APP_VERSION", "5.5.0")
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Ho_Chi_Minh")

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

    # Persistent media storage
    PERSISTENT_ROOT = os.getenv("PERSISTENT_ROOT") or os.path.join(basedir, "database")
    BACKUP_FOLDER = os.getenv("BACKUP_FOLDER") or os.path.join(PERSISTENT_ROOT, "backup")
    UPLOAD_ROOT = os.getenv("UPLOAD_ROOT") or os.path.join(PERSISTENT_ROOT, "uploads")
    LOGO_UPLOAD_FOLDER = os.getenv("LOGO_UPLOAD_FOLDER") or os.path.join(UPLOAD_ROOT, "logos")
    AVATAR_UPLOAD_FOLDER = os.getenv("AVATAR_UPLOAD_FOLDER") or os.path.join(UPLOAD_ROOT, "avatars")


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

    # Local SQLite fallback
    SQLALCHEMY_DATABASE_URI = (
        os.getenv("DATABASE_URL") or 
        os.getenv("SQLALCHEMY_DATABASE_URI") or 
        ("sqlite:///" + os.path.join(basedir, 'database', 'spa.db').replace('\\', '/'))
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
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")


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
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")

    def __init__(self):
        # In python-dotenv or environment variables, SECRET_KEY must be defined
        self.SECRET_KEY = os.getenv("SECRET_KEY")
        if not self.SECRET_KEY:
            raise RuntimeError("SECRET_KEY must be configured in Production.")

        self.SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
        if not self.SQLALCHEMY_DATABASE_URI:
            raise RuntimeError("DATABASE_URL must be configured in Production.")

        self.DEFAULT_OWNER_USERNAME = os.getenv("DEFAULT_OWNER_USERNAME", "owner")
        self.DEFAULT_OWNER_EMAIL = os.getenv("DEFAULT_OWNER_EMAIL", "")
        self.DEFAULT_OWNER_PASSWORD = os.getenv("DEFAULT_OWNER_PASSWORD")
        if not self.DEFAULT_OWNER_PASSWORD:
            raise RuntimeError("DEFAULT_OWNER_PASSWORD must be configured in Production.")
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
    env_name = os.getenv("APP_ENV", "development").lower()
    config_cls = config_by_name.get(env_name, DevelopmentConfig)
    return config_cls()

# Instantiate active config to preserve Config import usage
Config = get_active_config()
