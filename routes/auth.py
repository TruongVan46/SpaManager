# routes/auth.py
from flask import render_template, request, jsonify, redirect, url_for
from routes import auth_bp
from services.auth_service import AuthService

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # If already logged in, redirect to index
    if AuthService.is_authenticated():
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        # Accept JSON requests (AJAX)
        data = request.get_json() or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        remember = bool(data.get('remember', False))

        success, user = AuthService.login(username, password, remember=remember)
        if success:
            # Safe redirect extraction
            next_url = request.args.get('next') or url_for('dashboard.index')
            return jsonify(
                success=True,
                redirect=next_url,
                message=f"Xin chào, {user.full_name}"
            )
        else:
            return jsonify(success=False, message="Sai tên đăng nhập hoặc mật khẩu."), 401

    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
    AuthService.logout()
    return redirect(url_for('auth.login', logout=1))

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
    else:
        # Secure message returned on backend API
        return jsonify(success=False, message=message), 400

@auth_bp.route('/profile', methods=['GET', 'POST'])
def profile():
    user = AuthService.get_current_user()
    if not user:
        return redirect(url_for('auth.login', next=request.full_path))

    if request.method == 'POST':
        # Accept multipart form upload
        full_name = request.form.get('full_name', '').strip()
        avatar_file = request.files.get('avatar')

        success, message = AuthService.update_profile(user, full_name, avatar_file)
        if success:
            return jsonify(success=True, message=message)
        else:
            return jsonify(success=False, message=message), 400

    # GET request
    from core.auth.dto import UserDTO
    user_dto = UserDTO.from_model(user)
    return render_template('auth/profile.html', user=user_dto)
