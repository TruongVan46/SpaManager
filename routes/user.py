from flask import jsonify, redirect, render_template, request, url_for, abort

from core.auth.permissions import can_manage_users, is_owner, is_admin
from core.exceptions import BusinessException, NotFoundException, PermissionDeniedException, ValidationException
from routes import user_bp
from services.auth_service import AuthService
from services.notification_service import NotificationService
from services.user_service import UserService
from utils.pagination import get_pagination_params
from validators.user_validator import UserValidator


def _require_manager():
    return AuthService.require_manager_user()


def _require_owner():
    current_user = _require_manager()
    if not is_owner(current_user):
        abort(403)
    return current_user


def _extract_payload():
    if request.is_json:
        return request.get_json() or {}
    return request.form.to_dict()


def _get_available_roles_for_actor(actor):
    """
    Return the list of (value, label) role tuples the actor is allowed to assign.
    - OWNER can assign ADMIN, STAFF
    - ADMIN can assign STAFF only
    - Others: no roles (but they should not reach this point anyway)
    """
    if is_owner(actor):
        # OWNER can only assign ADMIN and STAFF (not OWNER or APPROVAL_OWNER)
        return [(r, label) for r, label in UserService.get_available_roles()
                if r not in ("OWNER", "APPROVAL_OWNER")]
    if is_admin(actor):
        # ADMIN may only assign STAFF
        return [(r, label) for r, label in UserService.get_available_roles()
                if r not in ("OWNER", "ADMIN", "APPROVAL_OWNER")]
    return []


@user_bp.before_request
def _require_user_management_permission():
    current_user = AuthService.get_current_active_user()
    if not current_user:
        abort(401)
    if not can_manage_users(current_user):
        abort(403)


def _render_or_json_error(template_name, context, errors, status_code=400):
    first_error_message = next(iter(errors.values()), "Dữ liệu người dùng không hợp lệ.")
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": False, "message": first_error_message, "fields": errors}), status_code
    context = dict(context)
    context["errors"] = errors
    return render_template(template_name, **context), status_code


@user_bp.route('/users')
def index():
    actor = _require_manager()
    if actor.role == "OWNER":
        from services.workspace_service import WorkspaceService
        repaired = WorkspaceService.repair_legacy_owner_created_memberships(actor)
        if repaired > 0:
            from extensions import db
            db.session.commit()

    query_text = request.args.get('q', '').strip()
    sort_by = request.args.get('sort_by', 'created_at')
    sort_dir = request.args.get('sort_dir', 'desc')
    page, per_page = get_pagination_params()

    users = UserService.search_paginated(
        query_text=query_text,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    removed_users = UserService.search_removed_paginated(
        query_text=query_text,
        page=1,
        per_page=50,
    )
    reset_allowed = {
        user.id: UserService.can_reset_password(actor, user)
        for user in users.items
    }
    return render_template(
        'user/index.html',
        users=users,
        removed_users=removed_users,
        q=query_text,
        sort_by=sort_by,
        sort_dir=sort_dir,
        role_labels=UserService.ROLE_LABELS,
        available_roles=_get_available_roles_for_actor(actor),
        reset_allowed=reset_allowed,
    )


@user_bp.route('/users/pending')
def pending():
    current_user = AuthService.get_current_active_user()
    if not current_user:
        abort(401)
    from core.auth.permissions import is_approval_owner
    if is_approval_owner(current_user):
        return redirect(url_for('approval.pending'))
    abort(403)


@user_bp.route('/users/<int:user_id>/approve', methods=['POST'])
def approve(user_id):
    abort(403)


@user_bp.route('/users/<int:user_id>/reject', methods=['POST'])
def reject(user_id):
    abort(403)


@user_bp.route('/users/create', methods=['GET', 'POST'])
def create():
    actor = _require_manager()
    errors = {}
    available_roles = _get_available_roles_for_actor(actor)
    form_data = {
        'username': '',
        'full_name': '',
        'email': '',
        'role': 'STAFF',
        'is_active': True,
    }

    if request.method == 'POST':
        payload = _extract_payload()
        form_data = {
            'username': (payload.get('username') or '').strip(),
            'full_name': (payload.get('full_name') or '').strip(),
            'email': (payload.get('email') or '').strip(),
            'role': (payload.get('role') or 'STAFF').strip().upper(),
            'is_active': str(payload.get('is_active', '0')).lower() in ('1', 'true', 'yes', 'on'),
        }

        # Prevent role elevation: only check if the submitted role is a known valid role.
        # Unknown/invalid roles are passed through to the validator for proper error messages.
        allowed_role_values = [r for r, _ in available_roles]
        all_known_roles = [r for r, _ in UserService.get_available_roles()]
        if form_data['role'] in all_known_roles and form_data['role'] not in allowed_role_values:
            errors['role'] = 'Bạn không có quyền gán vai trò này.'
            return _render_or_json_error('user/create.html', {'form_data': form_data, 'available_roles': available_roles}, errors)

        validator = UserValidator()
        validation = validator.validate_create({
            **payload,
            'username': form_data['username'],
            'full_name': form_data['full_name'],
            'email': form_data['email'],
            'role': form_data['role'],
        })
        if not validation.success:
            errors = validation.field_errors
            return _render_or_json_error('user/create.html', {'form_data': form_data, 'available_roles': available_roles}, errors)

        try:
            UserService.create_user(
                actor=actor,
                username=form_data['username'],
                full_name=form_data['full_name'],
                password=payload.get('password') or '',
                email=form_data['email'],
                role=form_data['role'],
                is_active=form_data['is_active'],
            )
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'Đã tạo người dùng thành công.'})
            NotificationService.flash_success('Đã tạo người dùng thành công.')
            return redirect(url_for('user.index'))
        except ValidationException as e:
            errors = getattr(e, 'field_errors', {}) or {}
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': e.message, 'fields': errors}), e.status_code
            NotificationService.flash_error(e.message)
            return render_template('user/create.html', form_data=form_data, errors=errors, available_roles=available_roles)
        except BusinessException as e:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': e.message}), e.status_code
            NotificationService.flash_error(e.message)
            return render_template('user/create.html', form_data=form_data, errors={'general': e.message}, available_roles=available_roles)

    return render_template('user/create.html', form_data=form_data, available_roles=available_roles)


@user_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
def edit(user_id):
    actor = _require_manager()
    user = UserService._get_workspace_scoped_user_or_404(user_id)
    if user.role == 'APPROVAL_OWNER':
        abort(403)
    available_roles = _get_available_roles_for_actor(actor)
    errors = {}
    form_data = {
        'username': user.username,
        'full_name': user.full_name,
        'email': user.email or '',
        'role': user.role,
    }

    if request.method == 'POST':
        payload = _extract_payload()
        form_data = {
            'username': (payload.get('username') or '').strip(),
            'full_name': (payload.get('full_name') or '').strip(),
            'email': (payload.get('email') or '').strip(),
            'role': (payload.get('role') or '').strip().upper(),
        }

        # Prevent role elevation: only check if the submitted role is different from the user's current role
        # and is a known valid role that exceeds the actor's assignment permission.
        allowed_role_values = [r for r, _ in available_roles]
        all_known_roles = [r for r, _ in UserService.get_available_roles()]
        if form_data['role'] != user.role and form_data['role'] in all_known_roles and form_data['role'] not in allowed_role_values:
            errors['role'] = 'Bạn không có quyền gán vai trò này.'
            return _render_or_json_error('user/edit.html', {'user': user, 'form_data': form_data, 'available_roles': available_roles}, errors)

        validator = UserValidator()
        validation = validator.validate_update(form_data)
        if not validation.success:
            errors = validation.field_errors
            return _render_or_json_error('user/edit.html', {'user': user, 'form_data': form_data, 'available_roles': available_roles}, errors)

        try:
            UserService.update_user(
                actor=actor,
                user_id=user_id,
                username=form_data['username'],
                full_name=form_data['full_name'],
                email=form_data['email'],
                role=form_data['role'],
            )
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'Đã cập nhật người dùng thành công.'})
            NotificationService.flash_success('Đã cập nhật người dùng thành công.')
            return redirect(url_for('user.index'))
        except ValidationException as e:
            errors = getattr(e, 'field_errors', {}) or {}
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': e.message, 'fields': errors}), e.status_code
            NotificationService.flash_error(e.message)
            return render_template('user/edit.html', user=user, form_data=form_data, errors=errors, available_roles=available_roles)
        except BusinessException as e:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': e.message}), e.status_code
            NotificationService.flash_error(e.message)
            return render_template('user/edit.html', user=user, form_data=form_data, errors={'general': e.message}, available_roles=available_roles)

    return render_template('user/edit.html', user=user, form_data=form_data, available_roles=available_roles)


@user_bp.route('/users/<int:user_id>/reset-password', methods=['GET', 'POST'])
def reset_password(user_id):
    actor = _require_manager()
    try:
        UserService._ensure_reset_actor_can_manage(actor)
        UserService._ensure_reset_target_is_not_protected(user_id)
        user, _membership = UserService._authorize_workspace_user_action(
            actor, user_id, "reset"
        )
    except PermissionDeniedException:
        abort(403)
    errors = {}
    form_data = {'new_password': '', 'confirm_password': ''}

    if request.method == 'POST':
        payload = _extract_payload()
        form_data = {
            'new_password': payload.get('new_password', ''),
            'confirm_password': payload.get('confirm_password', ''),
        }
        validator = UserValidator()
        validation = validator.validate_reset_password(form_data)
        if not validation.success:
            errors = validation.field_errors
            return _render_or_json_error('user/reset_password.html', {'user': user, 'form_data': form_data}, errors)

        try:
            UserService.reset_password(actor=actor, user_id=user_id, new_password=form_data['new_password'])
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'Đã đặt lại mật khẩu thành công.'})
            NotificationService.flash_success('Đã đặt lại mật khẩu thành công.')
            return redirect(url_for('user.index'))
        except ValidationException as e:
            errors = getattr(e, 'field_errors', {}) or {}
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': e.message, 'fields': errors}), e.status_code
            NotificationService.flash_error(e.message)
            return render_template('user/reset_password.html', user=user, form_data=form_data, errors=errors)
        except BusinessException as e:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': e.message}), e.status_code
            NotificationService.flash_error(e.message)
            return render_template('user/reset_password.html', user=user, form_data=form_data, errors={'general': e.message})

    return render_template('user/reset_password.html', user=user, form_data=form_data)


@user_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
def toggle_active(user_id):
    actor = _require_manager()
    user = UserService._get_workspace_scoped_user_or_404(user_id)
    if user.role == 'APPROVAL_OWNER':
        abort(403)
    payload = _extract_payload()
    desired_active_raw = payload.get('is_active', '0')
    desired_active = str(desired_active_raw).lower() in ('1', 'true', 'yes', 'on')

    try:
        UserService.toggle_active(actor=actor, user_id=user_id, is_active=desired_active)
        message = 'Đã kích hoạt người dùng thành công.' if desired_active else 'Đã vô hiệu hóa người dùng thành công.'
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': message})
        NotificationService.flash_success(message)
    except ValidationException as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': e.message, 'fields': getattr(e, 'field_errors', {}) or {}}), e.status_code
        NotificationService.flash_error(e.message)
    except BusinessException as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': e.message}), e.status_code
        NotificationService.flash_error(e.message)
    return redirect(url_for('user.index'))


@user_bp.route('/users/<int:user_id>/soft-delete', methods=['POST'])
def soft_delete(user_id):
    actor = _require_manager()
    payload = _extract_payload()
    reason = payload.get('reason', '').strip() or None
    try:
        UserService.soft_delete_user(actor=actor, user_id=user_id, reason=reason)
        NotificationService.flash_success('Đã xóa mềm nhân viên khỏi workspace.')
    except (ValidationException, NotFoundException, BusinessException) as e:
        NotificationService.flash_error(e.message)
    return redirect(url_for('user.index'))


@user_bp.route('/users/<int:user_id>/restore', methods=['POST'])
def restore(user_id):
    actor = _require_manager()
    try:
        UserService.restore_user(actor=actor, user_id=user_id)
        NotificationService.flash_success('Đã khôi phục nhân viên vào workspace.')
    except (ValidationException, NotFoundException, BusinessException) as e:
        NotificationService.flash_error(e.message)
    return redirect(url_for('user.index'))
