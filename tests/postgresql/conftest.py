import os

import pytest

from tests.postgresql.rehearsal_guard import (
    ensure_fresh_process,
    is_rehearsal_requested,
    validate_rehearsal_environment,
)


def pytest_configure(config):
    config.addinivalue_line("markers", "postgres_rehearsal: dedicated PostgreSQL rehearsal tests")


def resolve_postgres_rehearsal_target(environ):
    if not is_rehearsal_requested(environ):
        pytest.skip("PostgreSQL rehearsal requires the exact dedicated opt-in.")
    ensure_fresh_process()
    return validate_rehearsal_environment(environ)


@pytest.fixture(scope="session")
def postgres_rehearsal_target():
    return resolve_postgres_rehearsal_target(os.environ)


@pytest.fixture(scope="session")
def postgres_runtime(postgres_rehearsal_target):
    from tests.postgresql.rehearsal_runtime import create_runtime

    runtime = create_runtime(postgres_rehearsal_target)
    try:
        yield runtime
    finally:
        runtime.close()


@pytest.fixture
def postgres_service_session_timeouts(postgres_runtime, monkeypatch):
    from services.purge_request_service import PurgeRequestService
    from services.purge_service import PurgeService
    from tests.postgresql.rehearsal_runtime import wrap_service_new_session

    wrap_service_new_session(PurgeRequestService, monkeypatch)
    wrap_service_new_session(PurgeService, monkeypatch)
    yield
