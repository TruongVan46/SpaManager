from flask import jsonify, redirect, render_template, request, url_for, abort

from core.auth.permissions import is_approval_owner
from core.exceptions import BusinessException, ValidationException
from routes import approval_bp
from services.auth_service import AuthService
from services.notification_service import NotificationService
from services.user_service import UserService
from utils.pagination import get_pagination_params


def _require_approval_owner():
    current_user = AuthService.get_current_active_user()
    if not current_user:
        abort(401)
    if not is_approval_owner(current_user):
        abort(403)
    return current_user


@approval_bp.route('/approval/pending')
def pending():
    current_user = _require_approval_owner()
    page, per_page = get_pagination_params()
    users = UserService.list_approval_accounts(status='pending', page=page, per_page=per_page)
    return render_template(
        'approval/accounts.html',
        users=users,
        current_user=current_user,
        current_status='pending'
    )


@approval_bp.route('/approval/accounts')
def accounts():
    current_user = _require_approval_owner()
    status = request.args.get('status', 'pending')
    if status not in ('pending', 'active', 'rejected', 'disabled', 'deleted'):
        status = 'pending'

    page, per_page = get_pagination_params()
    users = UserService.list_approval_accounts(status=status, page=page, per_page=per_page)
    return render_template(
        'approval/accounts.html',
        users=users,
        current_user=current_user,
        current_status=status
    )


@approval_bp.route('/approval/users/<int:user_id>/approve', methods=['POST'])
def approve(user_id):
    actor = _require_approval_owner()
    try:
        user = UserService.approve_user(actor=actor, user_id=user_id)
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
    return redirect(url_for('approval.accounts', status='active'))


@approval_bp.route('/approval/users/<int:user_id>/reject', methods=['POST'])
def reject(user_id):
    actor = _require_approval_owner()
    try:
        user = UserService.reject_user(actor=actor, user_id=user_id)
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
    return redirect(url_for('approval.accounts', status='rejected'))


@approval_bp.route('/approval/users/<int:user_id>/disable', methods=['POST'])
def disable(user_id):
    actor = _require_approval_owner()
    try:
        user = UserService.disable_user(actor=actor, user_id=user_id)
        message = f"Đã vô hiệu hóa tài khoản {user.username}."
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
    return redirect(url_for('approval.accounts', status='disabled'))


@approval_bp.route('/approval/users/<int:user_id>/enable', methods=['POST'])
def enable(user_id):
    actor = _require_approval_owner()
    try:
        user = UserService.enable_user(actor=actor, user_id=user_id)
        message = f"Đã kích hoạt lại tài khoản {user.username}."
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
    return redirect(url_for('approval.accounts', status='active'))


@approval_bp.route('/approval/users/<int:user_id>/soft-delete', methods=['POST'])
def soft_delete_account(user_id):
    actor = _require_approval_owner()
    reason = request.form.get('reason', '').strip() or "Xóa từ cổng quản trị hệ thống"
    try:
        user = UserService.soft_delete_account(actor=actor, user_id=user_id, reason=reason)
        message = f"Đã xóa mềm tài khoản {user.username}."
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
    return redirect(url_for('approval.accounts', status='deleted'))


@approval_bp.route('/approval/users/<int:user_id>/restore', methods=['POST'])
def restore_account(user_id):
    actor = _require_approval_owner()
    try:
        user = UserService.restore_account(actor=actor, user_id=user_id)
        message = f"Đã khôi phục tài khoản {user.username}."
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': message})
        NotificationService.flash_success(message)
        target_status = user._normalized_approval_status()
        if target_status not in ('pending', 'active', 'rejected', 'disabled'):
            target_status = 'active'
        return redirect(url_for('approval.accounts', status=target_status))
    except ValidationException as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': e.message, 'fields': getattr(e, 'field_errors', {}) or {}}), e.status_code
        NotificationService.flash_error(e.message)
    except BusinessException as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': e.message}), e.status_code
        NotificationService.flash_error(e.message)
    return redirect(url_for('approval.accounts', status='deleted'))


@approval_bp.route('/approval/users/<int:user_id>/soft-delete-owner-workspace', methods=['POST'])
def soft_delete_owner_workspace(user_id):
    actor = _require_approval_owner()
    reason = request.form.get('reason', '').strip() or "Xóa owner và workspace từ cổng quản trị"
    try:
        user = UserService.soft_delete_owner_workspace(actor=actor, user_id=user_id, reason=reason)
        message = f"Đã xóa mềm OWNER {user.username} và các workspace liên quan."
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': message})
        NotificationService.flash_success(message)
    except ValidationException as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': e.message, 'fields': getattr(e, 'field_errors', {}) or {}}), e.status_code
        NotificationService.flash_error(e.message)
        return redirect(url_for('approval.accounts', status='active'))
    except BusinessException as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': e.message}), e.status_code
        NotificationService.flash_error(e.message)
        return redirect(url_for('approval.accounts', status='active'))
    return redirect(url_for('approval.accounts', status='deleted'))


@approval_bp.route('/approval/users/<int:user_id>/restore-owner-workspace', methods=['POST'])
def restore_owner_workspace(user_id):
    actor = _require_approval_owner()
    try:
        user = UserService.restore_owner_workspace(actor=actor, user_id=user_id)
        message = f"Đã khôi phục OWNER {user.username} và xử lý các workspace cùng sự kiện xóa."
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': message})
        NotificationService.flash_success(message)
        target_status = user._normalized_approval_status()
        if target_status not in ('pending', 'active', 'rejected', 'disabled'):
            target_status = 'active'
        return redirect(url_for('approval.accounts', status=target_status))
    except ValidationException as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': e.message, 'fields': getattr(e, 'field_errors', {}) or {}}), e.status_code
        NotificationService.flash_error(e.message)
    except BusinessException as e:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': e.message}), e.status_code
        NotificationService.flash_error(e.message)
    return redirect(url_for('approval.accounts', status='deleted'))
