"""Static contract and opt-in entry points for d3e PostgreSQL races.

Import and collection are intentionally database-free. The seven scenario
entry points are skipped unless every existing rehearsal guard is enabled.
"""

import os
from pathlib import Path

import pytest

from tests.postgresql.purge_reauth_concurrency_support import (
    APPLICATION_TABLE_NAMES,
    EXPECTED_REVISION,
    MIGRATION_METADATA_TABLE,
    SCENARIO_PLANS,
    SCENARIO_CALLBACKS,
    CleanupManifest,
    RoundContext,
    RehearsalGuardError,
    WorkerResult,
    assert_distinct_backend_pids,
    assert_revision_metadata,
    classify_public_tables,
    require_rehearsal_environment,
    source_application_table_names,
    create_enabled_rehearsal_context,
    execute_scenario,
    create_round_context,
    isolated_purge_execution_flags,
    copy_actual_session_cookie,
    resolve_scenario_callback,
)


SCENARIO_NAMES = {
    "A": "test_postgresql_concurrent_authorization_issuance",
    "B": "test_postgresql_actor_global_throttle_race",
    "C": "test_postgresql_same_nonce_claim_race",
    "D": "test_postgresql_concurrent_public_purge_execution",
    "E": "test_postgresql_copied_session_cookie_race",
    "F": "test_postgresql_issuance_versus_claim_race",
    "G": "test_postgresql_logout_revocation_versus_claim_race",
}


def _scenario_target_or_skip():
    if os.environ.get("SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL") != "1":
        pytest.skip("PostgreSQL d3e rehearsal requires the exact dedicated opt-in.")
    return require_rehearsal_environment(os.environ)


def _assert_scenario_plan(code):
    plan = SCENARIO_PLANS[code]
    assert plan.rounds >= {"A": 10, "B": 5, "C": 20, "D": 5, "E": 5, "F": 10, "G": 10}[code]
    assert plan.workers >= 2
    assert "Barrier" in plan.synchronization
    return plan


def test_d3e_scenario_inventory_is_one_to_one():
    assert set(SCENARIO_NAMES) == set(SCENARIO_PLANS) == set("ABCDEFG")
    source = Path(__file__).read_text(encoding="utf-8")
    for name in SCENARIO_NAMES.values():
        assert f"def {name}(" in source


def test_d3e_scenario_plans_have_independent_deterministic_workers():
    for code in SCENARIO_NAMES:
        plan = _assert_scenario_plan(code)
        assert "independent" in plan.isolation
        assert plan.forbidden_outcomes


def test_d3e_callback_registry_is_complete_and_harness_owned():
    assert set(SCENARIO_CALLBACKS) == set("ABCDEFG")
    assert all(callable(callback) for callback in SCENARIO_CALLBACKS.values())
    class Context:
        scenario_callbacks = SCENARIO_CALLBACKS
    for code in "ABCDEFG":
        assert resolve_scenario_callback(Context(), code) is SCENARIO_CALLBACKS[code]
    with pytest.raises(RehearsalGuardError):
        resolve_scenario_callback(Context(), "X")


def test_d3e_callback_registry_requires_no_external_registration():
    assert SCENARIO_CALLBACKS["A"].__module__ == "tests.postgresql.purge_reauth_concurrency_support"
    assert SCENARIO_CALLBACKS["D"].__name__ == "run_scenario_d_concurrent_public_execution"
    assert SCENARIO_CALLBACKS["E"].__name__ == "run_scenario_e_copied_cookie"


def test_d3e_opt_in_absent_skips_without_database_access(monkeypatch):
    monkeypatch.delenv("SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL", raising=False)
    with pytest.raises(pytest.skip.Exception):
        _scenario_target_or_skip()


def test_d3e_opt_in_missing_url_fails_closed(monkeypatch):
    monkeypatch.setenv("SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL", "1")
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SPAMANAGER_TEST_PROCESS", "1")
    monkeypatch.setenv("SPAMANAGER_ALLOW_POSTGRES_TESTS", "1")
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(RehearsalGuardError):
        _scenario_target_or_skip()


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///spamanager_purge_rehearsal_test",
        "postgresql://user@localhost:5433/spamanager_dev",
        "postgresql://user@localhost:5433/wrong_database",
        "postgresql://user@railway.example:5433/spamanager_purge_rehearsal_test",
    ],
)
def test_d3e_rejects_unsafe_database_targets(monkeypatch, url):
    for name, value in {
        "SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL": "1",
        "APP_ENV": "testing",
        "SPAMANAGER_TEST_PROCESS": "1",
        "SPAMANAGER_ALLOW_POSTGRES_TESTS": "1",
        "TEST_DATABASE_URL": url,
    }.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RehearsalGuardError):
        _scenario_target_or_skip()


def test_d3e_metadata_classification_excludes_alembic_version():
    classified = classify_public_tables(
        {MIGRATION_METADATA_TABLE, *APPLICATION_TABLE_NAMES},
        {MIGRATION_METADATA_TABLE, *APPLICATION_TABLE_NAMES},
    )
    assert classified["metadata"] == {MIGRATION_METADATA_TABLE}
    assert MIGRATION_METADATA_TABLE not in classified["application"]
    assert classified["application"] == APPLICATION_TABLE_NAMES


def test_d3e_workflow_tables_are_classified_without_purge_registry_imports():
    regular_metadata = APPLICATION_TABLE_NAMES - {
        "workspace_purge_requests", "purge_legal_holds", "purge_lifecycle_events",
        "workspace_purge_execution_authorizations", "workspace_purge_reauth_actor_throttles",
    }
    classified = classify_public_tables(
        {MIGRATION_METADATA_TABLE, *APPLICATION_TABLE_NAMES}, regular_metadata
    )
    assert classified["application"] == APPLICATION_TABLE_NAMES


def test_d3e_classification_is_import_order_independent():
    catalog = {MIGRATION_METADATA_TABLE, *APPLICATION_TABLE_NAMES}
    assert classify_public_tables(catalog, set())["application"] == APPLICATION_TABLE_NAMES
    assert classify_public_tables(catalog, APPLICATION_TABLE_NAMES)["application"] == APPLICATION_TABLE_NAMES


def test_d3e_expected_application_table_missing_fails_closed():
    with pytest.raises(RehearsalGuardError, match="Application table missing"):
        classify_public_tables(
            {MIGRATION_METADATA_TABLE, *(APPLICATION_TABLE_NAMES - {"purge_lifecycle_events"})},
            set(),
        )


@pytest.mark.parametrize(
    "revision_rows",
    [(), (EXPECTED_REVISION, EXPECTED_REVISION), ("0007_permanent_purge_workflow",)],
)
def test_d3e_revision_metadata_requires_exact_single_0008_row(revision_rows):
    with pytest.raises(RehearsalGuardError):
        assert_revision_metadata(revision_rows)


def test_d3e_revision_metadata_accepts_exact_single_0008_row():
    assert_revision_metadata((EXPECTED_REVISION,))


def test_d3e_unknown_public_table_fails_closed():
    with pytest.raises(RehearsalGuardError, match="Unknown public"):
        classify_public_tables(
            {MIGRATION_METADATA_TABLE, *APPLICATION_TABLE_NAMES, "unknown_public_table"},
            {MIGRATION_METADATA_TABLE, *APPLICATION_TABLE_NAMES},
        )


def test_d3e_metadata_source_table_set_does_not_omit_known_application_tables():
    class Metadata:
        tables = {name: object() for name in APPLICATION_TABLE_NAMES | {MIGRATION_METADATA_TABLE}}

    assert source_application_table_names(Metadata()) == APPLICATION_TABLE_NAMES
    assert EXPECTED_REVISION == "0008_durable_purge_reauth_state"


def test_d3e_worker_result_repr_contains_no_secret_fields():
    result = WorkerResult("C", 1, "claim-a", "CLAIMED", backend_pid=101, generation=1, state="CLAIMED")
    rendered = repr(result).lower()
    assert "password" not in rendered
    assert "nonce" not in rendered
    assert "cookie" not in rendered
    assert "database_url" not in rendered


def test_d3e_cleanup_manifest_is_exact_and_reverse_ordered():
    manifest = CleanupManifest("d3e-static-test")
    manifest.register("workspace", 10)
    manifest.register("purge_request", 20)
    manifest.register("authorization", 30)
    manifest.require_registered("authorization", 30)
    assert manifest.deletion_order() == (
        ("authorization", 30),
        ("purge_request", 20),
        ("workspace", 10),
    )
    with pytest.raises(ValueError):
        manifest.require_registered("authorization", 999)


def test_d3e_manifest_typed_registration_rejects_metadata_and_namespace_mismatch():
    manifest = CleanupManifest("round-a")
    manifest.register_user(1)
    with pytest.raises(ValueError):
        manifest.register(MIGRATION_METADATA_TABLE, 1)
    with pytest.raises(ValueError):
        manifest.register_typed("user", 2, "other-round")
    with pytest.raises(ValueError):
        manifest.register("not-a-table", 3)


def test_d3e_round_contexts_have_fresh_manifests_and_secret_safe_repr():
    first = create_round_context("D", 1, "run")
    second = create_round_context("D", 2, "run")
    assert first.manifest is not second.manifest
    assert first.namespace != second.namespace
    rendered = repr(first).lower()
    assert all(secret not in rendered for secret in ("password", "nonce", "cookie", "postgres"))


def test_d3e_isolated_flags_restore_application_config():
    class Application:
        config = {"PERMANENT_PURGE_UI_ENABLED": False, "PERMANENT_PURGE_EXECUTION_ENABLED": None}
    application = Application()
    with isolated_purge_execution_flags(application):
        assert application.config["PERMANENT_PURGE_UI_ENABLED"] is True
        assert application.config["PERMANENT_PURGE_EXECUTION_ENABLED"] is True
    assert application.config == {"PERMANENT_PURGE_UI_ENABLED": False, "PERMANENT_PURGE_EXECUTION_ENABLED": None}


def test_d3e_route_helpers_use_real_cookie_and_logout_route_contract():
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    assert "source.get_cookie(\"session\")" in source
    assert "target.set_cookie" in source
    assert 'client.post("/logout"' in source
    assert "revoke_active_authorizations_for_actor" not in source


def test_d3e_worker_backend_pid_assertion_is_fail_closed():
    results = [
        WorkerResult("A", 1, "a", "ok", backend_pid=1),
        WorkerResult("A", 1, "b", "ok", backend_pid=2),
    ]
    assert_distinct_backend_pids(results)
    with pytest.raises(AssertionError):
        assert_distinct_backend_pids([results[0], WorkerResult("A", 1, "b", "ok", backend_pid=1)])


@pytest.fixture
def enabled_rehearsal_context():
    if os.environ.get("SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL") != "1":
        pytest.skip("PostgreSQL d3e rehearsal requires the exact dedicated opt-in.")
    context = create_enabled_rehearsal_context(os.environ)
    try:
        yield context
    finally:
        context.close()


def test_postgresql_concurrent_authorization_issuance(enabled_rehearsal_context):
    assert len(execute_scenario(enabled_rehearsal_context, "A")) == 10


def test_postgresql_actor_global_throttle_race(enabled_rehearsal_context):
    assert len(execute_scenario(enabled_rehearsal_context, "B")) == 5


def test_postgresql_same_nonce_claim_race(enabled_rehearsal_context):
    assert len(execute_scenario(enabled_rehearsal_context, "C")) == 20


def test_postgresql_concurrent_public_purge_execution(enabled_rehearsal_context):
    assert len(execute_scenario(enabled_rehearsal_context, "D")) == 5


def test_postgresql_copied_session_cookie_race(enabled_rehearsal_context):
    assert len(execute_scenario(enabled_rehearsal_context, "E")) == 5


def test_postgresql_issuance_versus_claim_race(enabled_rehearsal_context):
    assert len(execute_scenario(enabled_rehearsal_context, "F")) == 10


def test_postgresql_logout_revocation_versus_claim_race(enabled_rehearsal_context):
    assert len(execute_scenario(enabled_rehearsal_context, "G")) == 10
