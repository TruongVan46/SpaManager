import traceback
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from tests.postgresql import rehearsal_runtime


SECRET = "ULTRA_SECRET_REHEARSAL_SENTINEL_9F2C"
FAKE_URL = (
    "postgresql://spamanager:ULTRA_SECRET_REHEARSAL_SENTINEL_9F2C@"
    "127.0.0.1:5433/spamanager_purge_rehearsal_test"
)


def _operational_error(original):
    return OperationalError(
        "could not connect",
        {"dsn": FAKE_URL, "password": SECRET},
        original,
    )


def _assert_safe_output(error, expected_code):
    rendered = "".join(traceback.format_exception(error))
    for output in (str(error), repr(error), rendered):
        assert SECRET not in output
        assert FAKE_URL not in output
        assert "password=" not in output
        assert "dsn=" not in output
        assert "OperationalError" not in output
        assert expected_code in output
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


def test_authentication_error_is_sanitized_and_chainless():
    original = SimpleNamespace(
        pgcode="28P01",
        diag=SimpleNamespace(sqlstate="28P01"),
        args=(f"password authentication failed for {SECRET}",),
    )
    with pytest.raises(rehearsal_runtime.RehearsalDatabaseAuthenticationError) as caught:
        rehearsal_runtime.raise_sanitized_database_error(_operational_error(original))
    _assert_safe_output(caught.value, "LOCAL_REHEARSAL_DATABASE_AUTHENTICATION_FAILED")


def test_generic_connection_error_is_sanitized():
    original = SimpleNamespace(
        pgcode="08001",
        diag=SimpleNamespace(sqlstate="08001"),
        args=(f"connection failed: {SECRET}",),
    )
    with pytest.raises(rehearsal_runtime.RehearsalDatabaseConnectionError) as caught:
        rehearsal_runtime.raise_sanitized_database_error(_operational_error(original))
    _assert_safe_output(caught.value, "LOCAL_REHEARSAL_DATABASE_CONNECTION_FAILED")


def test_actual_runtime_creation_boundary_sanitizes_import_failure(monkeypatch):
    original_import = __import__("builtins").__import__
    original = SimpleNamespace(
        pgcode="28P01",
        diag=SimpleNamespace(sqlstate="28P01"),
        args=(f"password authentication failed: {SECRET}",),
    )

    def fail_on_app(name, *args, **kwargs):
        if name == "app":
            raise _operational_error(original)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(__import__("builtins"), "__import__", fail_on_app)
    target = SimpleNamespace(
        backend="postgresql",
        host="127.0.0.1",
        port=5433,
        database="spamanager_purge_rehearsal_test",
    )
    environ = {
        "APP_ENV": "testing",
        "SPAMANAGER_TEST_PROCESS": "1",
        "SPAMANAGER_ALLOW_POSTGRES_TESTS": "1",
        "SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL": "1",
        "TEST_DATABASE_URL": "present",
    }
    with pytest.raises(rehearsal_runtime.RehearsalDatabaseAuthenticationError) as caught:
        rehearsal_runtime.create_runtime(target, environ=environ)
    _assert_safe_output(caught.value, "LOCAL_REHEARSAL_DATABASE_AUTHENTICATION_FAILED")


def test_non_connection_identity_error_is_preserved():
    with pytest.raises(rehearsal_runtime.RehearsalIdentityError, match="identity mismatch"):
        raise rehearsal_runtime.RehearsalIdentityError("identity mismatch")
