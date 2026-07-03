import os
import uuid
from datetime import datetime

from flask import current_app, has_app_context, session
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from extensions import db
from models.user import User
from models.activity_log import ActivityLog
from core.auth.enums import UserRole
from core.auth.constants import AUTH_SESSION_KEY
from core.logger import app_logger
from core.exceptions import ValidationException
from validators.auth_validator import AuthValidator
from validators.profile_validator import ProfileValidator

# services/auth_service.py

class AuthService:
    @staticmethod
    def login(username, password, remember=False):
        """
        Authenticate a user.
        Returns: (success_bool, user_object)
        """
        
        # 1. Validation
        data = {'username': username, 'password': password}
        validator = AuthValidator()
        validator.validate_login(data)
        validator.raise_if_invalid("Thông tin đăng nhập không hợp lệ.")

        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            session[AUTH_SESSION_KEY] = user.id
            session.permanent = remember
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            # Trigger hook
            AuthService.on_login_success(user)
            return True, user
        # Trigger security log for failed login attempts
        app_logger.security(f"Failed login attempt for username: {username}", module="AUTHENTICATION")
        return False, None

    @staticmethod
    def logout():
        """
        Log out the currently active session user.
        Returns: True
        """
        user = AuthService.get_current_user()
        if user:
            AuthService.on_logout(user)
        session.pop(AUTH_SESSION_KEY, None)
        return True

    @staticmethod
    def on_login_success(user):
        """Hook called when login succeeds."""
        try:
            app_logger.security(f"User login successful: {user.username} (ID: {user.id})", module="AUTHENTICATION")
            log = ActivityLog(
                module="Auth",
                action="LOGIN",
                severity="SUCCESS",
                description=f"Chủ Spa ({user.full_name}) đăng nhập thành công.",
                user_id=user.id
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app_logger.error(f"Error in on_login_success hook: {e}", module="AUTHENTICATION", exc_info=True)

    @staticmethod
    def on_logout(user):
        """Hook called when logout occurs."""
        try:
            app_logger.security(f"User logout: {user.username} (ID: {user.id})", module="AUTHENTICATION")
            log = ActivityLog(
                module="Auth",
                action="LOGOUT",
                severity="INFO",
                description=f"Chủ Spa ({user.full_name}) đăng xuất khỏi hệ thống.",
                user_id=user.id
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app_logger.error(f"Error in on_logout hook: {e}", module="AUTHENTICATION", exc_info=True)

    @staticmethod
    def get_current_user():
        """
        Get the currently logged-in user object from session.
        Returns: User or None
        """
        user_id = session.get(AUTH_SESSION_KEY)
        if user_id:
            # Querying the database to fetch the latest state
            return User.query.get(user_id)
        return None

    @staticmethod
    def is_authenticated():
        """
        Check if there is an active logged-in user session.
        Returns: bool
        """
        return AuthService.get_current_user() is not None

    @staticmethod
    def seed_owner_if_empty():
        """
        Seed the initial owner account if it does not already exist.
        """
        owner_username = os.getenv("DEFAULT_OWNER_USERNAME", "owner")
        owner_password = os.getenv("DEFAULT_OWNER_PASSWORD", "owner123")
        owner_email = os.getenv("DEFAULT_OWNER_EMAIL", "") or None

        if has_app_context():
            owner_username = current_app.config.get("DEFAULT_OWNER_USERNAME", owner_username)
            owner_password = current_app.config.get("DEFAULT_OWNER_PASSWORD", owner_password)
            owner_email = current_app.config.get("DEFAULT_OWNER_EMAIL", owner_email) or None

        def get_owner():
            return User.query.filter_by(username=owner_username).first()

        existing_owner = get_owner()
        if existing_owner is not None:
            app_logger.info(
                f"Default owner already exists (username={owner_username}).",
                module="AUTHENTICATION"
            )
            return existing_owner

        owner = User(
            username=owner_username,
            full_name="Chủ Spa",
            role=UserRole.OWNER.value,
            is_active=True,
            email=owner_email
        )
        owner.set_password(owner_password)
        db.session.add(owner)

        try:
            db.session.commit()
            app_logger.info(
                f"Default owner seeded successfully (username={owner_username}).",
                module="AUTHENTICATION"
            )
            return owner
        except IntegrityError:
            db.session.rollback()
            existing_owner = get_owner()
            if existing_owner is not None:
                app_logger.info(
                    f"Default owner was created concurrently by another worker (username={owner_username}).",
                    module="AUTHENTICATION"
                )
                return existing_owner

            app_logger.critical(
                f"IntegrityError while seeding default owner (username={owner_username}).",
                module="AUTHENTICATION",
                exc_info=True
            )
            raise

    @staticmethod
    def change_password(user, current_password, new_password, confirm_password=None):
        """
        Change a user's password.
        Returns: (success_bool, message_str)
        """
        if not user:
            raise ValidationException("Người dùng không hợp lệ.")

        
        confirm_password = confirm_password or new_password
        
        # 1. Validation
        data = {
            'current_password': current_password,
            'new_password': new_password,
            'confirm_password': confirm_password
        }
        validator = AuthValidator()
        validator.validate_change_password(data)
        validator.raise_if_invalid("Thông tin thay đổi mật khẩu không hợp lệ.")

        # 2. Check current password correctness
        if not user.check_password(current_password):
            AuthService.on_change_password_failed(user, "Mật khẩu cũ không chính xác.")
            raise ValidationException("Không thể đổi mật khẩu.")

        # 3. Update password
        user.set_password(new_password)
        user.updated_at = datetime.utcnow()
        db.session.commit()

        # Trigger hook
        AuthService.on_change_password_success(user)
        return True, "Đổi mật khẩu thành công."

    @staticmethod
    def on_change_password_success(user):
        """Hook called when change password succeeds."""
        try:
            app_logger.security(f"Password changed successfully for user: {user.username} (ID: {user.id})", module="SECURITY")
            log = ActivityLog(
                module="Auth",
                action="CHANGE_PASSWORD",
                severity="SUCCESS",
                description="Đổi mật khẩu thành công.",
                user_id=user.id
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app_logger.error(f"Error logging change password success: {e}", module="SECURITY", exc_info=True)

    @staticmethod
    def on_change_password_failed(user, reason):
        """Hook called when change password fails."""
        try:
            app_logger.security(f"Password change failed for user: {user.username} (ID: {user.id}) - Reason: {reason}", module="SECURITY")
            log = ActivityLog(
                module="Auth",
                action="CHANGE_PASSWORD_FAILED",
                severity="WARNING",
                description=f"Đổi mật khẩu thất bại: {reason}",
                user_id=user.id
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app_logger.error(f"Error logging change password failure: {e}", module="SECURITY", exc_info=True)

    @staticmethod
    def update_profile(user, full_name, avatar_file=None):
        """
        Update user profile (Full Name and Avatar).
        Returns: (success_bool, message_str)
        """
        if not user:
            raise ValidationException("Người dùng không hợp lệ.")

        
        # 1. Validation
        data = {
            'full_name': full_name,
            'avatar_file': avatar_file
        }
        validator = ProfileValidator()
        validator.validate(data)
        validator.raise_if_invalid("Thông tin hồ sơ cá nhân không hợp lệ.")

        sanitized_name = full_name.strip()

        # 2. Process avatar upload if provided
        if avatar_file and avatar_file.filename:

            filename = secure_filename(avatar_file.filename)
            ext = os.path.splitext(filename)[1].lower()
            # Create unique filename
            unique_name = f"{uuid.uuid4().hex}{ext}"
            uploads_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars')
            
            # Ensure upload folder exists
            os.makedirs(uploads_dir, exist_ok=True)
            
            file_path = os.path.join(uploads_dir, unique_name)
            
            # Save new avatar
            avatar_file.save(file_path)

            # Delete old custom avatar if it exists
            if user.avatar and user.avatar.startswith('/static/uploads/avatars/'):
                old_avatar_filename = user.avatar.replace('/static/uploads/avatars/', '')
                old_avatar_path = os.path.join(uploads_dir, old_avatar_filename)
                if os.path.exists(old_avatar_path):
                    try:
                        os.remove(old_avatar_path)
                    except Exception as e:
                        app_logger.error(f"Error deleting old avatar file: {e}", module="SECURITY", exc_info=True)

            # Update avatar path in DB
            user.avatar = f"/static/uploads/avatars/{unique_name}"

        # Update full name
        user.full_name = sanitized_name
        user.updated_at = datetime.utcnow()
        db.session.commit()

        # Trigger hook
        AuthService.on_profile_update_success(user)
        return True, "Cập nhật hồ sơ thành công."

    @staticmethod
    def on_profile_update_success(user):
        """Hook called when profile update succeeds."""
        try:
            log = ActivityLog(
                module="Auth",
                action="PROFILE_UPDATE",
                severity="SUCCESS",
                description="Cập nhật thông tin tài khoản.",
                user_id=user.id
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app_logger.error(f"Error logging profile update: {e}", module="SECURITY", exc_info=True)
