# routes/dashboard.py
from flask import render_template, jsonify
from routes import dashboard_bp
from services.dashboard_service import DashboardService

@dashboard_bp.route('/')
def index():
    data = DashboardService.get_dashboard_data()
    return render_template('dashboard/index.html', **data)

@dashboard_bp.route('/api/dashboard/data')
def api_dashboard_data():
    """API endpoint to get the latest dashboard data as JSON, utilized by frontend AJAX polling for smart refresh."""
    data = DashboardService.get_dashboard_data()
    return jsonify(data)
