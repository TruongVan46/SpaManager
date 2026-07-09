# models/user.py
from extensions import db
from core.auth.enums import UserRole
from core.auth.security import PasswordHasher
from utils.timezone_utils import utc_now

class User(db.Model):
    __tablename__ = 'users'

    APPROVAL_PENDING = "pending"
    APPROVAL_ACTIVE = "active"
    APPROVAL_REJECTED = "rejected"
    APPROVAL_DISABLED = "disabled"
    APPROVAL_STATUSES = {
        APPROVAL_PENDING,
        APPROVAL_ACTIVE,
        APPROVAL_REJECTED,
        APPROVAL_DISABLED,
    }

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    avatar = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(50), nullable=False, default=UserRole.OWNER.value)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    approval_status = db.Column(db.String(20), nullable=False, default="active", index=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # New fields for Google OAuth & Multi-provider support
    email = db.Column(db.String(255), unique=True, nullable=True)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    auth_provider = db.Column(db.String(50), nullable=False, default='local')
    oauth_id = db.Column(db.String(255), unique=True, nullable=True)

    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Soft delete fields
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    deletion_reason = db.Column(db.String(255), nullable=True)

    deleted_by = db.relationship("User", foreign_keys=[deleted_by_id], remote_side=[id], lazy=True)

    def _normalized_approval_status(self):
        status = (self.approval_status or self.APPROVAL_ACTIVE).strip().lower()
        return status if status in self.APPROVAL_STATUSES else self.APPROVAL_ACTIVE

    @property
    def is_pending_approval(self):
        return self._normalized_approval_status() == self.APPROVAL_PENDING

    @property
    def is_rejected_approval(self):
        return self._normalized_approval_status() == self.APPROVAL_REJECTED

    @property
    def is_disabled_approval(self):
        return self._normalized_approval_status() == self.APPROVAL_DISABLED

    @property
    def is_approval_active(self):
        return self._normalized_approval_status() == self.APPROVAL_ACTIVE

    @property
    def can_access_app(self):
        return bool(self.is_active and self.is_approval_active)

    def set_password(self, password):
        self.password_hash = PasswordHasher.hash_password(password)

    def check_password(self, password):
        return PasswordHasher.verify_password(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'
