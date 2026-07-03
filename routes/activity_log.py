from flask import render_template, request
from routes import activity_log_bp
from services.activity_log_service import ActivityLogService
from utils.pagination import get_pagination_params

@activity_log_bp.route('/activity-logs')
def index():
    """Retrieve and display activity logs."""
    q = request.args.get('q', '').strip()
    module = request.args.get('module', '').strip()
    action = request.args.get('action', '').strip()
    severity = request.args.get('severity', '').strip()
    time_range = request.args.get('time_range', '').strip()
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()
    sort_by = request.args.get('sort_by', 'newest').strip()
    
    page, per_page = get_pagination_params()
        
    logs = ActivityLogService.get_filtered_logs(
        page=page,
        per_page=per_page,
        module=module,
        action=action,
        severity=severity,
        search_query=q,
        time_range=time_range,
        from_date=from_date,
        to_date=to_date,
        sort_by=sort_by
    )
    
    return render_template(
        'activity_log/index.html',
        logs=logs,
        q=q,
        module=module,
        action=action,
        severity=severity,
        time_range=time_range,
        from_date=from_date,
        to_date=to_date,
        sort_by=sort_by,
        per_page=per_page
    )
