# models/user.py
from extensions import db
from core.auth.enums import UserRole
from core.auth.security import PasswordHasher
from utils.timezone_utils import utc_now

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    avatar = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(50), nullable=False, default=UserRole.OWNER.value)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # New fields for Google OAuth & Multi-provider support
    email = db.Column(db.String(255), unique=True, nullable=True)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    auth_provider = db.Column(db.String(50), nullable=False, default='local')
    oauth_id = db.Column(db.String(255), unique=True, nullable=True)

    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    def set_password(self, password):
        self.password_hash = PasswordHasher.hash_password(password)

    def check_password(self, password):
        return PasswordHasher.verify_password(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'
