from flask import jsonify, redirect, render_template, request, url_for, abort

from core.auth.permissions import can_manage_users, is_owner
from core.exceptions import BusinessException, ValidationException
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
    _require_manager()
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
    return render_template(
        'user/index.html',
        users=users,
        q=query_text,
        sort_by=sort_by,
        sort_dir=sort_dir,
        role_labels=UserService.ROLE_LABELS,
        available_roles=UserService.get_available_roles(),
    )


@user_bp.route('/users/pending')
def pending():
    current_user = _require_owner()
    page, per_page = get_pagination_params()
    users = UserService.pending_paginated(page=page, per_page=per_page)
    return render_template(
        'user/pending.html',
        users=users,
        current_user=current_user,
        role_labels=UserService.ROLE_LABELS,
    )


@user_bp.route('/users/<int:user_id>/approve', methods=['POST'])
def approve(user_id):
    actor = _require_owner()
    try:
        user = UserService.approve_pending_user(actor=actor, user_id=user_id)
        message = f"Đã duyệt tài khoản {user.username}."
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
    return redirect(url_for('user.pending'))


@user_bp.route('/users/<int:user_id>/reject', methods=['POST'])
def reject(user_id):
    actor = _require_owner()
    try:
        user = UserService.reject_pending_user(actor=actor, user_id=user_id)
        message = f"Đã từ chối tài khoản {user.username}."
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
    return redirect(url_for('user.pending'))


@user_bp.route('/users/create', methods=['GET', 'POST'])
def create():
    _require_manager()
    errors = {}
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
            return _render_or_json_error('user/create.html', {'form_data': form_data, 'available_roles': UserService.get_available_roles()}, errors)

        try:
            actor = AuthService.require_manager_user()
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
            return render_template('user/create.html', form_data=form_data, errors=errors, available_roles=UserService.get_available_roles())
        except BusinessException as e:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': e.message}), e.status_code
            NotificationService.flash_error(e.message)
            return render_template('user/create.html', form_data=form_data, errors={'general': e.message}, available_roles=UserService.get_available_roles())

    return render_template('user/create.html', form_data=form_data, available_roles=UserService.get_available_roles())


@user_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
def edit(user_id):
    _require_manager()
    user = UserService._get_user_or_404(user_id)
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
        validator = UserValidator()
        validation = validator.validate_update(form_data)
        if not validation.success:
            errors = validation.field_errors
            return _render_or_json_error('user/edit.html', {'user': user, 'form_data': form_data, 'available_roles': UserService.get_available_roles()}, errors)

        try:
            actor = AuthService.require_manager_user()
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
            return render_template('user/edit.html', user=user, form_data=form_data, errors=errors, available_roles=UserService.get_available_roles())
        except BusinessException as e:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': e.message}), e.status_code
            NotificationService.flash_error(e.message)
            return render_template('user/edit.html', user=user, form_data=form_data, errors={'general': e.message}, available_roles=UserService.get_available_roles())

    return render_template('user/edit.html', user=user, form_data=form_data, available_roles=UserService.get_available_roles())


@user_bp.route('/users/<int:user_id>/reset-password', methods=['GET', 'POST'])
def reset_password(user_id):
    _require_manager()
    user = UserService._get_user_or_404(user_id)
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
            actor = AuthService.require_manager_user()
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
