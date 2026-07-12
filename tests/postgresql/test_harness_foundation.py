import pytest


@pytest.mark.postgres_rehearsal
def test_dedicated_postgres_target_is_metadata_only(postgres_rehearsal_target):
    assert postgres_rehearsal_target.backend == "postgresql"
    assert postgres_rehearsal_target.host in {"localhost", "127.0.0.1"}
    assert postgres_rehearsal_target.port == 5433
    assert postgres_rehearsal_target.database == "spamanager_purge_rehearsal_test"
