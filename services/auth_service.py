import os
import uuid
from datetime import datetime

from flask import current_app, has_app_context, has_request_context, session
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from extensions import db
from models.user import User
from models.activity_log import ActivityLog
from core.auth.enums import UserRole, normalize_role_value
from core.auth.constants import AUTH_SESSION_KEY
from core.logger import app_logger
from core.exceptions import AuthenticationException, PermissionDeniedException, ValidationException
from validators.auth_validator import AuthValidator
from validators.profile_validator import ProfileValidator
from utils.timezone_utils import utc_now
from utils.media_storage import resolve_media_file_path
from core.auth.permissions import can_manage_users

# services/auth_service.py

class AuthService:
    MANAGER_ROLES = {UserRole.OWNER.value, UserRole.ADMIN.value}

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
            from core.csrf import rotate_csrf_token
            rotate_csrf_token()
            user.last_login = utc_now()
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
        from core.csrf import clear_csrf_token
        clear_csrf_token()
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
        if not has_request_context():
            return None
        user_id = session.get(AUTH_SESSION_KEY)
        if user_id:
            # Querying the database to fetch the latest state
            return User.query.get(user_id)
        return None

    @staticmethod
    def get_current_active_user():
        user = AuthService.get_current_user()
        if user and user.is_active:
            return user
        return None

    @staticmethod
    def get_current_username():
        """
        Get the username of the currently logged-in user.
        Returns: str or None
        """
        current_user = AuthService.get_current_active_user()
        return current_user.username if current_user else None

    @staticmethod
    def is_manager_user(user=None):
        user = user or AuthService.get_current_active_user()
        return can_manage_users(user)

    @staticmethod
    def require_current_username():
        """
        Require a valid authenticated username for user-triggered operations.
        Raises AuthenticationException when the current actor is missing.
        """
        username = AuthService.get_current_username()
        if not username:
            raise AuthenticationException("Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
        return username

    @staticmethod
    def require_manager_user():
        user = AuthService.get_current_active_user()
        if not user:
            raise AuthenticationException("Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
        if not can_manage_users(user):
            raise PermissionDeniedException("Bạn không có quyền truy cập khu vực quản lý người dùng.")
        return user

    @staticmethod
    def is_authenticated():
        """
        Check if there is an active logged-in user session.
        Returns: bool
        """
        return AuthService.get_current_active_user() is not None

    @staticmethod
    def seed_owner_if_empty():
        """
        Seed the initial owner account if it does not already exist.
        """
        if has_app_context():
            owner_username = current_app.config.get("DEFAULT_OWNER_USERNAME", "owner")
            owner_password = current_app.config.get("DEFAULT_OWNER_PASSWORD")
            owner_email = current_app.config.get("DEFAULT_OWNER_EMAIL", "") or None
        else:
            from config import get_active_config

            active_config = get_active_config()
            owner_username = getattr(active_config, "DEFAULT_OWNER_USERNAME", "owner")
            owner_password = getattr(active_config, "DEFAULT_OWNER_PASSWORD", None)
            owner_email = getattr(active_config, "DEFAULT_OWNER_EMAIL", "") or None

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
        user.updated_at = utc_now()
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
        old_avatar_path = None
        if avatar_file and avatar_file.filename:

            filename = secure_filename(avatar_file.filename)
            ext = os.path.splitext(filename)[1].lower()
            # Create unique filename
            unique_name = f"{uuid.uuid4().hex}{ext}"
            uploads_dir = current_app.config['AVATAR_UPLOAD_FOLDER']
            
            # Ensure upload folder exists
            os.makedirs(uploads_dir, exist_ok=True)
            
            file_path = os.path.join(uploads_dir, unique_name)
            
            # Save new avatar
            avatar_file.save(file_path)

            # Delete old custom avatar if it exists
            old_avatar_path = resolve_media_file_path(
                user.avatar,
                'avatar',
                current_app.config['UPLOAD_ROOT'],
                current_app.root_path
            )

            # Update avatar path in DB
            user.avatar = f"avatars/{unique_name}"

        # Update full name
        user.full_name = sanitized_name
        user.updated_at = utc_now()
        try:
            db.session.commit()
        except Exception:
            if avatar_file and avatar_file.filename and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            raise

        if old_avatar_path and os.path.exists(old_avatar_path):
            try:
                os.remove(old_avatar_path)
            except Exception as e:
                app_logger.error(f"Error deleting old avatar file: {e}", module="SECURITY", exc_info=True)

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
