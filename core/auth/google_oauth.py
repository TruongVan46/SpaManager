from flask import current_app, flash, has_app_context, has_request_context, redirect, url_for

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


def handle_google_callback_skeleton(error=None, error_description=None, app=None):
    app = _get_app(app)
    if error:
        flash("Đăng nhập Google không hoàn tất.", "warning")
        return redirect(url_for("auth.login"))

    if app is None or not is_google_auth_available(app):
        flash("Đăng nhập Google hiện chưa được bật.", "warning")
        return redirect(url_for("auth.login"))

    flash(
        "Google login đã kết nối nhưng bước tạo tài khoản sẽ được bật ở task sau.",
        "info",
    )
    return redirect(url_for("auth.login"))
