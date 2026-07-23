import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault(
    "TEST_DATABASE_URL",
    f"sqlite:///{(Path(__file__).resolve().parent / 'session_guard_test.db').as_posix()}",
)

from app import app
from flask import session

from core.auth.constants import AUTH_SESSION_KEY, SESSION_REVOCATION_VERSION_KEY
from services.auth_service import AuthService


def _user(*, version=3, active=True, deleted_at=None, purge_state=None):
    return SimpleNamespace(
        id=11,
        session_revocation_version=version,
        is_active=active,
        deleted_at=deleted_at,
        account_purge_state=purge_state,
        is_pending_approval=False,
        is_rejected_approval=False,
        is_disabled_approval=False,
    )


def test_matching_version_loads_and_mismatch_clears_session():
    with app.test_request_context():
        user = _user()
        session[AUTH_SESSION_KEY] = user.id
        session[SESSION_REVOCATION_VERSION_KEY] = 3
        with patch("services.auth_service.User.query", create=True) as query:
            query.get.return_value = user
            assert AuthService.get_current_user() is user
            session[SESSION_REVOCATION_VERSION_KEY] = 2
            assert AuthService.get_current_user() is None
        assert AUTH_SESSION_KEY not in session
        assert SESSION_REVOCATION_VERSION_KEY not in session


def test_missing_or_malformed_version_fails_closed():
    with app.test_request_context():
        user = _user()
        with patch("services.auth_service.User.query", create=True) as query:
            query.get.return_value = user
            session[AUTH_SESSION_KEY] = user.id
            assert AuthService.get_current_user() is None
            session[AUTH_SESSION_KEY] = user.id
            session[SESSION_REVOCATION_VERSION_KEY] = "3"
            assert AuthService.get_current_user() is None
        assert AUTH_SESSION_KEY not in session


def test_deleted_inactive_and_terminal_users_are_blocked():
    with app.test_request_context():
        for user in (_user(deleted_at=object()), _user(active=False), _user(purge_state="PURGED_TOMBSTONE")):
            session[AUTH_SESSION_KEY] = user.id
            session[SESSION_REVOCATION_VERSION_KEY] = user.session_revocation_version
            with patch("services.auth_service.User.query", create=True) as query:
                query.get.return_value = user
                assert AuthService.get_current_user() is None


def test_local_session_writer_records_version_and_remember_flag():
    with app.test_request_context():
        user = _user(version=9)
        AuthService._write_authenticated_session(user, remember=True)
        assert session[AUTH_SESSION_KEY] == user.id
        assert session[SESSION_REVOCATION_VERSION_KEY] == 9
        assert session.permanent is True
