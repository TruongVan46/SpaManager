from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from extensions import db
from core.auth.enums import UserRole, normalize_role_value
from core.activity_log_utils import build_activity_log_entry, get_activity_actor_display_name
from core.exceptions import ConflictException, NotFoundException, ValidationException
from models.user import User
from utils.timezone_utils import utc_now


class UserService:
    ROLE_LABELS = {
        UserRole.OWNER.value: "Chủ Spa",
        UserRole.ADMIN.value: "Quản trị",
        UserRole.STAFF.value: "Nhân viên",
    }

    AVAILABLE_ROLES = (
        UserRole.STAFF.value,
        UserRole.ADMIN.value,
        UserRole.OWNER.value,
    )

    MANAGER_ROLES = {UserRole.OWNER.value, UserRole.ADMIN.value}

    @staticmethod
    def get_role_label(role):
        return UserService.ROLE_LABELS.get(role, role or "Không xác định")

    @staticmethod
    def get_available_roles():
        return [(role, UserService.get_role_label(role)) for role in UserService.AVAILABLE_ROLES]

    @staticmethod
    def _normalize_username(username):
        return (username or "").strip()

    @staticmethod
    def _normalize_email(email):
        cleaned = (email or "").strip().lower()
        return cleaned or None

    @staticmethod
    def _normalize_full_name(full_name):
        return (full_name or "").strip()

    @staticmethod
    def _normalize_role(role):
        normalized = normalize_role_value(role) or UserRole.STAFF.value
        if normalized not in UserService.AVAILABLE_ROLES:
            raise ValidationException("Vai trò người dùng không hợp lệ.", field_errors={"role": "Vai trò người dùng không hợp lệ."})
        return normalized

    @staticmethod
    def _normalize_bool(value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return value != 0
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    @staticmethod
    def _is_manager_role(role):
        return normalize_role_value(role) in UserService.MANAGER_ROLES

    @staticmethod
    def _get_user_or_404(user_id):
        user = User.query.get(user_id)
        if not user:
            raise NotFoundException("Không tìm thấy người dùng.")
        return user

    @staticmethod
    def _get_active_manager_count(exclude_user_id=None):
        query = User.query.filter(
            User.is_active.is_(True),
            func.lower(User.role).in_([role.lower() for role in UserService.MANAGER_ROLES]),
        )
        if exclude_user_id is not None:
            query = query.filter(User.id != exclude_user_id)
        return query.count()

    @staticmethod
    def _ensure_unique_fields(username, email, exclude_user_id=None):
        errors = {}

        username_query = User.query.filter(User.username == username)
        if exclude_user_id is not None:
            username_query = username_query.filter(User.id != exclude_user_id)
        if username_query.first():
            errors["username"] = "Tên đăng nhập đã tồn tại."

        if email:
            email_query = User.query.filter(User.email == email)
            if exclude_user_id is not None:
                email_query = email_query.filter(User.id != exclude_user_id)
            if email_query.first():
                errors["email"] = "Email này đã được sử dụng."

        if errors:
            raise ValidationException("Dữ liệu người dùng không hợp lệ.", field_errors=errors)

    @staticmethod
    def _log_user_action(actor, action, description, target_user, severity="SUCCESS"):
        log_entry = build_activity_log_entry(
            module="Users",
            action=action,
            severity=severity,
            description=description,
            reference_id=target_user.id if target_user else None,
            user_id=actor.id if actor else None,
        )
        log_entry.created_at = utc_now()
        db.session.add(log_entry)

    @staticmethod
    def search_paginated(query_text="", page=1, per_page=25, sort_by="created_at", sort_dir="desc"):
        query = User.query
        search = (query_text or "").strip()
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                or_(
                    User.username.ilike(pattern),
                    User.full_name.ilike(pattern),
                    User.email.ilike(pattern),
                    User.role.ilike(pattern),
                )
            )

        sort_map = {
            "username": User.username,
            "email": User.email,
            "role": User.role,
            "is_active": User.is_active,
            "created_at": User.created_at,
        }
        sort_column = sort_map.get(sort_by, User.created_at)
        if sort_dir == "asc":
            query = query.order_by(sort_column.asc(), User.id.asc())
        else:
            query = query.order_by(sort_column.desc(), User.id.desc())

        return query.paginate(page=page, per_page=per_page, error_out=False)

    @staticmethod
    def create_user(actor, username, full_name, password, email=None, role=None, is_active=True):
        username = UserService._normalize_username(username)
        full_name = UserService._normalize_full_name(full_name)
        email = UserService._normalize_email(email)
        role = UserService._normalize_role(role)
        errors = {}

        if not username:
            errors["username"] = "Tên đăng nhập không được để trống."
        if not full_name:
            errors["full_name"] = "Họ và tên không được để trống."
        if not password:
            errors["password"] = "Mật khẩu không được để trống."
        if errors:
            raise ValidationException("Dữ liệu người dùng không hợp lệ.", field_errors=errors)

        UserService._ensure_unique_fields(username=username, email=email)

        user = User(
            username=username,
            full_name=full_name,
            email=email,
            role=role,
            is_active=UserService._normalize_bool(is_active),
        )
        user.set_password(password)
        db.session.add(user)
        actor_display_name = get_activity_actor_display_name(actor)

        try:
            db.session.flush()
            UserService._log_user_action(
                actor=actor,
                action="CREATE_USER",
                description=f"{actor_display_name} đã tạo tài khoản {user.username}.",
                target_user=user,
            )
            db.session.commit()
            return user
        except IntegrityError as exc:
            db.session.rollback()
            raise ConflictException("Tên đăng nhập hoặc email đã tồn tại.") from exc
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def update_user(actor, user_id, username, full_name, email=None, role=None):
        user = UserService._get_user_or_404(user_id)

        username = UserService._normalize_username(username)
        full_name = UserService._normalize_full_name(full_name)
        email = UserService._normalize_email(email)
        role = UserService._normalize_role(role)

        errors = {}
        if not username:
            errors["username"] = "Tên đăng nhập không được để trống."
        if not full_name:
            errors["full_name"] = "Họ và tên không được để trống."
        if errors:
            raise ValidationException("Dữ liệu người dùng không hợp lệ.", field_errors=errors)

        if user.id == actor.id and UserService._is_manager_role(user.role) and role not in UserService.MANAGER_ROLES:
            raise ValidationException(
                "Không thể tự hạ quyền quản trị của chính mình.",
                field_errors={"role": "Không thể tự hạ quyền quản trị của chính mình."}
            )

        UserService._ensure_unique_fields(username=username, email=email, exclude_user_id=user.id)

        if user.id != actor.id and user.is_active and UserService._is_manager_role(user.role) and role not in UserService.MANAGER_ROLES:
            if UserService._get_active_manager_count(exclude_user_id=user.id) <= 0:
                raise ValidationException("Không thể hạ quyền owner/admin cuối cùng.", field_errors={"role": "Không thể hạ quyền owner/admin cuối cùng."})

        user.username = username
        user.full_name = full_name
        user.email = email
        user.role = role
        user.updated_at = utc_now()
        actor_display_name = get_activity_actor_display_name(actor)

        try:
            UserService._log_user_action(
                actor=actor,
                action="UPDATE_USER",
                description=f"{actor_display_name} đã cập nhật tài khoản {user.username}.",
                target_user=user,
            )
            db.session.commit()
            return user
        except IntegrityError as exc:
            db.session.rollback()
            raise ConflictException("Tên đăng nhập hoặc email đã tồn tại.") from exc
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def reset_password(actor, user_id, new_password):
        user = UserService._get_user_or_404(user_id)
        if not new_password:
            raise ValidationException("Mật khẩu mới không được để trống.", field_errors={"new_password": "Mật khẩu mới không được để trống."})

        user.set_password(new_password)
        user.updated_at = utc_now()
        actor_display_name = get_activity_actor_display_name(actor)

        try:
            UserService._log_user_action(
                actor=actor,
                action="RESET_USER_PASSWORD",
                description=f"{actor_display_name} đã đặt lại mật khẩu cho {user.username}.",
                target_user=user,
            )
            db.session.commit()
            return user
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def toggle_active(actor, user_id, is_active):
        user = UserService._get_user_or_404(user_id)
        desired_active = UserService._normalize_bool(is_active)

        if user.id == actor.id and not desired_active:
            raise ValidationException("Không thể vô hiệu hóa chính mình.", field_errors={"is_active": "Không thể vô hiệu hóa chính mình."})

        if user.is_active and not desired_active and UserService._is_manager_role(user.role):
            if UserService._get_active_manager_count(exclude_user_id=user.id) <= 0:
                raise ValidationException("Không thể vô hiệu hóa owner/admin cuối cùng.", field_errors={"is_active": "Không thể vô hiệu hóa owner/admin cuối cùng."})

        user.is_active = desired_active
        user.updated_at = utc_now()
        actor_display_name = get_activity_actor_display_name(actor)
        action = "ACTIVATE_USER" if desired_active else "DEACTIVATE_USER"
        description = (
            f"{actor_display_name} đã kích hoạt tài khoản {user.username}."
            if desired_active
            else f"{actor_display_name} đã vô hiệu hóa tài khoản {user.username}."
        )

        try:
            UserService._log_user_action(
                actor=actor,
                action=action,
                description=description,
                target_user=user,
            )
            db.session.commit()
            return user
        except Exception:
            db.session.rollback()
            raise
