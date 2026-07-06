from urllib.parse import urlparse, urljoin

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from core.auth.constants import AUTH_SESSION_KEY
from core.auth.google_oauth import (
    handle_google_callback_skeleton,
    is_google_auth_available,
    start_google_authorization,
)
from core.csrf import clear_csrf_token
from core.exceptions import AuthenticationException
from routes import auth_bp
from services.auth_service import AuthService
from services.login_rate_limit_service import get_request_ip


def _is_safe_next_url(target):
    if not target:
        return False

    base_url = request.host_url
    test_url = urljoin(base_url, target)
    return urlparse(test_url).scheme in ("http", "https") and urlparse(base_url).netloc == urlparse(test_url).netloc


def _clear_stale_session():
    session.pop(AUTH_SESSION_KEY, None)
    clear_csrf_token()


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    denied_notice = request.args.get('denied') == '1'
    current_user = AuthService.get_current_user()
    if current_user:
        if getattr(current_user, "can_access_app", False):
            from core.auth.permissions import is_approval_owner
            if is_approval_owner(current_user):
                return redirect(url_for('approval.pending'))
            return redirect(url_for('dashboard.index'))
        if getattr(current_user, "is_pending_approval", False):
            return redirect('/auth/pending')
        denied_notice = True
        _clear_stale_session()

    if AuthService.is_authenticated():
        from core.auth.permissions import is_approval_owner
        if is_approval_owner(AuthService.get_current_user()):
            return redirect(url_for('approval.pending'))
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        data = request.get_json() or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        remember = bool(data.get('remember', False))
        request_ip = get_request_ip(request)

        try:
            success, user = AuthService.login(username, password, remember=remember, request_ip=request_ip)
        except AuthenticationException as exc:
            payload = {
                "success": False,
                "message": exc.message,
            }
            if exc.code == "AUTH_ACCOUNT_PENDING":
                payload["pending"] = True
                payload["redirect"] = "/auth/pending"
            return jsonify(payload), exc.status_code
        if success:
            from core.auth.permissions import is_approval_owner
            if is_approval_owner(user):
                next_url = url_for('approval.pending')
            else:
                next_target = request.args.get('next')
                next_url = next_target if _is_safe_next_url(next_target) else url_for('dashboard.index')
            return jsonify(
                success=True,
                redirect=next_url,
                message=f"Xin chào, {user.full_name}"
            )
        return jsonify(success=False, message="Sai tên đăng nhập hoặc mật khẩu."), 401

    return render_template(
        'auth/login.html',
        denied_notice=denied_notice,
        google_auth_available=is_google_auth_available(),
    )


@auth_bp.route('/auth/pending', methods=['GET'])
@auth_bp.route('/pending', methods=['GET'])
def pending():
    current_user = AuthService.get_current_user()
    if not current_user:
        return redirect(url_for('auth.login'))

    if getattr(current_user, "can_access_app", False):
        return redirect(url_for('dashboard.index'))

    if not getattr(current_user, "is_pending_approval", False):
        _clear_stale_session()
        return redirect(url_for('auth.login', denied=1))

    return render_template('auth/pending.html', user=current_user)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    AuthService.logout()
    return redirect(url_for('auth.login', logout=1))


@auth_bp.route('/auth/google/start', methods=['GET'])
def google_start():
    response = start_google_authorization()
    if response is not None:
        return response

    if not is_google_auth_available():
        flash("Đăng nhập Google hiện chưa được bật.", "warning")
    else:
        flash("Google login đang được chuẩn bị.", "info")
    return redirect(url_for('auth.login'))


@auth_bp.route('/auth/google/callback', methods=['GET'])
def google_callback():
    error = request.args.get('error')
    error_description = request.args.get('error_description')
    return handle_google_callback_skeleton(error=error, error_description=error_description)


@auth_bp.route('/change-password', methods=['POST'])
def change_password():
    user = AuthService.get_current_user()
    if not user:
        return jsonify(success=False, message="Phiên làm việc đã hết hạn. Vui lòng đăng nhập lại."), 401

    data = request.get_json() or {}
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')

    success, message = AuthService.change_password(user, current_password, new_password, confirm_password)
    if success:
        return jsonify(success=True, message=message)
    return jsonify(success=False, message=message), 400


@auth_bp.route('/profile', methods=['GET', 'POST'])
def profile():
    user = AuthService.get_current_user()
    if not user:
        return redirect(url_for('auth.login', next=request.full_path))

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        avatar_file = request.files.get('avatar')

        success, message = AuthService.update_profile(user, full_name, avatar_file)
        if success:
            return jsonify(success=True, message=message)
        return jsonify(success=False, message=message), 400

    from core.auth.dto import UserDTO

    user_dto = UserDTO.from_model(user)
    return render_template('auth/profile.html', user=user_dto)
