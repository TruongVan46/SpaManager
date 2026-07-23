"""Canonical authenticated-session setup for request-level tests."""

from core.auth.constants import AUTH_SESSION_KEY, SESSION_REVOCATION_VERSION_KEY


def set_authenticated_session(session_data, user, *, workspace_id=None, enable_workspace_isolation=None):
    """Create a valid versioned session while preserving optional test context."""
    if not hasattr(user, "session_revocation_version"):
        from models.user import User
        user = User.query.get(user)
    if user is None:
        raise AssertionError("Authenticated test session requires a persisted user.")
    session_data[AUTH_SESSION_KEY] = user.id
    session_data[SESSION_REVOCATION_VERSION_KEY] = int(user.session_revocation_version)
    if workspace_id is not None:
        session_data["current_workspace_id"] = workspace_id
    if enable_workspace_isolation is not None:
        session_data["_enable_workspace_isolation"] = enable_workspace_isolation
    return session_data
