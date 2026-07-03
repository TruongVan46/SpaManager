# services/system_refresh_service.py
from extensions import db
from core.cache import dashboard_cache
from core.logger import app_logger

class SystemRefreshService:
    @staticmethod
    def after_restore():
        """
        Refresh the entire system state after restoring the database.
        This includes clearing all caches, closing current sessions,
        and disposing of the database engine to prevent stale connections.
        """
        try:
            # 1. Clear Caches
            # Clear Dashboard Cache
            dashboard_cache.clear()
            app_logger.info("Cleared Dashboard Cache.", module="SYSTEM")
            
            # Clear Statistics Cache (Placeholder if implemented later)
            # Clear Search Index Cache (Placeholder if implemented later)
            # Clear Backup Cache (Placeholder if implemented later)
            
            # 2. Reset SQLAlchemy database connection and session state
            # This invalidates the identity map and discards any connection pool caches.
            db.session.remove()
            db.session.close()
            db.engine.dispose()
            app_logger.info("Database session and connection pool reset successfully.", module="SYSTEM")
            
            return True
        except Exception as e:
            app_logger.error(f"Error during system refresh after restore: {str(e)}", module="SYSTEM", exc_info=True)
            return False
