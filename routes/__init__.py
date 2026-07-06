from flask import Blueprint

dashboard_bp = Blueprint('dashboard', __name__)
customer_bp = Blueprint('customer', __name__)
service_bp = Blueprint('service', __name__)
appointment_bp = Blueprint('appointment', __name__)
invoice_bp = Blueprint('invoice', __name__)
statistics_bp = Blueprint('statistics', __name__)
setting_bp = Blueprint('setting', __name__)
activity_log_bp = Blueprint('activity_log', __name__)
recycle_bin_bp = Blueprint('recycle_bin', __name__)
auth_bp = Blueprint('auth', __name__)
user_bp = Blueprint('user', __name__)
approval_bp = Blueprint('approval', __name__)

# Import route modules so blueprint routes are registered
from . import dashboard, customer, service, appointment, invoice, statistics, setting, activity_log, recycle_bin, auth, user, approval # noqa: F401
