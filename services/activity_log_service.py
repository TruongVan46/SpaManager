from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from core.logger import app_logger

from extensions import db
from models.activity_log import ActivityLog
from services.auth_service import AuthService
from models.user import User
from core.activity_log_utils import (
    build_activity_log_entry,
    normalize_activity_action,
    normalize_activity_severity,
)
from utils.timezone_utils import local_day_bounds_utc, local_today, parse_datetime_value, utc_now


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
    def write_log(module, action, description, reference_id=None, severity=SEVERITY_INFO, session_override=None, commit=True, user_id_override=None):
        """
        Write a new activity log entry.
        This writes to the database using an independent session to ensure that
        log failures do not affect the main transaction, and log commits do not
        unintentionally commit the main transaction.
        """
        try:
            current_user = AuthService.get_current_user()
            log_entry = build_activity_log_entry(
                module=module,
                action=normalize_activity_action(action),
                description=description,
                reference_id=reference_id,
                severity=normalize_activity_severity(severity),
                user_id=user_id_override if user_id_override is not None else (current_user.id if current_user else None)
            )
            log_entry.created_at = utc_now()
            if session_override is not None:
                session_override.add(log_entry)
                if commit:
                    session_override.commit()
                return True

            # Use an independent session to ensure log safety
            with Session(db.engine) as session:
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
    def get_actor_options():
        """Return distinct users that appear in activity logs."""
        from services.workspace_service import WorkspaceService
        from models.workspace import WorkspaceMember
        wid = WorkspaceService.get_current_workspace_id()
        if wid is None:
            return []

        workspace_user_ids = db.session.query(WorkspaceMember.user_id).filter(
            WorkspaceMember.workspace_id == wid,
            WorkspaceMember.status == 'active'
        )

        return (
            User.query.join(ActivityLog, ActivityLog.user_id == User.id)
            .filter(User.id.in_(workspace_user_ids))
            .distinct()
            .order_by(User.username.asc())
            .all()
        )

    @staticmethod
    def get_filtered_logs(page=1, per_page=10, module=None, action=None, severity=None, 
                          search_query=None, actor=None, time_range=None, from_date=None, to_date=None, 
                          sort_by='newest'):
        """
        Retrieve paginated activity logs with advanced filtering, searching, and sorting.
        """
        from services.workspace_service import WorkspaceService
        from models.workspace import WorkspaceMember

        wid = WorkspaceService.get_current_workspace_id()
        if wid is None:
            query = ActivityLog.query.filter(ActivityLog.id == -1)
        else:
            workspace_user_ids = db.session.query(WorkspaceMember.user_id).filter(
                WorkspaceMember.workspace_id == wid,
                WorkspaceMember.status == 'active'
            )

            query = ActivityLog.query.outerjoin(User, ActivityLog.user_id == User.id).filter(
                ActivityLog.user_id.in_(workspace_user_ids)
            )
        
        # Search query (description, module, action)
        if search_query:
            query = query.filter(
                (ActivityLog.description.ilike(f'%{search_query}%')) |
                (ActivityLog.module.ilike(f'%{search_query}%')) |
                (ActivityLog.action.ilike(f'%{search_query}%')) |
                (User.username.ilike(f'%{search_query}%')) |
                (User.full_name.ilike(f'%{search_query}%'))
            )

        if actor:
            actor_query = actor.strip()
            if actor_query and actor_query != 'Tất cả':
                query = query.filter(
                    (User.username.ilike(f'%{actor_query}%')) |
                    (User.full_name.ilike(f'%{actor_query}%'))
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

        # Time range filter (local time converted back to stored UTC)
        local_today_start_utc, local_today_end_utc = local_day_bounds_utc(local_today())
        
        start_dt = None
        end_dt = None
        
        if time_range == 'today':
            start_dt = local_today_start_utc
            end_dt = local_today_end_utc
        elif time_range == '7_days':
            start_dt, end_dt = local_day_bounds_utc(local_today() - timedelta(days=6))
            end_dt = local_today_end_utc
        elif time_range == '30_days':
            start_dt, end_dt = local_day_bounds_utc(local_today() - timedelta(days=29))
            end_dt = local_today_end_utc
        elif time_range == 'this_month':
            current_day = local_today()
            start_dt = local_day_bounds_utc(date(current_day.year, current_day.month, 1))[0]
            end_dt = local_today_end_utc
        elif time_range == 'custom':
            if from_date:
                try:
                    parsed_from = parse_datetime_value(from_date)
                    if parsed_from:
                        start_dt = local_day_bounds_utc(parsed_from.date())[0]
                except (AttributeError, ValueError):
                    pass
            if to_date:
                try:
                    parsed_to = parse_datetime_value(to_date)
                    if parsed_to:
                        end_dt = local_day_bounds_utc(parsed_to.date())[1]
                except (AttributeError, ValueError):
                    pass
                    
        if start_dt:
            query = query.filter(ActivityLog.created_at >= start_dt)
        if end_dt:
            query = query.filter(ActivityLog.created_at <= end_dt)

        # Sorting
        if sort_by == 'oldest':
            query = query.order_by(ActivityLog.created_at.asc())
        else:
            query = query.order_by(ActivityLog.created_at.desc())
            
        return query.paginate(page=page, per_page=per_page, error_out=False)
