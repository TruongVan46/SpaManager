# core/logger.py
import logging
import os
from logging.handlers import RotatingFileHandler
from config import Config

# Color support for Development mode console logs
COLOR_CODES = {
    'DEBUG': '\033[94m',    # Blue
    'INFO': '\033[92m',     # Green
    'WARNING': '\033[93m',  # Yellow
    'ERROR': '\033[91m',    # Red
    'CRITICAL': '\033[95m', # Magenta
    'ENDC': '\033[0m'
}

class ColorConsoleFormatter(logging.Formatter):
    def format(self, record):
        dt = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        level = record.levelname
        module = getattr(record, 'module_name', 'SYSTEM')
        msg = record.getMessage()
        color = COLOR_CODES.get(level, '')
        endc = COLOR_CODES['ENDC'] if color else ''
        
        trace = ""
        if record.exc_info:
            trace = "\n" + self.formatException(record.exc_info)
            
        return f"{color}[{dt}] {level} [{module}] {msg}{trace}{endc}"

class FileLogFormatter(logging.Formatter):
    def format(self, record):
        dt = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        level = record.levelname
        module = getattr(record, 'module_name', 'SYSTEM')
        msg = record.getMessage()
        
        trace = ""
        if record.exc_info:
            trace = "\n" + self.formatException(record.exc_info)
            
        return f"[{dt}]\n{level}\n{module}\n{msg}{trace}"

class AppLogger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(AppLogger, cls).__new__(cls, *args, **kwargs)
            cls._instance._initialized = False
        return cls._instance

    def init_app(self, app=None):
        if self._initialized:
            return
        self._initialized = True

        # Resolve logs directory path
        log_dir = Config.LOG_DIR
        os.makedirs(log_dir, exist_ok=True)
        
        # Log Level
        log_level_str = Config.LOG_LEVEL.upper()
        log_level = getattr(logging, log_level_str, logging.INFO)
        max_bytes = Config.LOG_ROTATION_SIZE
        backup_count = Config.LOG_BACKUP_COUNT

        # Base App Logger Setup
        self.logger = logging.getLogger('spamanager_app')
        self.logger.setLevel(log_level)
        self.logger.propagate = False

        file_formatter = FileLogFormatter()

        # Clear existing handlers to prevent duplicate entries
        self.logger.handlers = []

        # 1. Application Log Handler
        app_handler = RotatingFileHandler(
            os.path.join(log_dir, 'application.log'),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        app_handler.setLevel(log_level)
        app_handler.setFormatter(file_formatter)
        self.logger.addHandler(app_handler)

        # 2. Error Log Handler
        err_handler = RotatingFileHandler(
            os.path.join(log_dir, 'error.log'),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        err_handler.setLevel(logging.ERROR)
        err_handler.setFormatter(file_formatter)
        self.logger.addHandler(err_handler)

        # 3. Security Logger Setup
        self.sec_logger = logging.getLogger('spamanager_security')
        self.sec_logger.setLevel(logging.INFO)
        self.sec_logger.propagate = False
        self.sec_logger.handlers = []
        
        sec_handler = RotatingFileHandler(
            os.path.join(log_dir, 'security.log'),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        sec_handler.setLevel(logging.INFO)
        sec_handler.setFormatter(file_formatter)
        self.sec_logger.addHandler(sec_handler)

        # 4. Console Handler (for Development color logging)
        is_dev = os.environ.get('FLASK_ENV') == 'development' or (app and app.debug)
        if is_dev:
            # Enable ANSI colors for Windows terminals if needed
            if os.name == 'nt':
                try:
                    import colorama
                    colorama.init()
                except ImportError:
                    pass

            console_handler = logging.StreamHandler()
            console_handler.setFormatter(ColorConsoleFormatter())
            self.logger.addHandler(console_handler)
            
            sec_console_handler = logging.StreamHandler()
            sec_console_handler.setFormatter(ColorConsoleFormatter())
            self.sec_logger.addHandler(sec_console_handler)

    def debug(self, msg, module="SYSTEM"):
        self.logger.debug(msg, extra={"module_name": module})

    def info(self, msg, module="SYSTEM"):
        self.logger.info(msg, extra={"module_name": module})

    def warning(self, msg, module="SYSTEM"):
        self.logger.warning(msg, extra={"module_name": module})

    def error(self, msg, module="SYSTEM", exc_info=None):
        self.logger.error(msg, exc_info=exc_info, extra={"module_name": module})

    def critical(self, msg, module="SYSTEM", exc_info=None):
        self.logger.critical(msg, exc_info=exc_info, extra={"module_name": module})

    def security(self, msg, module="SECURITY"):
        self.sec_logger.info(msg, extra={"module_name": module})

    def audit(self, msg, module="AUDIT"):
        self.info(msg, module=module)

# Expose global singleton instance
app_logger = AppLogger()
