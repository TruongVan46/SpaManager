from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from extensions import db
from core.auth.enums import UserRole, normalize_role_value
from core.auth.security import PasswordPolicy
from core.activity_log_utils import build_activity_log_entry, get_activity_actor_display_name
from core.exceptions import ConflictException, NotFoundException, ValidationException
from models.user import User
from models.workspace import WorkspaceMember
from utils.timezone_utils import utc_now
from services.workspace_service import WorkspaceService


class UserService:
    ROLE_LABELS = {
        UserRole.OWNER.value: "Chủ Spa",
        UserRole.ADMIN.value: "Quản trị",
        UserRole.STAFF.value: "Nhân viên",
        UserRole.APPROVAL_OWNER.value: "Quản trị duyệt tài khoản",
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
        """Get user by id without workspace scope (used internally)."""
        user = User.query.get(user_id)
        if not user:
            raise NotFoundException("Không tìm thấy người dùng.")
        return user

    @staticmethod
    def _get_workspace_scoped_user_or_404(user_id):
        """
        Get user by id, ensuring they belong to the current workspace.
        In production: validates workspace membership; raises 404 if not found or not in workspace.
        In TESTING without isolation flag: skips workspace check (legacy test compat).
        """
        from flask import current_app, has_app_context, has_request_context, session

        user = User.query.get(user_id)
        if not user:
            raise NotFoundException("Không tìm thấy người dùng.")

        is_testing = has_app_context() and current_app.config.get("TESTING") is True
        if is_testing:
            if not has_request_context() or not session.get("_enable_workspace_isolation"):
                return user
            workspace_id = session.get("current_workspace_id")
        else:
            workspace_id = WorkspaceService.get_current_workspace_id()

        if workspace_id and not WorkspaceService.is_user_in_workspace(user.id, workspace_id):
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
    def _get_workspace_scoped_base_query():
        """
        Return a base User query scoped to the current workspace.

        Production: joins WorkspaceMember and filters by current workspace_id.
        Fail-closed: if no workspace context, returns a query that yields nothing.
        TESTING without isolation flag: returns unscoped query (legacy compat).
        """
        from flask import current_app, has_app_context, has_request_context, session

        is_testing = has_app_context() and current_app.config.get("TESTING") is True
        if is_testing:
            if not has_request_context() or not session.get("_enable_workspace_isolation"):
                return User.query
            workspace_id = session.get("current_workspace_id")
        else:
            workspace_id = WorkspaceService.get_current_workspace_id()

        base = WorkspaceService.get_workspace_members_query(workspace_id)
        if base is None:
            # Fail-closed: impossible user_id constraint
            return User.query.filter(User.id == -1)
        return base

    @staticmethod
    def search_paginated(query_text="", page=1, per_page=25, sort_by="created_at", sort_dir="desc"):
        query = UserService._get_workspace_scoped_base_query().filter(
            User.role != UserRole.APPROVAL_OWNER.value
        )
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
    def pending_paginated(page=1, per_page=25):
        query = User.query.filter(User.approval_status == User.APPROVAL_PENDING)
        query = query.order_by(User.created_at.desc(), User.id.desc())
        return query.paginate(page=page, per_page=per_page, error_out=False)

    @staticmethod
    def _resolve_current_workspace_id_for_create():
        """
        Resolve the workspace_id to use when creating a user from the UI.
        Production: requires a valid workspace context (fail-closed).
        TESTING with isolation flag: reads from session.
        TESTING without isolation flag: returns None (skip membership creation).
        Raises ValidationException if production has no workspace context.
        """
        from flask import current_app, has_app_context, has_request_context, session

        is_testing = has_app_context() and current_app.config.get("TESTING") is True
        if is_testing:
            if not has_request_context() or not session.get("_enable_workspace_isolation"):
                return None
            workspace_id = session.get("current_workspace_id")
            if not workspace_id:
                raise ValidationException(
                    "Không có workspace hiện tại. Vui lòng đăng nhập lại và chọn workspace."
                )
            return workspace_id

        workspace_id = WorkspaceService.get_current_workspace_id()
        if not workspace_id:
            raise ValidationException(
                "Không có workspace hiện tại. Vui lòng đăng nhập lại và chọn workspace."
            )
        return workspace_id

    @staticmethod
    def create_user(actor, username, full_name, password, email=None, role=None, is_active=True):
        username = UserService._normalize_username(username)
        full_name = UserService._normalize_full_name(full_name)
        email = UserService._normalize_email(email)
        role = UserService._normalize_role(role)
        errors = {}

        # Roles that cannot be created from UI (system-level only)
        if role in (UserRole.APPROVAL_OWNER.value, UserRole.OWNER.value):
            raise ValidationException(
                "Không thể tạo vai trò này từ giao diện quản lý.",
                field_errors={"role": "Vai trò không được phép."},
            )

        # Prevent non-OWNER actors from creating ADMIN users
        if role == UserRole.ADMIN.value and actor and actor.role != UserRole.OWNER.value:
            raise ValidationException(
                "Bạn không có quyền gán vai trò này.",
                field_errors={"role": "Bạn không có quyền gán vai trò này."},
            )

        if not username:
            errors["username"] = "Tên đăng nhập không được để trống."
        if not full_name:
            errors["full_name"] = "Họ và tên không được để trống."
        if not password:
            errors["password"] = "Mật khẩu không được để trống."
        if errors:
            raise ValidationException("Dữ liệu người dùng không hợp lệ.", field_errors=errors)

        policy_result = PasswordPolicy.validate_password(password, require_confirm=False, prevent_reuse=False)
        if not policy_result.valid:
            raise ValidationException(policy_result.message, field_errors=policy_result.errors)

        UserService._ensure_unique_fields(username=username, email=email)

        workspace_id = UserService._resolve_current_workspace_id_for_create()

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

            # Assign user to current workspace
            if workspace_id:
                WorkspaceService.add_member_for_user(
                    workspace_id=workspace_id,
                    user=user,
                    global_role=role,
                    actor=actor,
                )

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
        user = UserService._get_workspace_scoped_user_or_404(user_id)
        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể sửa đổi tài khoản phê duyệt hệ thống.", field_errors={"role": "Không thể sửa đổi tài khoản phê duyệt hệ thống."})

        username = UserService._normalize_username(username)
        full_name = UserService._normalize_full_name(full_name)
        email = UserService._normalize_email(email)
        role = UserService._normalize_role(role)

        if role == UserRole.OWNER.value and user.role != UserRole.OWNER.value:
            raise ValidationException(
                "Không thể thay đổi vai trò thành chủ spa từ giao diện quản lý.",
                field_errors={"role": "Không thể thay đổi vai trò thành chủ spa."},
            )

        if role == UserRole.ADMIN.value and user.role != UserRole.ADMIN.value and actor and actor.role != UserRole.OWNER.value:
            raise ValidationException(
                "Bạn không có quyền gán vai trò này.",
                field_errors={"role": "Bạn không có quyền gán vai trò này."},
            )

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
        user = UserService._get_workspace_scoped_user_or_404(user_id)
        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể sửa đổi tài khoản phê duyệt hệ thống.")
        if not new_password:
            raise ValidationException("Mật khẩu mới không được để trống.", field_errors={"new_password": "Mật khẩu mới không được để trống."})

        policy_result = PasswordPolicy.validate_password(
            new_password,
            require_confirm=False,
            prevent_reuse=True,
            current_password_hash=user.password_hash,
        )
        if not policy_result.valid:
            raise ValidationException(policy_result.message, field_errors=policy_result.errors)

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
        user = UserService._get_workspace_scoped_user_or_404(user_id)
        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể sửa đổi tài khoản phê duyệt hệ thống.")
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

    @staticmethod
    def list_approval_accounts(status=None, page=1, per_page=25):
        from core.auth.enums import UserRole
        query = User.query.filter(User.role != UserRole.APPROVAL_OWNER.value)
        if status == 'deleted':
            query = query.filter(User.deleted_at.isnot(None)).order_by(User.deleted_at.desc(), User.id.desc())
        else:
            query = query.filter(User.deleted_at.is_(None))
            if status:
                query = query.filter(User.approval_status == status)
            query = query.order_by(User.created_at.desc(), User.id.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        from models.workspace import WorkspaceMember
        for u in pagination.items:
            u.group_type = "other"
            u.workspace_name = ""
            u.workspace_id = None
            u.owner_name = ""
            u.owner_username = ""

            if u.role == UserRole.OWNER.value:
                u.group_type = "owner_registration"
                member = WorkspaceMember.query.filter_by(user_id=u.id, role="owner").first()
                if member:
                    u.workspace_id = member.workspace_id
                    u.workspace_name = member.workspace.name
            else:
                member = WorkspaceMember.query.filter_by(user_id=u.id).first()
                if member:
                    u.workspace_id = member.workspace_id
                    u.workspace_name = member.workspace.name
                    u.group_type = "owner_created_member"
                    owner_member = WorkspaceMember.query.filter_by(workspace_id=member.workspace_id, role="owner").first()
                    if owner_member:
                        u.owner_name = owner_member.user.full_name
                        u.owner_username = owner_member.user.username

        return pagination

    @staticmethod
    def approve_user(actor, user_id):
        user = UserService._get_user_or_404(user_id)
        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể duyệt tài khoản quản trị hệ thống.")

        user.approval_status = User.APPROVAL_ACTIVE
        user.is_active = True
        user.approved_by_id = actor.id if actor else None
        user.approved_at = utc_now()
        user.updated_at = utc_now()

        from models.workspace import WorkspaceMember
        existing_memberships = WorkspaceMember.query.filter_by(user_id=user.id).all()
        for m in existing_memberships:
            m.status = "active"
            m.updated_at = utc_now()

        if user.auth_provider == "google":
            user.role = UserRole.OWNER.value
            owner_membership = WorkspaceMember.query.filter_by(user_id=user.id, role="owner").first()
            if owner_membership:
                owner_membership.status = "active"
                owner_membership.updated_at = utc_now()
            else:
                other_membership = WorkspaceMember.query.filter_by(user_id=user.id).first()
                if other_membership:
                    other_membership.status = "active"
                    other_membership.role = "owner"
                    other_membership.updated_at = utc_now()
                else:
                    WorkspaceService.ensure_workspace_for_approved_owner(user, approved_by=actor)

        actor_display_name = get_activity_actor_display_name(actor)
        try:
            UserService._log_user_action(
                actor=actor,
                action="APPROVE_USER",
                description=f"{actor_display_name} đã duyệt/kích hoạt tài khoản {user.username}.",
                target_user=user,
            )
            db.session.commit()
            return user
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def reject_user(actor, user_id):
        user = UserService._get_user_or_404(user_id)
        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể từ chối tài khoản quản trị hệ thống.")
        if user.approval_status != User.APPROVAL_PENDING:
            raise ValidationException("Chỉ có thể từ chối tài khoản đang chờ duyệt.")

        user.approval_status = User.APPROVAL_REJECTED
        user.is_active = False
        user.approved_by_id = None
        user.approved_at = None
        user.updated_at = utc_now()
        actor_display_name = get_activity_actor_display_name(actor)
        try:
            UserService._log_user_action(
                actor=actor,
                action="REJECT_USER",
                description=f"{actor_display_name} đã từ chối tài khoản {user.username}.",
                target_user=user,
            )
            db.session.commit()
            return user
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def disable_user(actor, user_id):
        user = UserService._get_user_or_404(user_id)
        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể vô hiệu hóa tài khoản quản trị hệ thống.")
        if user.id == actor.id:
            raise ValidationException("Không thể tự vô hiệu hóa chính mình.")
        if user.approval_status != User.APPROVAL_ACTIVE:
            raise ValidationException("Chỉ có thể vô hiệu hóa tài khoản đã duyệt.")

        user.approval_status = User.APPROVAL_DISABLED
        user.is_active = False
        user.updated_at = utc_now()

        from models.workspace import WorkspaceMember
        memberships = WorkspaceMember.query.filter_by(user_id=user.id).all()
        for membership in memberships:
            membership.status = "inactive"
            membership.updated_at = utc_now()

        actor_display_name = get_activity_actor_display_name(actor)
        try:
            UserService._log_user_action(
                actor=actor,
                action="DISABLE_USER",
                description=f"{actor_display_name} đã vô hiệu hóa tài khoản {user.username}.",
                target_user=user,
            )
            db.session.commit()
            return user
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def enable_user(actor, user_id):
        user = UserService._get_user_or_404(user_id)
        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể kích hoạt tài khoản quản trị hệ thống.")
        if user.approval_status not in (User.APPROVAL_DISABLED, User.APPROVAL_REJECTED):
            raise ValidationException("Chỉ có thể kích hoạt tài khoản đang bị vô hiệu hóa hoặc bị từ chối.")

        return UserService.approve_user(actor, user_id)

    @staticmethod
    def approve_pending_user(actor, user_id):
        user = UserService._get_user_or_404(user_id)
        if user.approval_status != User.APPROVAL_PENDING:
            raise ValidationException("Chỉ có thể duyệt tài khoản đang chờ duyệt.", field_errors={"approval_status": "Chỉ có thể duyệt tài khoản đang chờ duyệt."})
        return UserService.approve_user(actor, user_id)

    @staticmethod
    def reject_pending_user(actor, user_id):
        user = UserService._get_user_or_404(user_id)
        if user.approval_status != User.APPROVAL_PENDING:
            raise ValidationException("Chỉ có thể từ chối tài khoản đang chờ duyệt.", field_errors={"approval_status": "Chỉ có thể từ chối tài khoản đang chờ duyệt."})
        return UserService.reject_user(actor, user_id)

    @staticmethod
    def search_removed_paginated(query_text="", page=1, per_page=25):
        from models.workspace import WorkspaceMember
        from flask import current_app, has_app_context, has_request_context, session

        is_testing = has_app_context() and current_app.config.get("TESTING") is True
        if is_testing:
            if not has_request_context() or not session.get("_enable_workspace_isolation"):
                workspace_id = session.get("current_workspace_id")
            else:
                workspace_id = session.get("current_workspace_id")
        else:
            workspace_id = WorkspaceService.get_current_workspace_id()

        if not workspace_id:
            return User.query.filter(User.id == -1).paginate(page=page, per_page=per_page, error_out=False)

        query = (
            User.query
            .join(
                WorkspaceMember,
                (WorkspaceMember.user_id == User.id)
                & (WorkspaceMember.workspace_id == workspace_id)
                & (WorkspaceMember.status == "removed"),
            )
        )

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

        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        for u in pagination.items:
            m = WorkspaceMember.query.filter_by(workspace_id=workspace_id, user_id=u.id, status="removed").first()
            if m:
                u.removed_at = m.removed_at
                u.removed_by = m.removed_by
                u.removal_reason = m.removal_reason
        return pagination

    @staticmethod
    def soft_delete_user(actor, user_id, reason=None):
        from models.workspace import WorkspaceMember

        if actor.role != "OWNER":
            raise ValidationException("Chỉ chủ spa mới có quyền xóa mềm nhân viên.")

        user = User.query.get(user_id)
        if not user:
            raise NotFoundException("Không tìm thấy người dùng.")

        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể xóa tài khoản quản trị hệ thống.")

        if user.role == UserRole.OWNER.value:
            raise ValidationException("Không thể xóa tài khoản chủ spa.")

        if user.id == actor.id:
            raise ValidationException("Không thể tự xóa chính mình.")

        workspace_id = None
        try:
            workspace_id = UserService._resolve_current_workspace_id_for_create()
        except Exception:
            pass

        if not workspace_id:
            member_own = WorkspaceMember.query.filter_by(
                user_id=actor.id, role="owner", status="active"
            ).first()
            if member_own:
                workspace_id = member_own.workspace_id

        if not workspace_id:
            raise ValidationException("Không có workspace hiện tại.")

        membership = WorkspaceMember.query.filter_by(
            workspace_id=workspace_id,
            user_id=user.id,
            status="active"
        ).first()

        if not membership:
            raise ValidationException("Người dùng không thuộc workspace này hoặc đã bị xóa.")

        membership.status = "removed"
        membership.removed_at = utc_now()
        membership.removed_by_id = actor.id
        membership.removal_reason = reason
        membership.updated_at = utc_now()

        actor_display_name = get_activity_actor_display_name(actor)
        try:
            UserService._log_user_action(
                actor=actor,
                action="REMOVE_USER",
                description=f"{actor_display_name} đã xóa mềm nhân viên {user.username} khỏi workspace.",
                target_user=user,
            )
            db.session.commit()
            return user
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def restore_user(actor, user_id):
        from models.workspace import WorkspaceMember

        if actor.role != "OWNER":
            raise ValidationException("Chỉ chủ spa mới có quyền khôi phục nhân viên.")

        user = User.query.get(user_id)
        if not user:
            raise NotFoundException("Không tìm thấy người dùng.")

        workspace_id = None
        try:
            workspace_id = UserService._resolve_current_workspace_id_for_create()
        except Exception:
            pass

        if not workspace_id:
            member_own = WorkspaceMember.query.filter_by(
                user_id=actor.id, role="owner", status="active"
            ).first()
            if member_own:
                workspace_id = member_own.workspace_id

        if not workspace_id:
            raise ValidationException("Không có workspace hiện tại.")

        membership = WorkspaceMember.query.filter_by(
            workspace_id=workspace_id,
            user_id=user.id,
            status="removed"
        ).first()

        if not membership:
            raise ValidationException("Người dùng chưa bị xóa hoặc không thuộc workspace này.")

        membership.status = "active"
        membership.removed_at = None
        membership.removed_by_id = None
        membership.removal_reason = None
        membership.updated_at = utc_now()

        actor_display_name = get_activity_actor_display_name(actor)
        try:
            UserService._log_user_action(
                actor=actor,
                action="RESTORE_USER",

                description=f"{actor_display_name} đã khôi phục nhân viên {user.username} vào workspace.",
                target_user=user,
            )
            db.session.commit()
            return user
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def soft_delete_account(actor, user_id, reason=None):
        from core.auth.enums import UserRole
        from core.exceptions import PermissionDeniedException

        if actor.role != UserRole.APPROVAL_OWNER.value:
            raise PermissionDeniedException("Chỉ quản trị hệ thống mới có quyền xóa mềm tài khoản.")

        if actor.id == user_id:
            raise ValidationException("Không thể tự xóa chính mình.")

        user = User.query.get(user_id)
        if not user:
            raise NotFoundException("Không tìm thấy người dùng.")

        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể xóa tài khoản quản trị hệ thống.")

        if user.role == UserRole.OWNER.value:
            raise ValidationException("Xóa owner sẽ được xử lý ở bước workspace lifecycle riêng.")

        if user.deleted_at is not None:
            raise ValidationException("Tài khoản này đã bị xóa mềm trước đó.")

        user.deleted_at = utc_now()
        user.deleted_by_id = actor.id
        user.deletion_reason = reason
        user.is_active = False

        actor_display_name = get_activity_actor_display_name(actor)
        try:
            UserService._log_user_action(
                actor=actor,
                action="SOFT_DELETE_ACCOUNT",
                description=f"{actor_display_name} đã xóa mềm tài khoản {user.username}.",
                target_user=user,
            )
            db.session.commit()
            return user
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def restore_account(actor, user_id):
        from core.auth.enums import UserRole
        from core.exceptions import PermissionDeniedException

        if actor.role != UserRole.APPROVAL_OWNER.value:
            raise PermissionDeniedException("Chỉ quản trị hệ thống mới có quyền khôi phục tài khoản.")

        user = User.query.get(user_id)
        if not user:
            raise NotFoundException("Không tìm thấy người dùng.")

        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể khôi phục tài khoản quản trị hệ thống.")

        if user.role == UserRole.OWNER.value:
            raise ValidationException("Khôi phục owner sẽ được xử lý ở bước workspace lifecycle riêng.")

        if user.deleted_at is None:
            raise ValidationException("Tài khoản này chưa bị xóa mềm.")

        user.deleted_at = None
        user.deleted_by_id = None
        user.deletion_reason = None

        # Handle is_active safely
        if user._normalized_approval_status() == User.APPROVAL_ACTIVE:
            user.is_active = True
        else:
            user.is_active = False

        actor_display_name = get_activity_actor_display_name(actor)
        try:
            UserService._log_user_action(
                actor=actor,
                action="RESTORE_ACCOUNT",
                description=f"{actor_display_name} đã khôi phục tài khoản {user.username}.",
                target_user=user,
            )
            db.session.commit()
            return user
        except Exception:
            db.session.rollback()
            raise


    @staticmethod
    def soft_delete_owner_workspace(actor, user_id, reason=None):
        from core.auth.enums import UserRole
        from core.exceptions import PermissionDeniedException
        from models.workspace import Workspace, WorkspaceMember

        if actor.role != UserRole.APPROVAL_OWNER.value:
            raise PermissionDeniedException("Chỉ quản trị hệ thống mới có quyền xóa mềm tài khoản.")

        if actor.id == user_id:
            raise ValidationException("Không thể tự xóa chính mình.")

        user = User.query.get(user_id)
        if not user:
            raise NotFoundException("Không tìm thấy người dùng.")

        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể xóa tài khoản quản trị hệ thống.")

        if user.role != UserRole.OWNER.value:
            raise ValidationException("Tài khoản này không phải là owner.")

        if user.deleted_at is not None:
            raise ValidationException("Tài khoản này đã bị xóa mềm trước đó.")

        now = utc_now()

        # 1. Soft-delete owner
        user.deleted_at = now
        user.deleted_by_id = actor.id
        user.deletion_reason = reason
        user.is_active = False

        # 2. Find owned active workspaces
        owned_workspaces = Workspace.query.join(
            WorkspaceMember,
            (WorkspaceMember.workspace_id == Workspace.id)
            & (WorkspaceMember.user_id == user.id)
            & (WorkspaceMember.role == "owner")
            & (WorkspaceMember.status == "active")
        ).filter(Workspace.deleted_at.is_(None)).all()

        ws_names = []
        for ws in owned_workspaces:
            ws.deleted_at = now
            ws.deleted_by_id = actor.id
            ws.deletion_reason = reason
            ws.updated_at = now
            ws_names.append(ws.name)

        actor_display_name = get_activity_actor_display_name(actor)
        if owned_workspaces:
            ws_list_str = ", ".join(ws_names)
            desc = f"{actor_display_name} đã xóa mềm OWNER {user.username} và các workspace liên quan: {ws_list_str}."
        else:
            desc = f"{actor_display_name} đã xóa mềm OWNER {user.username} (Không tìm thấy workspace active liên quan)."

        try:
            UserService._log_user_action(
                actor=actor,
                action="SOFT_DELETE_OWNER_WORKSPACE",
                description=desc,
                target_user=user,
            )
            db.session.commit()
            return user
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def restore_owner_workspace(actor, user_id):
        from core.auth.enums import UserRole
        from core.exceptions import PermissionDeniedException
        from models.workspace import Workspace, WorkspaceMember

        if actor.role != UserRole.APPROVAL_OWNER.value:
            raise PermissionDeniedException("Chỉ quản trị hệ thống mới có quyền khôi phục owner và workspace.")

        if actor.id == user_id:
            raise ValidationException("Không thể tự khôi phục chính mình bằng chức năng này.")

        user = User.query.get(user_id)
        if not user:
            raise NotFoundException("Không tìm thấy người dùng.")

        if user.role == UserRole.APPROVAL_OWNER.value:
            raise ValidationException("Không thể khôi phục tài khoản quản trị hệ thống bằng chức năng này.")

        if user.role != UserRole.OWNER.value:
            raise ValidationException(
                "Tài khoản này không phải là owner. Hãy dùng chức năng khôi phục STAFF/ADMIN."
            )

        if user.deleted_at is None:
            raise ValidationException("Tài khoản owner này chưa bị xóa mềm.")

        try:
            now = utc_now()
            user.deleted_at = None
            user.deleted_by_id = None
            user.deletion_reason = None
            user.is_active = user._normalized_approval_status() == User.APPROVAL_ACTIVE

            owned_workspaces = Workspace.query.join(
                WorkspaceMember,
                (WorkspaceMember.workspace_id == Workspace.id)
                & (WorkspaceMember.user_id == user.id)
                & (WorkspaceMember.role == "owner")
            ).filter(Workspace.deleted_at.isnot(None)).all()

            workspace_names = []
            for workspace in owned_workspaces:
                workspace.deleted_at = None
                workspace.deleted_by_id = None
                workspace.deletion_reason = None
                workspace.updated_at = now
                workspace_names.append(workspace.name)

            actor_display_name = get_activity_actor_display_name(actor)
            if workspace_names:
                workspace_list = ", ".join(workspace_names)
                description = (
                    f"{actor_display_name} đã khôi phục OWNER {user.username} "
                    f"và các workspace liên quan: {workspace_list}."
                )
            else:
                description = (
                    f"{actor_display_name} đã khôi phục OWNER {user.username}; "
                    "không tìm thấy workspace deleted liên quan."
                )

            UserService._log_user_action(
                actor=actor,
                action="RESTORE_OWNER_WORKSPACE",
                description=description,
                target_user=user,
            )
            db.session.commit()
            return user
        except Exception:
            db.session.rollback()
            raise
