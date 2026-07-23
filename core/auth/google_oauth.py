import hashlib
import secrets

from flask import current_app, flash, has_app_context, has_request_context, redirect, session, url_for

from core.auth.constants import AUTH_SESSION_KEY, SESSION_REVOCATION_VERSION_KEY
from core.auth.enums import UserRole
from extensions import db
from models.user import User

try:
    from authlib.integrations.flask_client import OAuth
except ImportError:  # pragma: no cover - dependency may be absent in some local environments
    class OAuth:  # minimal local/test shim
        def __init__(self):
            self._clients = {}

        def init_app(self, app):
            app.extensions.setdefault("authlib_oauth", self)
            return self

        def register(self, **kwargs):
            name = kwargs.get("name")
            if name:
                self._clients[name] = kwargs
            return kwargs

        def create_client(self, name):
            return self._clients.get(name)


class GoogleIdentityError(ValueError):
    pass


oauth = OAuth()


def _get_app(app=None):
    if app is not None:
        return app
    if not has_app_context():
        return None
    return current_app._get_current_object()


def _is_config_valid(app):
    client_id = (app.config.get("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (app.config.get("GOOGLE_CLIENT_SECRET") or "").strip()
    return bool(client_id and client_secret)


def _ensure_state(app):
    state = app.extensions.setdefault("google_oauth", {})
    state.setdefault("initialized", False)
    state.setdefault("registered", False)
    state.setdefault("available", False)
    return state


def get_google_client(app=None):
    app = _get_app(app)
    if app is None:
        return None

    state = app.extensions.get("google_oauth", {})
    client = state.get("client")
    if client is not None:
        return client

    create_client = getattr(oauth, "create_client", None)
    if callable(create_client):
        try:
            client = create_client("google")
        except Exception:  # pragma: no cover - authlib/runtime specific
            client = None
        if client is not None:
            state["client"] = client
            return client

    client_attr = getattr(oauth, "google", None)
    if client_attr is not None:
        state["client"] = client_attr
        return client_attr

    return None


def build_google_redirect_uri(app=None):
    app = _get_app(app)
    if app is None:
        return None

    configured_uri = (app.config.get("GOOGLE_REDIRECT_URI") or "").strip()
    if configured_uri:
        return configured_uri

    if has_request_context():
        try:
            return url_for("auth.google_callback", _external=True)
        except RuntimeError:
            pass

    return "/auth/google/callback"


def init_google_oauth(app=None):
    app = _get_app(app)
    if app is None:
        return False

    state = _ensure_state(app)
    enabled = bool(app.config.get("GOOGLE_AUTH_ENABLED"))
    valid = _is_config_valid(app)
    state["enabled"] = enabled
    state["valid"] = valid
    state["available"] = False

    if not (enabled and valid):
        return False

    if not state["initialized"]:
        oauth.init_app(app)
        state["initialized"] = True

    if not state["registered"]:
        register_kwargs = {
            "name": "google",
            "client_id": app.config.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": app.config.get("GOOGLE_CLIENT_SECRET", ""),
            "server_metadata_url": app.config.get("GOOGLE_DISCOVERY_URL", ""),
            "client_kwargs": {
                "scope": " ".join(app.config.get("GOOGLE_SCOPES", [])),
            },
        }
        redirect_uri = build_google_redirect_uri(app)
        if redirect_uri:
            register_kwargs["redirect_uri"] = redirect_uri
        oauth.register(**register_kwargs)
        state["registered"] = True

    state["client"] = get_google_client(app)
    state["available"] = True
    return True


def is_google_auth_available(app=None):
    app = _get_app(app)
    if app is None:
        return False

    if not bool(app.config.get("GOOGLE_AUTH_ENABLED")):
        return False
    if not _is_config_valid(app):
        return False

    state = app.extensions.get("google_oauth", {})
    if state.get("available") and state.get("registered"):
        return True

    return init_google_oauth(app)


def start_google_authorization(app=None):
    app = _get_app(app)
    if app is None or not is_google_auth_available(app):
        return None

    client = get_google_client(app)
    if client is None or not hasattr(client, "authorize_redirect"):
        return None

    redirect_uri = build_google_redirect_uri(app)
    try:
        return client.authorize_redirect(redirect_uri)
    except Exception:  # pragma: no cover - keep login safe if client setup fails
        return None


def extract_google_identity(token=None, profile=None, app=None):
    app = _get_app(app)
    payload = profile or {}
    if not payload and isinstance(token, dict):
        for key in ("userinfo", "id_token_claims", "claims"):
            if isinstance(token.get(key), dict):
                payload = token[key]
                break
        if not payload:
            payload = token

    subject = str(payload.get("sub") or payload.get("oauth_id") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    email_verified = payload.get("email_verified")

    if not subject:
        raise GoogleIdentityError("missing_sub")
    if not email:
        raise GoogleIdentityError("missing_email")
    if email_verified is not True:
        raise GoogleIdentityError("email_not_verified")

    allowed_domain = ""
    if app is not None:
        allowed_domain = (app.config.get("GOOGLE_ALLOWED_DOMAIN") or "").strip().lower().lstrip("@")
    email_domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    if allowed_domain and email_domain != allowed_domain:
        raise GoogleIdentityError("domain_not_allowed")

    return {
        "sub": subject,
        "email": email,
        "email_verified": True,
        "name": str(payload.get("name") or "").strip(),
        "picture": str(payload.get("picture") or "").strip(),
        "hd": str(payload.get("hd") or email_domain).strip().lower(),
    }


def _extract_identity_from_callback(client, app):
    if client is None or not hasattr(client, "authorize_access_token"):
        raise GoogleIdentityError("client_unavailable")

    token = client.authorize_access_token()
    profile = None
    parse_id_token = getattr(client, "parse_id_token", None)
    if callable(parse_id_token):
        try:
            profile = parse_id_token(token)
        except TypeError:
            profile = parse_id_token(token, None)
    return extract_google_identity(token=token, profile=profile, app=app)


def _build_google_username(subject):
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]
    return f"google_{digest}"


def _rotate_session_csrf():
    from core.csrf import rotate_csrf_token

    rotate_csrf_token()


def _set_pending_session(user):
    session[AUTH_SESSION_KEY] = user.id
    session[SESSION_REVOCATION_VERSION_KEY] = int(user.session_revocation_version)
    _rotate_session_csrf()


def _login_active_google_user(user):
    from services.auth_service import AuthService
    from services.workspace_service import WorkspaceService
    from core.auth.permissions import is_approval_owner

    if not is_approval_owner(user) and not WorkspaceService.ensure_authenticated_workspace_access(user):
        AuthService.clear_authentication_session()
        flash("Tài khoản hiện không có quyền truy cập vào cơ sở nào.", "warning")
        return redirect(url_for("auth.login"))

    session[AUTH_SESSION_KEY] = user.id
    session[SESSION_REVOCATION_VERSION_KEY] = int(user.session_revocation_version)
    session.permanent = False
    _rotate_session_csrf()

    from utils.timezone_utils import utc_now

    user.last_login = utc_now()
    db.session.commit()
    AuthService.on_login_success(user)
    if is_approval_owner(user):
        return redirect(url_for("approval.pending"))
    return redirect(url_for("dashboard.index"))


def create_or_route_google_pending_user(identity):
    linked_user = User.query.filter_by(auth_provider="google", oauth_id=identity["sub"]).first()
    if linked_user:
        if linked_user.is_pending_approval or linked_user.is_rejected_approval or linked_user.is_disabled_approval or not linked_user.is_active or not linked_user.can_access_app:
            _set_pending_session(linked_user)
            return redirect("/auth/pending")
        if linked_user.can_access_app:
            return _login_active_google_user(linked_user)

    existing_email_user = User.query.filter_by(email=identity["email"]).first()
    if existing_email_user:
        flash(
            "Email này đã tồn tại. Vui lòng đăng nhập bằng mật khẩu hoặc liên hệ chủ spa.",
            "warning",
        )
        return redirect(url_for("auth.login"))

    user = User(
        username=_build_google_username(identity["sub"]),
        full_name=identity.get("name") or identity["email"].split("@", 1)[0],
        role=UserRole.STAFF.value,
        is_active=False,
        approval_status=User.APPROVAL_PENDING,
        approved_by_id=None,
        approved_at=None,
        email=identity["email"],
        email_verified=True,
        auth_provider="google",
        oauth_id=identity["sub"],
    )
    user.set_password(secrets.token_urlsafe(32))
    db.session.add(user)
    db.session.commit()
    _set_pending_session(user)
    return redirect("/auth/pending")


def handle_google_callback_skeleton(error=None, error_description=None, app=None):
    app = _get_app(app)
    if error:
        flash("Đăng nhập Google không hoàn tất.", "warning")
        return redirect(url_for("auth.login"))

    if app is None or not is_google_auth_available(app):
        flash("Đăng nhập Google hiện chưa được bật.", "warning")
        return redirect(url_for("auth.login"))

    client = get_google_client(app)
    try:
        identity = _extract_identity_from_callback(client, app)
    except GoogleIdentityError:
        flash("Không thể xác thực tài khoản Google. Vui lòng thử lại hoặc liên hệ chủ spa.", "warning")
        return redirect(url_for("auth.login"))

    return create_or_route_google_pending_user(identity)
