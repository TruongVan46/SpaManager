import ast
from pathlib import Path
import sys

import pytest

from tests.postgresql.rehearsal_guard import (
    REHEARSAL_DATABASE_NAME,
    REHEARSAL_OPT_IN_ENV,
    RehearsalGuardError,
    is_rehearsal_requested,
    validate_rehearsal_environment,
)
from tests.postgresql import conftest


def valid_environment(url="postgresql://user:SUPER_SECRET_SENTINEL@localhost:5433/spamanager_purge_rehearsal_test"):
    return {
        "APP_ENV": "testing",
        "SPAMANAGER_TEST_PROCESS": "1",
        "SPAMANAGER_ALLOW_POSTGRES_TESTS": "1",
        REHEARSAL_OPT_IN_ENV: "1",
        "TEST_DATABASE_URL": url,
    }


def assert_rejected(environment):
    raw_url = environment.get("TEST_DATABASE_URL")
    with pytest.raises(RehearsalGuardError) as error:
        validate_rehearsal_environment(environment)
    message = str(error.value)
    assert "SUPER_SECRET_SENTINEL" not in message
    if isinstance(raw_url, str) and raw_url:
        assert raw_url not in message


def test_accepts_exact_dedicated_target():
    target = validate_rehearsal_environment(valid_environment())
    assert (target.backend, target.host, target.port, target.database) == (
        "postgresql", "localhost", 5433, REHEARSAL_DATABASE_NAME
    )
    assert "SUPER_SECRET_SENTINEL" not in repr(target)


def test_accepts_postgresql_driver_variant():
    target = validate_rehearsal_environment(valid_environment(
        "postgresql+psycopg://user:SUPER_SECRET_SENTINEL@127.0.0.1:5433/spamanager_purge_rehearsal_test"
    ))
    assert target.host == "127.0.0.1"


@pytest.mark.parametrize("name,value", [
    ("APP_ENV", None), ("APP_ENV", "production"),
    ("SPAMANAGER_TEST_PROCESS", None), ("SPAMANAGER_TEST_PROCESS", "true"),
    ("SPAMANAGER_TEST_PROCESS", "0"),
    ("SPAMANAGER_ALLOW_POSTGRES_TESTS", None), ("SPAMANAGER_ALLOW_POSTGRES_TESTS", "true"),
    (REHEARSAL_OPT_IN_ENV, None), (REHEARSAL_OPT_IN_ENV, "yes"),
    (REHEARSAL_OPT_IN_ENV, "on"),
])
def test_requires_exact_markers(name, value):
    environment = valid_environment()
    if value is None:
        environment.pop(name, None)
    else:
        environment[name] = value
    assert_rejected(environment)


@pytest.mark.parametrize("url", [
    None,
    "",
    123,
    "not a url",
    "sqlite:///spamanager_purge_rehearsal_test",
    "mysql://user:SUPER_SECRET_SENTINEL@localhost:5433/spamanager_purge_rehearsal_test",
])
def test_rejects_missing_malformed_or_wrong_dialect(url):
    environment = valid_environment(url)
    assert_rejected(environment)


@pytest.mark.parametrize("query", [
    "host=railway.internal",
    "port=5432",
    "service=production",
    "sslmode=require",
    "options=-c%20search_path%3Dpublic",
    "host=localhost&port=5432",
])
def test_rejects_all_url_query_parameters(query):
    raw_url = f"postgresql://user:SUPER_SECRET_SENTINEL@localhost:5433/{REHEARSAL_DATABASE_NAME}?{query}"
    assert_rejected(valid_environment(raw_url))


@pytest.mark.parametrize("raw_url", [
    " postgresql://user:SUPER_SECRET_SENTINEL@localhost:5433/spamanager_purge_rehearsal_test",
    "postgresql://user:SUPER_SECRET_SENTINEL@localhost:5433/spamanager_purge_rehearsal_test ",
    "\npostgresql://user:SUPER_SECRET_SENTINEL@localhost:5433/spamanager_purge_rehearsal_test",
])
def test_rejects_url_with_surrounding_whitespace(raw_url):
    assert_rejected(valid_environment(raw_url))


def test_malformed_url_suppresses_parser_exception_cause():
    raw_url = "postgresql://user:SUPER_SECRET_SENTINEL@localhost:notaport/spamanager_purge_rehearsal_test"
    with pytest.raises(RehearsalGuardError) as error:
        validate_rehearsal_environment(valid_environment(raw_url))
    assert "not a valid database URL" in str(error.value)
    assert "SUPER_SECRET_SENTINEL" not in str(error.value)
    assert raw_url not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


@pytest.mark.parametrize("host", ["railway.internal", "example.com", "192.168.1.20", "::1", "LOCALHOST", " localhost"])
def test_rejects_non_exact_hosts(host):
    assert_rejected(valid_environment(
        f"postgresql://user:SUPER_SECRET_SENTINEL@{host}:5433/{REHEARSAL_DATABASE_NAME}"
    ))


@pytest.mark.parametrize("port", [None, 5432, 5434])
def test_rejects_non_exact_ports(port):
    host = "localhost" if port is not None else "localhost"
    url = f"postgresql://user:SUPER_SECRET_SENTINEL@{host}:{port or ''}/{REHEARSAL_DATABASE_NAME}"
    assert_rejected(valid_environment(url))


@pytest.mark.parametrize("database", ["spamanager_dev", "postgres", "template0", "template1", "another_name_test", "", "xspamanager_purge_rehearsal_test"])
def test_rejects_non_exact_databases(database):
    assert_rejected(valid_environment(
        f"postgresql://user:SUPER_SECRET_SENTINEL@localhost:5433/{database}"
    ))


@pytest.mark.parametrize("value", [None, "", "true", "yes", "on", 1])
def test_is_rehearsal_requested_requires_exact_one(value):
    environment = {REHEARSAL_OPT_IN_ENV: value}
    assert is_rehearsal_requested(environment) is False


def test_is_rehearsal_requested_accepts_exact_one():
    assert is_rehearsal_requested({REHEARSAL_OPT_IN_ENV: "1"}) is True


def test_guard_import_does_not_import_app_or_extensions():
    source = Path(__file__).with_name("rehearsal_guard.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "app" not in imported_names
    assert "extensions" not in imported_names


@pytest.mark.parametrize("module_name", ["app", "extensions"])
def test_process_isolation_refuses_loaded_application_modules(monkeypatch, module_name):
    from tests.postgresql.rehearsal_guard import ensure_fresh_process

    monkeypatch.setitem(sys.modules, module_name, object())
    with pytest.raises(RehearsalGuardError, match="fresh pytest process"):
        ensure_fresh_process()


def test_fixture_checks_process_isolation_before_target_validation(monkeypatch):
    environment = valid_environment()
    monkeypatch.setenv("APP_ENV", environment["APP_ENV"])
    monkeypatch.setenv("SPAMANAGER_TEST_PROCESS", environment["SPAMANAGER_TEST_PROCESS"])
    monkeypatch.setenv("SPAMANAGER_ALLOW_POSTGRES_TESTS", environment["SPAMANAGER_ALLOW_POSTGRES_TESTS"])
    monkeypatch.setenv(REHEARSAL_OPT_IN_ENV, environment[REHEARSAL_OPT_IN_ENV])
    monkeypatch.setenv("TEST_DATABASE_URL", environment["TEST_DATABASE_URL"])
    monkeypatch.setattr(conftest, "validate_rehearsal_environment", lambda _: pytest.fail("validation must not run"))
    monkeypatch.setattr(conftest, "ensure_fresh_process", lambda: (_ for _ in ()).throw(RehearsalGuardError("fresh pytest process")))
    with pytest.raises(RehearsalGuardError, match="fresh pytest process"):
        conftest.postgres_rehearsal_target._fixture_function()


def test_guard_source_has_no_connection_or_process_operations():
    source = Path(__file__).with_name("rehearsal_guard.py").read_text(encoding="utf-8")
    for prohibited in ("create_engine", "engine.connect", "sessionmaker", "psycopg.connect", "subprocess", "docker", "psql"):
        assert prohibited not in source
