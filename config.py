# config.py - SpaManager Project
import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # Khóa bảo mật của Flask
    SECRET_KEY = "spa_manager_2026_secret_key"

    # SQLite Database
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(basedir, 'database', 'spa.db').replace('\\', '/')

    # Tắt theo dõi thay đổi của SQLAlchemy để tăng hiệu năng
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session lifetime
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)

    # Static Assets Caching Header (1 year cache for maximum browser load performance)
    SEND_FILE_MAX_AGE_DEFAULT = timedelta(days=365)

    # Logging Configurations
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_DIR = os.path.join(basedir, 'logs')
    LOG_ROTATION_SIZE = 5 * 1024 * 1024 # 5 MB
    LOG_BACKUP_COUNT = 5