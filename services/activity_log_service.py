from datetime import datetime
from sqlalchemy.orm import Session
from core.logger import app_logger

from extensions import db
from models.activity_log import ActivityLog


class ActivityLogService:
    """Service dedicated to managing, writing, and querying activity logs."""

    # Severity Constants
    SEVERITY_INFO = 'INFO'
    SEVERITY_SUCCESS = 'SUCCESS'
    SEVERITY_WARNING = 'WARNING'
    SEVERITY_ERROR = 'ERROR'

    # Action Constants
    ACTION_CREATE = 'CREATE'
    ACTION_UPDATE = 'UPDATE'
    ACTION_DELETE = 'DELETE'
    ACTION_BACKUP = 'BACKUP'
    ACTION_RESTORE = 'RESTORE'
    ACTION_IMPORT = 'IMPORT'
    ACTION_EXPORT = 'EXPORT'
    ACTION_STATUS_CHANGE = 'STATUS_CHANGE'
    ACTION_LOGIN = 'LOGIN'
    ACTION_LOGOUT = 'LOGOUT'
    ACTION_CUSTOM = 'CUSTOM'

    # Module Constants
    MODULE_CUSTOMER = 'Customer'
    MODULE_SERVICE = 'Service'
    MODULE_APPOINTMENT = 'Appointment'
    MODULE_INVOICE = 'Invoice'
    MODULE_STATISTICS = 'Statistics'
    MODULE_DASHBOARD = 'Dashboard'
    MODULE_SETTINGS = 'Settings'
    MODULE_SYSTEM = 'System'

    @staticmethod
    def write_log(module, action, description, reference_id=None, severity=SEVERITY_INFO):
        """
        Write a new activity log entry.
        This writes to the database using an independent session to ensure that
        log failures do not affect the main transaction, and log commits do not
        unintentionally commit the main transaction.
        """
        try:
            # Use an independent session to ensure log safety
            with Session(db.engine) as session:
                log_entry = ActivityLog(
                    module=module,
                    action=action,
                    description=description,
                    reference_id=reference_id,
                    severity=severity,
                    created_at=datetime.utcnow()
                )
                session.add(log_entry)
                session.commit()
                return True
        except Exception as e:
            # Prevent logging failure from affecting the main business logic
            app_logger.error(f"Failed to write activity log: {e}", module="ACTIVITY_LOG", exc_info=True)
            return False

    @staticmethod
    def log_create(module, description, reference_id=None, severity=SEVERITY_SUCCESS):
        """Log a creation action."""
        return ActivityLogService.write_log(
            module=module,
            action=ActivityLogService.ACTION_CREATE,
            description=description,
            reference_id=reference_id,
            severity=severity
        )

    @staticmethod
    def log_update(module, description, reference_id=None, severity=SEVERITY_SUCCESS):
        """Log an update action."""
        return ActivityLogService.write_log(
            module=module,
            action=ActivityLogService.ACTION_UPDATE,
            description=description,
            reference_id=reference_id,
            severity=severity
        )

    @staticmethod
    def log_delete(module, description, reference_id=None, severity=SEVERITY_SUCCESS):
        """Log a deletion action."""
        return ActivityLogService.write_log(
            module=module,
            action=ActivityLogService.ACTION_DELETE,
            description=description,
            reference_id=reference_id,
            severity=severity
        )

    @staticmethod
    def log_action(module, action, description, reference_id=None, severity=SEVERITY_INFO):
        """Log a generic action."""
        return ActivityLogService.write_log(
            module=module,
            action=action,
            description=description,
            reference_id=reference_id,
            severity=severity
        )

    # camelCase aliases to provide clear and reusable options for API calls as requested
    logCreate = log_create
    logUpdate = log_update
    logDelete = log_delete
    logAction = log_action

    @staticmethod
    def get_all():
        """Retrieve all activity logs sorted by creation time descending."""
        return ActivityLog.query.order_by(ActivityLog.created_at.desc()).all()

    @staticmethod
    def get_by_module(module):
        """Retrieve activity logs filtered by module."""
        return ActivityLog.query.filter_by(module=module).order_by(ActivityLog.created_at.desc()).all()

    @staticmethod
    def get_by_reference(module, reference_id):
        """Retrieve activity logs filtered by module and reference ID."""
        return ActivityLog.query.filter_by(
            module=module,
            reference_id=reference_id
        ).order_by(ActivityLog.created_at.desc()).all()

    @staticmethod
    def get_filtered_logs(page=1, per_page=10, module=None, action=None, severity=None, 
                          search_query=None, time_range=None, from_date=None, to_date=None, 
                          sort_by='newest'):
        """
        Retrieve paginated activity logs with advanced filtering, searching, and sorting.
        """
        query = ActivityLog.query
        
        # Search query (description, module, action)
        if search_query:
            query = query.filter(
                (ActivityLog.description.ilike(f'%{search_query}%')) |
                (ActivityLog.module.ilike(f'%{search_query}%')) |
                (ActivityLog.action.ilike(f'%{search_query}%'))
            )
            
        # Filter Module
        if module and module != 'Tất cả':
            query = query.filter(ActivityLog.module == module)
            
        # Filter Action
        if action and action != 'Tất cả':
            query = query.filter(ActivityLog.action == action)
            
        # Filter Severity
        if severity and severity != 'Tất cả':
            query = query.filter(ActivityLog.severity == severity)

        # Time range filter (Vietnamese GMT+7 converted to UTC)
        from datetime import timedelta
        utc_now = datetime.utcnow()
        local_now = utc_now + timedelta(hours=7)
        local_today_start = datetime(local_now.year, local_now.month, local_now.day)
        local_today_end = local_today_start + timedelta(days=1) - timedelta(microseconds=1)
        
        start_dt = None
        end_dt = None
        
        if time_range == 'today':
            start_dt = local_today_start
            end_dt = local_today_end
        elif time_range == '7_days':
            start_dt = local_today_start - timedelta(days=6)
            end_dt = local_today_end
        elif time_range == '30_days':
            start_dt = local_today_start - timedelta(days=29)
            end_dt = local_today_end
        elif time_range == 'this_month':
            start_dt = datetime(local_now.year, local_now.month, 1)
            end_dt = local_today_end
        elif time_range == 'custom':
            if from_date:
                try:
                    start_dt = datetime.strptime(from_date, '%Y-%m-%d')
                except ValueError:
                    pass
            if to_date:
                try:
                    end_dt = datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1) - timedelta(microseconds=1)
                except ValueError:
                    pass
                    
        if start_dt:
            utc_start = start_dt - timedelta(hours=7)
            query = query.filter(ActivityLog.created_at >= utc_start)
        if end_dt:
            utc_end = end_dt - timedelta(hours=7)
            query = query.filter(ActivityLog.created_at <= utc_end)

        # Sorting
        if sort_by == 'oldest':
            query = query.order_by(ActivityLog.created_at.asc())
        else:
            query = query.order_by(ActivityLog.created_at.desc())
            
        return query.paginate(page=page, per_page=per_page, error_out=False)

