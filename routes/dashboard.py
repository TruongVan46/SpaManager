# routes/dashboard.py
from datetime import timedelta

from flask import current_app, jsonify, render_template
from sqlalchemy import func

from core.auth.permissions import can_manage_settings
from extensions import db
from models.activity_log import ActivityLog
from models.user import User
from repositories.backup_repository import BackupRepository
from routes import dashboard_bp
from services.auth_service import AuthService
from services.backup_service import BackupService
from services.dashboard_service import DashboardService
from utils.timezone_utils import format_local_datetime, to_local_datetime, utc_now


def _build_admin_summary():
    current_user = AuthService.get_current_active_user()
    if not can_manage_settings(current_user):
        return None

    app = current_app._get_current_object()
    summary = {
        "backup": {
            "has_backup": False,
            "count": 0,
            "display_name": None,
            "friendly_time": None,
            "status": None,
            "notes": None,
            "version_db": None,
            "version_app": None,
        },
        "users": {
            "active": 0,
            "inactive": 0,
            "total": 0,
        },
        "activity": {
            "warning_count": 0,
            "error_count": 0,
            "status": "Ổn định",
            "latest_time": None,
        },
    }

    try:
        backup_entries = list((BackupRepository.load_all(app) or {}).values())
        summary["backup"]["count"] = len(backup_entries)
        if backup_entries:
            def backup_sort_key(meta):
                dt = to_local_datetime(meta.get("created_at"), assume_utc=True)
                return dt.timestamp() if dt else 0

            latest_backup = max(backup_entries, key=backup_sort_key)
            latest_dt = to_local_datetime(latest_backup.get("created_at"), assume_utc=True)
            summary["backup"].update({
                "has_backup": True,
                "display_name": latest_backup.get("display_name") or latest_backup.get("filename") or "Bản sao lưu gần nhất",
                "friendly_time": BackupService.format_friendly_time(latest_dt) if latest_dt else None,
                "status": latest_backup.get("status", "Valid"),
                "notes": latest_backup.get("notes", "-"),
                "version_db": latest_backup.get("database_version", "v1.0"),
                "version_app": latest_backup.get("app_version", f"SpaManager v{BackupService.APP_VERSION}"),
            })
    except Exception:
        summary["backup"]["error"] = "Không thể tải trạng thái backup"

    try:
        active_users = db.session.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
        inactive_users = db.session.query(func.count(User.id)).filter(User.is_active.is_(False)).scalar() or 0
        summary["users"].update({
            "active": int(active_users),
            "inactive": int(inactive_users),
            "total": int(active_users + inactive_users),
        })
    except Exception:
        summary["users"]["error"] = "Không thể tải số liệu người dùng"

    try:
        alert_cutoff = utc_now() - timedelta(days=7)
        warning_count = db.session.query(func.count(ActivityLog.id)).filter(
            ActivityLog.created_at >= alert_cutoff,
            ActivityLog.severity == "WARNING",
        ).scalar() or 0
        error_count = db.session.query(func.count(ActivityLog.id)).filter(
            ActivityLog.created_at >= alert_cutoff,
            ActivityLog.severity == "ERROR",
        ).scalar() or 0
        latest_alert = db.session.query(ActivityLog).filter(
            ActivityLog.created_at >= alert_cutoff,
            ActivityLog.severity.in_(["WARNING", "ERROR"]),
        ).order_by(ActivityLog.created_at.desc()).first()
        summary["activity"].update({
            "warning_count": int(warning_count),
            "error_count": int(error_count),
            "status": "Cần theo dõi" if (warning_count or error_count) else "Ổn định",
            "latest_time": format_local_datetime(latest_alert.created_at, assume_utc=True) if latest_alert and latest_alert.created_at else None,
        })
    except Exception:
        summary["activity"]["error"] = "Không thể tải cảnh báo gần đây"

    summary["shortcuts"] = [
        {"label": "Người dùng", "icon": "bi-people", "url": "/users"},
        {"label": "Cài đặt", "icon": "bi-gear", "url": "/settings"},
        {"label": "Nhật ký hoạt động", "icon": "bi-clock-history", "url": "/activity-log"},
        {"label": "Sao lưu", "icon": "bi-shield-check", "url": "/settings#card-backup-center"},
    ]
    return summary


def _prepare_dashboard_data():
    data = dict(DashboardService.get_dashboard_data())
    current_user = AuthService.get_current_active_user()
    if can_manage_settings(current_user):
        data["admin_summary"] = _build_admin_summary()
    else:
        data.pop("recent_activities", None)
        data.pop("admin_summary", None)
    return data


@dashboard_bp.route("/")
def index():
    data = _prepare_dashboard_data()
    return render_template("dashboard/index.html", **data)


@dashboard_bp.route("/api/dashboard/data")
def api_dashboard_data():
    """API endpoint to get the latest dashboard data as JSON, utilized by frontend AJAX polling for smart refresh."""
    data = _prepare_dashboard_data()
    return jsonify(data)
