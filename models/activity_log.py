from extensions import db
from utils.timezone_utils import utc_now

class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)
    module = db.Column(db.String(100), nullable=False, index=True) # e.g. Customer, Appointment, Invoice, Service, Settings
    action = db.Column(db.String(100), nullable=False, index=True) # e.g. CREATE, UPDATE, DELETE, BACKUP, RESTORE, IMPORT, EXPORT
    description = db.Column(db.Text, nullable=False)   # Detailed log message
    reference_id = db.Column(db.Integer, nullable=True) # ID of the related object (if applicable)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    severity = db.Column(db.String(50), nullable=False, default='INFO', index=True) # INFO, SUCCESS, WARNING, ERROR

    def __repr__(self):
        return f'<ActivityLog {self.module} - {self.action} [{self.severity}] at {self.created_at}>'
