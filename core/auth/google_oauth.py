from flask import current_app, has_app_context

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

oauth = OAuth()


def _get_app(app=None):
    if app is not None:
        return app
    if not has_app_context():
        return None
    return current_app._get_current_object()


def _is_config_valid(app):
    validator = getattr(app.config, "validate_google_oauth_config", None)
    if callable(validator):
        return not validator()

    client_id = (app.config.get("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (app.config.get("GOOGLE_CLIENT_SECRET") or "").strip()
    return bool(client_id and client_secret)


def init_google_oauth(app=None):
    app = _get_app(app)
    if app is None:
        return False

    state = app.extensions.setdefault("google_oauth", {})
    state.setdefault("initialized", False)
    state.setdefault("registered", False)
    state["available"] = False

    enabled = bool(app.config.get("GOOGLE_AUTH_ENABLED"))
    valid = _is_config_valid(app)
    state["enabled"] = enabled
    state["valid"] = valid

    if not (enabled and valid and oauth is not None):
        return False

    if not state["initialized"]:
        oauth.init_app(app)
        state["initialized"] = True

    if not state["registered"]:
        client_kwargs = {
            "scope": " ".join(app.config.get("GOOGLE_SCOPES", [])),
        }
        register_kwargs = {
            "name": "google",
            "client_id": app.config.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": app.config.get("GOOGLE_CLIENT_SECRET", ""),
            "server_metadata_url": app.config.get("GOOGLE_DISCOVERY_URL", ""),
            "client_kwargs": client_kwargs,
        }
        redirect_uri = app.config.get("GOOGLE_REDIRECT_URI", "")
        if redirect_uri:
            register_kwargs["redirect_uri"] = redirect_uri
        oauth.register(**register_kwargs)
        state["registered"] = True

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
