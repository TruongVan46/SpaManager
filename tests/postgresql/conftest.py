import os

import pytest

from tests.postgresql.rehearsal_guard import (
    ensure_fresh_process,
    is_rehearsal_requested,
    validate_rehearsal_environment,
)


def pytest_configure(config):
    config.addinivalue_line("markers", "postgres_rehearsal: dedicated PostgreSQL rehearsal tests")


@pytest.fixture(scope="session")
def postgres_rehearsal_target():
    if not is_rehearsal_requested(os.environ):
        pytest.skip("PostgreSQL rehearsal requires the exact dedicated opt-in.")
    ensure_fresh_process()
    return validate_rehearsal_environment(os.environ)
