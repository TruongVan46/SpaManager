from flask import current_app, jsonify, make_response, redirect, render_template, request, url_for, abort

from core.auth.permissions import is_approval_owner
from core.exceptions import BusinessException, ValidationException
from routes import approval_bp
from services.auth_service import AuthService
from services.notification_service import NotificationService
from services.user_service import UserService
from services.purge_request_service import (
    PurgeRequestService,
    PurgeRequestServiceError,
)
from config import (
    is_permanent_purge_execution_enabled,
    is_permanent_purge_ui_enabled,
)
from utils.pagination import get_pagination_params
from services.purge_service import (
    PurgeAuthorizationError,
    PurgeCommitOutcomeUnknownError,
    PurgeConflictError,
    PurgeExecutionDisabledError,
    PurgeExecutionError,
    PurgeService,
)


def _require_approval_owner():
    current_user = AuthService.get_current_active_user()
    if not current_user:
        abort(401)
    if not is_approval_owner(current_user):
        abort(403)
    return current_user


def _require_purge_ui():
    if not is_permanent_purge_ui_enabled(current_app.config.get("PERMANENT_PURGE_UI_ENABLED")):
        abort(404)
    return _require_approval_owner()


def _require_purge_execution():
    if not is_permanent_purge_ui_enabled(current_app.config.get("PERMANENT_PURGE_UI_ENABLED")):
        abort(404)
    if not is_permanent_purge_execution_enabled(current_app.config.get("PERMANENT_PURGE_EXECUTION_ENABLED")):
        abort(404)
    return _require_approval_owner()


def _no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _purge_error(error):
    NotificationService.flash_error(error.message)
    return redirect(url_for("approval.purge_requests"))


def _load_execution_summary(request_id):
    try:
        summary = PurgeRequestService.get_summary(request_id)
    except PurgeRequestServiceError as error:
        abort(404 if error.code == "NOT_FOUND" else 409)
    try:
        workspace_target = PurgeRequestService.get_workspace_target(summary.workspace_id)
    except PurgeRequestServiceError as error:
        abort(404 if error.code == "NOT_FOUND" else 409)
    return summary, workspace_target


def _execution_is_basic_candidate(summary, workspace_target, actor):
    return (
        summary.status == "APPROVED"
        and summary.requested_by_id != actor.id
        and summary.invalidated_at is None
        and not summary.outcome_unknown
        and summary.manifest_valid
        and not workspace_target.get("purged")
    )


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


@approval_bp.route('/approval/purge-requests')
def purge_requests():
    actor = _require_purge_ui()
    page, per_page = get_pagination_params()
    page_obj = PurgeRequestService.list_summaries(page=page, per_page=per_page)
    target = None
    workspace_id = request.args.get("workspace_id", type=int)
    if workspace_id:
        try:
            target = PurgeRequestService.get_workspace_target(workspace_id)
        except PurgeRequestServiceError:
            target = None
    response = make_response(render_template(
        "approval/purge_requests.html",
        current_user=actor,
        pagination=page_obj,
        summaries=page_obj.items,
        workspace_target=target,
    ))
    return _no_cache(response)


@approval_bp.route('/approval/purge-requests/<int:request_id>')
def purge_request_detail(request_id):
    actor = _require_purge_ui()
    try:
        summary = PurgeRequestService.get_summary(request_id)
    except PurgeRequestServiceError as error:
        abort(404 if error.code == "NOT_FOUND" else 409)
    workspace_target = None
    try:
        workspace_target = PurgeRequestService.get_workspace_target(summary.workspace_id)
    except PurgeRequestServiceError:
        pass
    response = make_response(render_template(
        "approval/purge_request_detail.html", current_user=actor, summary=summary,
        workspace_target=workspace_target,
    ))
    return _no_cache(response)


@approval_bp.route('/approval/purge-requests/<int:request_id>/execute/confirm', methods=['GET'])
def confirm_purge_request(request_id):
    actor = _require_purge_execution()
    summary, workspace_target = _load_execution_summary(request_id)
    if summary.requested_by_id == actor.id:
        abort(403)
    if not _execution_is_basic_candidate(summary, workspace_target, actor):
        abort(409)
    response = make_response(render_template(
        "approval/purge_request_execute.html",
        current_user=actor,
        summary=summary,
        workspace_target=workspace_target,
        confirmation_phrase=f"PURGE WORKSPACE {summary.workspace_id} REQUEST {summary.id}",
    ))
    return _no_cache(response)


@approval_bp.route('/approval/purge-requests/<int:request_id>/execute', methods=['POST'])
def execute_purge_request(request_id):
    actor = _require_purge_execution()
    summary, workspace_target = _load_execution_summary(request_id)
    if summary.requested_by_id == actor.id:
        abort(403)
    if not _execution_is_basic_candidate(summary, workspace_target, actor):
        NotificationService.flash_error("Purge request is no longer executable.")
        return redirect(url_for("approval.purge_request_detail", request_id=request_id))

    expected_phrase = f"PURGE WORKSPACE {summary.workspace_id} REQUEST {summary.id}"
    supplied_phrase = request.form.get("confirmation_phrase")
    if not isinstance(supplied_phrase, str) or supplied_phrase.strip() != expected_phrase:
        NotificationService.flash_error("Typed confirmation is invalid.")
        return redirect(url_for("approval.purge_request_detail", request_id=request_id))

    try:
        result = PurgeService.execute_workspace_purge(
            request_id=summary.id,
            workspace_id=summary.workspace_id,
            executor_user_id=actor.id,
        )
    except PurgeCommitOutcomeUnknownError:
        NotificationService.flash_error("Purge outcome requires investigation; no retry was attempted.")
    except PurgeExecutionDisabledError:
        NotificationService.flash_error("Permanent purge execution is disabled.")
    except PurgeAuthorizationError:
        NotificationService.flash_error("Actor is not authorized to execute this purge request.")
    except PurgeConflictError as error:
        NotificationService.flash_error(str(error))
    except PurgeExecutionError:
        NotificationService.flash_error("Purge execution failed; review the request before taking further action.")
    else:
        NotificationService.flash_success(
            f"Purge request {result.request_id} completed."
        )
    return redirect(url_for("approval.purge_request_detail", request_id=request_id))


@approval_bp.route('/approval/workspaces/<int:workspace_id>/purge-request', methods=['POST'])
def create_purge_request(workspace_id):
    actor = _require_purge_ui()
    try:
        summary = PurgeRequestService.create_purge_request(
            workspace_id=workspace_id,
            requester_user_id=actor.id,
            confirmation_phrase=request.form.get("confirmation_phrase"),
        )
        NotificationService.flash_success("Purge request đã được tạo và chờ review.")
        return redirect(url_for("approval.purge_request_detail", request_id=summary.id))
    except PurgeRequestServiceError as error:
        return _purge_error(error)


@approval_bp.route('/approval/purge-requests/<int:request_id>/approve', methods=['POST'])
def approve_purge_request(request_id):
    actor = _require_purge_ui()
    try:
        summary = PurgeRequestService.approve_purge_request(
            request_id=request_id, approver_user_id=actor.id,
            confirmation_phrase=request.form.get("confirmation_phrase"),
        )
        NotificationService.flash_success("Purge request đã được approve; execution chưa được mở.")
        return redirect(url_for("approval.purge_request_detail", request_id=summary.id))
    except PurgeRequestServiceError as error:
        return _purge_error(error)


@approval_bp.route('/approval/purge-requests/<int:request_id>/reject', methods=['POST'])
def reject_purge_request(request_id):
    actor = _require_purge_ui()
    try:
        summary = PurgeRequestService.reject_purge_request(
            request_id=request_id, rejector_user_id=actor.id,
            reason=request.form.get("reason"),
        )
        NotificationService.flash_success("Purge request đã bị reject và được lưu audit.")
        return redirect(url_for("approval.purge_request_detail", request_id=summary.id))
    except PurgeRequestServiceError as error:
        return _purge_error(error)


@approval_bp.route('/approval/purge-requests/<int:request_id>/cancel', methods=['POST'])
def cancel_purge_request(request_id):
    actor = _require_purge_ui()
    try:
        summary = PurgeRequestService.cancel_purge_request(
            request_id=request_id, requester_user_id=actor.id,
            reason=request.form.get("reason"),
        )
        NotificationService.flash_success("Purge request đã được cancel.")
        return redirect(url_for("approval.purge_request_detail", request_id=summary.id))
    except PurgeRequestServiceError as error:
        return _purge_error(error)
