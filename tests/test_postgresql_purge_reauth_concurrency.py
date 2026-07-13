"""Static contract and opt-in entry points for d3e PostgreSQL races.

Import and collection are intentionally database-free. The seven scenario
entry points are skipped unless every existing rehearsal guard is enabled.
"""

import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.postgresql.purge_reauth_concurrency_support as support
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
    assert_application_tables_empty,
    CLEANUP_KIND_ORDER,
    _manifest_request_ids,
    _manifest_workspace_ids,
    validate_terminal_backlink_bindings,
    CapturedPytestResult,
    CleanupFailure,
    HARNESS_CLEANUP_REQUIRED,
    SERVICE_DELETION_EXPECTED,
    reconcile_service_deletion_expected,
    canonical_route_url,
    format_rehearsal_evidence,
    run_postflight_with_evidence,
    POSTGRESQL_SCENARIO_NODE_IDS,
    INDEPENDENT_PHASE_NODE_IDS,
    IndependentExecutionPlan,
    PhaseEvidence,
    ScenarioExecutionResult,
    ZeroRowGateResult,
    build_independent_execution_plan,
    execute_scenario_with_outcomes,
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


def test_d3e_service_deletion_mode_is_semantic_not_letter_based():
    assert SCENARIO_PLANS["D"].execution_mode == "PURGE_SERVICE"
    assert SCENARIO_PLANS["E"].execution_mode == "PURGE_SERVICE"
    assert not SCENARIO_PLANS["A"].service_deletion_expected
    assert not SCENARIO_PLANS["B"].service_deletion_expected
    assert not SCENARIO_PLANS["C"].service_deletion_expected
    assert not SCENARIO_PLANS["F"].service_deletion_expected
    assert not SCENARIO_PLANS["G"].service_deletion_expected
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    assert "if round_context.scenario == \"D\"" not in source
    assert "if scenario in {\"D\", \"E\"}" not in source


def test_d3e_round_context_carries_execution_semantics():
    assert create_round_context("D", 1, "run").execution_mode == "PURGE_SERVICE"
    assert create_round_context("E", 1, "run").execution_mode == "PURGE_SERVICE"
    assert create_round_context("F", 1, "run").execution_mode == "AUTHORIZATION_ONLY"


def test_d3e_e_fixture_registers_service_deletions_by_mode():
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    fixture = source[source.index("def approved_request"):source.index("def _service_worker_results")]
    assert "round_context.execution_mode == \"PURGE_SERVICE\"" in fixture
    assert "register_service_deletion_expected" not in fixture
    assert "manifest.classification_by_key[(kind, object_id)] = SERVICE_DELETION_EXPECTED" in fixture


def test_d3e_e_uses_same_isolated_execution_flags_as_d():
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    e_source = source[source.index("def run_scenario_e_copied_cookie"):source.index("def run_scenario_f_issuance_vs_claim")]
    assert "with isolated_purge_execution_flags(context.application):" in e_source


def test_d3e_independent_phase_selectors_are_exact_and_disjoint():
    plan = build_independent_execution_plan()
    selectors = plan.validate()
    assert len(selectors["A-D"]) == 4
    assert len(selectors["E"]) == len(selectors["F"]) == len(selectors["G"]) == 1
    flattened = [node for nodes in selectors.values() for node in nodes]
    assert len(flattened) == len(set(flattened)) == 7
    assert set(flattened) == set(POSTGRESQL_SCENARIO_NODE_IDS.values())
    assert all(node.startswith("tests/test_postgresql_purge_reauth_concurrency.py::test_postgresql_") for node in flattened)


def test_d3e_independent_plan_requires_zero_and_stops_after_any_failure():
    plan = IndependentExecutionPlan()
    assert plan.should_start("A-D")
    passed = PhaseEvidence("A-D", "PASS", "PASS", "PASS")
    failed_teardown = PhaseEvidence("E", "PASS", "FAIL", "FAIL")
    failed_functional = PhaseEvidence("E", "FAIL", "PASS", "PASS")
    assert plan.should_start("E", passed)
    assert not plan.should_start("F", failed_teardown)
    assert not plan.should_start("F", failed_functional)
    assert not plan.should_start("G", failed_teardown)


def test_d3e_zero_row_gate_reports_exact_nonzero_tables():
    counts = {name: 0 for name in APPLICATION_TABLE_NAMES}
    counts["users"] = 2
    failed = ZeroRowGateResult("spamanager_purge_rehearsal_test", EXPECTED_REVISION, counts)
    assert not failed.passed
    assert failed.nonzero_tables == {"users": 2}
    passed = ZeroRowGateResult("spamanager_purge_rehearsal_test", EXPECTED_REVISION, {name: 0 for name in APPLICATION_TABLE_NAMES})
    assert passed.passed


def test_d3e_outcome_separates_functional_teardown_and_postflight():
    result = ScenarioExecutionResult("E", "PASS", teardown_status="FAIL", teardown_error="missing row", postflight_status="FAIL", remaining_objects=("user:1",))
    assert result.functional_status == "PASS"
    assert result.teardown_status == "FAIL"
    assert result.postflight_status == "FAIL"
    assert result.overall_status == "FAIL"
    assert result.remaining_objects == ("user:1",)


def test_d3e_outcome_preserves_functional_failure_when_cleanup_passes():
    result = ScenarioExecutionResult("E", "FAIL", functional_error="HTTP contract failure", teardown_status="PASS", postflight_status="PASS")
    assert result.functional_status == "FAIL"
    assert result.teardown_status == "PASS"
    assert result.overall_status == "FAIL"


def test_d3e_execution_plan_has_no_broad_repair_continue_path():
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    plan_source = source[source.index("class IndependentExecutionPlan"):source.index("def build_independent_execution_plan")]
    assert "repair" not in plan_source.lower()
    assert "stop_on_teardown_failure" in plan_source
    assert "stop_on_postflight_failure" in plan_source


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


def test_d3e_bootstrap_readiness_rejects_any_application_delta_without_cleanup():
    with pytest.raises(RehearsalGuardError, match="application data is not empty"):
        assert_application_tables_empty({"users": 1, "workspaces": 0})

    support_source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    assert "DELETE" not in support_source[support_source.index("def assert_application_tables_empty"):support_source.index("def _assert_readiness")]


def test_d3e_bootstrap_suppression_is_explicit_and_loaded_before_app_import():
    config_source = Path("config.py").read_text(encoding="utf-8")
    app_source = Path("app.py").read_text(encoding="utf-8")
    support_source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    assert "BOOTSTRAP_ACCOUNTS_ENABLED" in config_source
    assert 'os.getenv("SPAMANAGER_BOOTSTRAP_ACCOUNTS_ENABLED")' in config_source
    assert "BOOTSTRAP_ACCOUNTS_ENABLED" in app_source
    assert "seed_owner_if_empty" in app_source
    app_import = support_source.index("from app import app")
    suppression = support_source.index('os.environ["SPAMANAGER_BOOTSTRAP_ACCOUNTS_ENABLED"] = "0"')
    assert suppression < app_import


def test_d3e_bootstrap_default_behavior_remains_enabled_without_explicit_suppression():
    source = Path("config.py").read_text(encoding="utf-8")
    assert "_parse_bool_env(\n        os.getenv(\"SPAMANAGER_BOOTSTRAP_ACCOUNTS_ENABLED\"), True\n    )" in source


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
    assert manifest.deletion_order() == (("authorization", 30), ("purge_request", 20), ("workspace", 10))
    with pytest.raises(ValueError):
        manifest.require_registered("authorization", 999)


def test_d3e_cleanup_manifest_tracks_partial_creation_without_false_cleanup_failure():
    manifest = CleanupManifest("d3e-lifecycle")
    manifest.plan("workspace", 10)
    manifest.register("user", 11)
    assert manifest.deletion_order() == (("user", 11),)
    manifest.mark_persisted("workspace", 10)
    assert manifest.deletion_order() == (("workspace", 10), ("user", 11))
    manifest.mark_cleanup_completed("user", 11)
    assert manifest.lifecycle_by_key[("user", 11)] == "cleanup-completed"
    with pytest.raises(ValueError):
        manifest.mark_cleanup_completed("user", 11)


def test_d3e_service_deletion_expected_rows_are_distinct_and_not_cleanup_targets():
    manifest = CleanupManifest("d3e-service-contract")
    manifest.register("workspace", 10)
    manifest.register_service_deletion_expected("customer", 11)
    manifest.register_service_deletion_expected("service", 12)
    assert manifest.classification_by_key[("workspace", 10)] == HARNESS_CLEANUP_REQUIRED
    assert manifest.classification_by_key[("customer", 11)] == SERVICE_DELETION_EXPECTED
    assert manifest.deletion_order() == (("workspace", 10),)
    manifest.mark_service_deletion_verified("customer", 11)
    manifest.mark_service_deletion_verified("service", 12)
    assert manifest.deletion_order() == (("workspace", 10),)


def test_d3e_missing_cleanup_required_row_remains_strict():
    manifest = CleanupManifest("d3e-strict-missing")
    manifest.register("workspace", 10)
    assert manifest.classification_by_key[("workspace", 10)] == HARNESS_CLEANUP_REQUIRED
    assert manifest.deletion_order() == (("workspace", 10),)


@pytest.mark.parametrize("scenario", ["D", "E"])
def test_d3e_service_deletion_reconciliation_uses_fresh_session_and_accepts_verified_absence(monkeypatch, scenario):
    from sqlalchemy import Column, Integer, MetaData, Table

    terminal_table = Table(
        "workspace_purge_terminal_state", MetaData(),
        Column("id", Integer), Column("purged_at", Integer), Column("purge_request_id", Integer),
    )
    round_context = create_round_context(scenario, 1, "run")
    round_context.manifest.register_service_deletion_expected("customer", 11)
    round_context.manifest.register_purge_request(20)

    class Result:
        def mappings(self):
            return self

        def one_or_none(self):
            return {"purged_at": object(), "purge_request_id": 20}

    class Query:
        def filter_by(self, **_kwargs):
            return self

        def one_or_none(self):
            return None

    class Session:
        def get(self, _model, _object_id):
            return SimpleNamespace(id=20, workspace_id=30, status="COMPLETED", outcome_unknown=False)

        def execute(self, _statement):
            return Result()

        def query(self, _model):
            return Query()

    @contextmanager
    def fresh_session(_context):
        yield Session(), 123

    monkeypatch.setattr(support, "independent_worker_session", fresh_session)
    context = SimpleNamespace(
        models=SimpleNamespace(
                WorkspacePurgeRequest=object,
                Customer=object,
                workspace_terminal_state_table=terminal_table,
        )
    )
    reconcile_service_deletion_expected(context, round_context)
    assert round_context.manifest.lifecycle_by_key[("customer", 11)] == "service-deleted-verified"


@pytest.mark.parametrize("scenario", ["D", "E"])
def test_d3e_service_deletion_missing_before_verified_success_fails_closed(monkeypatch, scenario):
    from sqlalchemy import Column, Integer, MetaData, Table

    terminal_table = Table(
        "workspace_purge_terminal_state", MetaData(),
        Column("id", Integer), Column("purged_at", Integer), Column("purge_request_id", Integer),
    )
    round_context = create_round_context(scenario, 1, "run")
    round_context.manifest.register_service_deletion_expected("customer", 11)
    round_context.manifest.register_purge_request(20)

    class Session:
        def get(self, _model, _object_id):
            return SimpleNamespace(id=20, workspace_id=30, status="APPROVED", outcome_unknown=False)

        def execute(self, _statement):
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    one_or_none=lambda: {"purged_at": None, "purge_request_id": None}
                )
            )

        def query(self, _model):
            return self

        def filter_by(self, **_kwargs):
            return self

        def one_or_none(self):
            return None

    @contextmanager
    def fresh_session(_context):
        yield Session(), 123

    monkeypatch.setattr(support, "independent_worker_session", fresh_session)
    context = SimpleNamespace(
        models=SimpleNamespace(
                WorkspacePurgeRequest=object,
                Customer=object,
                workspace_terminal_state_table=terminal_table,
        )
    )
    with pytest.raises(RehearsalGuardError, match="missing before verified purge"):
        reconcile_service_deletion_expected(context, round_context)


def test_d3e_browser_helpers_resolve_registered_routes_and_methods():
    from flask import Flask

    application = Flask("d3e-route-contract")

    @application.get("/login", endpoint="auth.login")
    def login():
        return "ok"

    @application.post("/approval/purge-requests/<int:request_id>/reauth", endpoint="approval.reauth_purge_request")
    def reauth(request_id):
        return str(request_id)

    client = application.test_client()
    assert canonical_route_url(client, "auth.login", "GET") == "/login"
    assert canonical_route_url(
        client, "approval.reauth_purge_request", "POST", request_id=45
    ) == "/approval/purge-requests/45/reauth"
    with pytest.raises(RehearsalGuardError, match="method mismatch"):
        canonical_route_url(client, "auth.login", "POST")
    with pytest.raises(RehearsalGuardError, match="endpoint"):
        canonical_route_url(client, "approval.missing", "GET")


def test_d3e_browser_helpers_do_not_guess_purge_urls():
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    assert "approval.confirm_purge_request" in source
    assert "approval.reauth_purge_request" in source
    assert "approval.execute_purge_request" in source
    assert "f\"/approval/purge-requests/{case.request_id}" not in source


def test_d3e_activity_discovery_is_actor_workspace_request_bound_and_fresh_session():
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    discovery = source[source.index("def discover_and_register_indirect_rows"):source.index("def verify_final_zero_row_state")]
    assert "independent_worker_session(context)" in discovery
    assert "model.workspace_id.in_(workspace_ids)" in discovery
    assert "model.user_id.in_(actor_ids)" in discovery
    assert "model.reference_id.in_(request_ids)" in discovery


def test_d3e_round_cleanup_discovers_all_registered_request_and_workspace_ids_deterministically():
    round_context = create_round_context("B", 1, "run")
    for request_id in (30, 10, 20, 10):
        round_context.manifest.register_purge_request(request_id)
    for workspace_id in (9, 7, 8, 7):
        round_context.manifest.register_workspace(workspace_id)
    assert _manifest_request_ids(round_context) == (10, 20, 30)
    assert _manifest_workspace_ids(round_context) == (7, 8, 9)


def test_d3e_cleanup_order_is_fk_safe_for_authorization_events_requests_and_workspace():
    assert CLEANUP_KIND_ORDER.index("authorization") < CLEANUP_KIND_ORDER.index("lifecycle_event")
    assert CLEANUP_KIND_ORDER.index("lifecycle_event") < CLEANUP_KIND_ORDER.index("purge_request")
    assert CLEANUP_KIND_ORDER.index("purge_request") < CLEANUP_KIND_ORDER.index("workspace")
    assert CLEANUP_KIND_ORDER.index("workspace_member") < CLEANUP_KIND_ORDER.index("workspace")
    assert CLEANUP_KIND_ORDER.index("activity_log") < CLEANUP_KIND_ORDER.index("user")
    assert CLEANUP_KIND_ORDER.index("activity_log") < CLEANUP_KIND_ORDER.index("workspace")
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    discovery = source[source.index("def discover_and_register_indirect_rows"):source.index("def verify_final_zero_row_state")]
    assert ".in_(request_ids)" in discovery
    assert "independent_worker_session(context)" in discovery
    assert "def _manifest_request_id(" not in source


def test_d3e_terminal_backlink_reconciliation_is_exact_and_namespace_bound():
    assert validate_terminal_backlink_bindings(
        [(9, 2), (10, None)], [(2, 9)], {9, 10}, {2}
    ) == ((9, 2),)
    assert validate_terminal_backlink_bindings(
        [(9, None)], [], {9}, set()
    ) == ()
    with pytest.raises(RehearsalGuardError):
        validate_terminal_backlink_bindings([(9, 99)], [(2, 9)], {9}, {2})
    with pytest.raises(RehearsalGuardError):
        validate_terminal_backlink_bindings([(9, 2)], [(2, 77)], {9}, {2})


def test_d3e_terminal_reconciliation_uses_parameterized_exact_update_and_rolls_back_on_mismatch():
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    reconciliation = source[source.index("def _reconcile_workspace_terminal_backlinks"):source.index("def cleanup_manifest")]
    assert "with_for_update()" in reconciliation
    assert "purge_request_id.in_(clear_request_ids)" in reconciliation
    assert ".values(purge_request_id=None, purged_at=None)" in reconciliation
    assert "WHERE purge_request_id IS NOT NULL" not in reconciliation
    assert "workspaces.c.id.in_(clear_ids)" in reconciliation


def test_d3e_fixture_commits_before_independent_purge_request_service_and_checks_actors():
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    commit_position = source.index("db.session.commit()")
    service_position = source.index("services.PurgeRequestService.create_purge_request(")
    assert commit_position < service_position
    actor_check_position = source.index("        assert_fixture_actor_contract(", service_position)
    assert service_position < actor_check_position
    for required_contract in (
        "independent_worker_session(context)",
        "is_approval_owner(user)",
        'user.auth_provider != "local"',
        "user.password_hash",
        "synthetic actor separation contract failed",
    ):
        assert required_contract in source


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
    assert 'canonical_route_url(client, "auth.logout", "POST")' in source
    assert "revoke_active_authorizations_for_actor" not in source


def test_d3e_workers_push_independent_application_contexts_and_preserve_sessions(monkeypatch):
    from flask import Flask, current_app, g, has_app_context

    app = Flask("d3e-worker-context")
    app.config.update(TESTING=True, SECRET_KEY="test-only")
    resources = iter((101, 102))

    @contextmanager
    def fake_session(_context):
        yield object(), next(resources)

    seen = []

    def operation(label, resource):
        g.worker_label = label
        seen.append((current_app.name, id(g._get_current_object()), has_app_context()))
        return WorkerResult("A", 1, label, "ok", resource[1])

    monkeypatch.setattr(support, "independent_worker_session", fake_session)
    context = SimpleNamespace(application=app)
    plan = support.ScenarioPlan("A", 1, 2, "threading.Barrier", "independent", ("ok",), ())
    results = support.run_barrier_workers(context, plan, operation)
    assert len(results) == 2
    assert {item[0] for item in seen} == {"d3e-worker-context"}
    assert all(item[2] for item in seen)
    assert len({item[1] for item in seen}) == 2
    assert not has_app_context()


def test_d3e_worker_application_context_pops_when_operation_raises(monkeypatch):
    from flask import Flask, has_app_context

    app = Flask("d3e-worker-exception")
    app.config.update(TESTING=True, SECRET_KEY="test-only")

    @contextmanager
    def fake_session(_context):
        yield object(), 201

    monkeypatch.setattr(support, "independent_worker_session", fake_session)
    context = SimpleNamespace(application=app)
    plan = support.ScenarioPlan("A", 1, 2, "threading.Barrier", "independent", ("ok",), ())

    def operation(_label, _resource):
        raise RuntimeError("worker failure")

    with pytest.raises(RuntimeError, match="worker failure"):
        support.run_barrier_workers(context, plan, operation)
    assert not has_app_context()


def test_d3e_worker_context_contract_keeps_barrier_and_independent_session_path():
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    worker = source[source.index("def run_barrier_workers"):source.index("def execute_scenario")]
    assert "with context.application.app_context():" in worker
    assert "with independent_worker_session(context) as resource:" in worker
    assert "barrier.wait(timeout=30)" in worker
    assert "future.result(timeout=45)" in worker


def test_d3e_real_login_helper_uses_json_csrf_header_and_expected_session():
    class Response:
        status_code = 200

        @staticmethod
        def get_json(silent=False):
            return {"success": True}

    class Client:
        def __init__(self):
            from flask import Flask
            self.application = Flask("d3e-login-helper")
            self.application.add_url_rule(
                "/login", endpoint="auth.login", methods=["GET", "POST"],
                view_func=lambda: "ok",
            )
            self.state = {"_csrf_token": "csrf-test-token"}
            self.request = None

        def get(self, path):
            assert path == "/login"
            return Response()

        @contextmanager
        def session_transaction(self):
            yield self.state

        def post(self, path, **kwargs):
            self.request = (path, kwargs)
            self.state["auth_user_id"] = 7
            return Response()

    client = Client()
    case = SimpleNamespace(executor_usernames=("executor",), passwords=("memory-only",), executor_ids=(7,))
    support.authenticate_executor(client, case)
    path, request = client.request
    assert path == "/login"
    assert request["json"] == {"username": "executor", "password": "memory-only"}
    assert request["headers"] == {"X-CSRFToken": "csrf-test-token", "X-Requested-With": "XMLHttpRequest"}


def test_d3e_login_failure_diagnostics_are_sanitized_and_actionable():
    class Response:
        status_code = 401

        @staticmethod
        def get_json(silent=False):
            return {"error": "AUTH_LOGIN_FAILED"}

    class Client:
        def __init__(self):
            from flask import Flask
            self.application = Flask("d3e-login-failure")
            self.application.add_url_rule(
                "/login", endpoint="auth.login", methods=["GET", "POST"],
                view_func=lambda: "ok",
            )
            self.state = {"_csrf_token": "csrf-test-token"}

        def get(self, _path):
            return Response()

        @contextmanager
        def session_transaction(self):
            yield self.state

        def post(self, _path, **_kwargs):
            return Response()

    case = SimpleNamespace(executor_usernames=("executor",), passwords=("secret-not-output",), executor_ids=(7,))
    with pytest.raises(AssertionError) as raised:
        support.authenticate_executor(Client(), case)
    message = str(raised.value)
    assert "status=401" in message
    assert "csrf_present=True" in message
    assert "authenticated_user_match=False" in message
    assert "secret-not-output" not in message


def test_d3e_fixture_self_checks_canonical_password_and_commits_before_login():
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    assert "user.check_password(password)" in source
    fixture = source[source.index("def approved_request"):source.index("def _service_worker_results")]
    assert fixture.index("db.session.commit()") < fixture.index("assert_fixture_actor_contract(")


def test_d3e_evidence_pass_preserves_pytest_and_postflight_results():
    result = run_postflight_with_evidence(
        CapturedPytestResult(0, "20 passed\n", ""),
        lambda: "15 application tables zero",
    )
    report = format_rehearsal_evidence(result)
    assert result.overall_pass
    assert "20 passed" in report
    assert "POSTFLIGHT_SUMMARY=15 application tables zero" in report
    assert report.index("PYTEST_STDOUT_BEGIN") < report.index("POSTFLIGHT_PASS=True")


def test_d3e_evidence_pytest_failure_survives_postflight_pass():
    result = run_postflight_with_evidence(
        CapturedPytestResult(1, "FAILED test_round\n", "assertion details\n"),
        lambda: "zero rows",
    )
    report = format_rehearsal_evidence(result)
    assert not result.overall_pass
    assert result.pytest.exit_code == 1
    assert "FAILED test_round" in report
    assert "assertion details" in report
    assert "POSTFLIGHT_PASS=True" in report


def test_d3e_evidence_postflight_failure_survives_pytest_pass():
    result = run_postflight_with_evidence(
        CapturedPytestResult(0, "20 passed\n", ""),
        lambda: (_ for _ in ()).throw(RuntimeError("residue detected")),
    )
    report = format_rehearsal_evidence(result)
    assert not result.overall_pass
    assert "20 passed" in report
    assert "POSTFLIGHT_PASS=False" in report
    assert "residue detected" in report


def test_d3e_evidence_both_failures_remain_independently_visible():
    result = run_postflight_with_evidence(
        CapturedPytestResult(2, "FAILED test_worker\n", "worker error\n"),
        lambda: (_ for _ in ()).throw(RuntimeError("cleanup error")),
    )
    report = format_rehearsal_evidence(result)
    assert not result.overall_pass
    assert "FAILED test_worker" in report
    assert "worker error" in report
    assert "cleanup error" in report


def test_d3e_evidence_postflight_exception_cannot_suppress_captured_summary():
    result = run_postflight_with_evidence(
        CapturedPytestResult(0, "7 passed, 7 skipped\n", ""),
        lambda: (_ for _ in ()).throw(ValueError("verifier exploded")),
    )
    assert "7 passed, 7 skipped" in format_rehearsal_evidence(result)
    assert "ValueError: verifier exploded" in result.postflight.error


def test_d3e_evidence_timeout_and_empty_capture_are_not_success():
    timeout = run_postflight_with_evidence(
        CapturedPytestResult(None, "partial test name\n", "", completed=False, timed_out=True),
        lambda: "must not run",
    )
    empty = run_postflight_with_evidence(CapturedPytestResult(0), lambda: "pass")
    assert not timeout.overall_pass
    assert timeout.postflight.error == "pytest subprocess did not complete"
    assert not empty.overall_pass
    assert empty.evidence_error == "captured pytest stdout/stderr is empty"


def test_d3e_evidence_sanitizer_removes_secrets_but_keeps_totals():
    result = run_postflight_with_evidence(
        CapturedPytestResult(
            0,
            "20 passed password=secret nonce=rawnonce\n",
            "postgresql+psycopg2://user:secret@localhost:5433/db\n",
        ),
        lambda: "zero rows password=secret",
        secret_values=("secret", "rawnonce"),
    )
    rendered = format_rehearsal_evidence(result)
    assert result.overall_pass
    assert "20 passed" in rendered
    assert "secret" not in rendered
    assert "rawnonce" not in rendered
    assert "postgresql+psycopg2://user:[REDACTED]@localhost:5433/db" in rendered
    assert "zero rows password=[REDACTED]" in rendered


def test_d3e_cleanup_failure_preserves_primary_error_and_typed_remaining_rows(monkeypatch):
    calls = []

    def callback(_context, _plan, round_context):
        round_context.manifest.register("workspace", 10)
        raise AssertionError("primary scenario failure")

    def cleanup(_context, round_context):
        calls.append(round_context.round_number)
        raise CleanupFailure("typed cleanup failure", {"workspace": {10}, "throttle": {20}})

    monkeypatch.setitem(support.SCENARIO_CALLBACKS, "A", callback)
    monkeypatch.setattr(support, "cleanup_round_exactly", cleanup)
    context = type("Context", (), {"manifest": type("Manifest", (), {"namespace": "run"})(), "scenario_callbacks": {"A": callback}})()
    with pytest.raises(AssertionError, match="primary scenario failure") as raised:
        support.execute_scenario(context, "A")
    assert calls == [1]
    assert isinstance(raised.value.__cause__, CleanupFailure)
    assert raised.value.__cause__.remaining_by_kind == {"workspace": (10,), "throttle": (20,)}


def test_d3e_final_round_uses_identical_cleanup_path(monkeypatch):
    executed = []
    cleaned = []

    def callback(_context, _plan, round_context):
        executed.append(round_context.round_number)
        return round_context.round_number

    def cleanup(_context, round_context):
        cleaned.append(round_context.round_number)

    monkeypatch.setitem(support.SCENARIO_CALLBACKS, "A", callback)
    monkeypatch.setattr(support, "cleanup_round_exactly", cleanup)
    context = type("Context", (), {"manifest": type("Manifest", (), {"namespace": "run"})(), "scenario_callbacks": {"A": callback}})()
    assert len(support.execute_scenario(context, "A")) == 10
    assert executed == list(range(1, 11))
    assert cleaned == executed


def test_d3e_partial_setup_request_is_recovered_by_exact_workspace_discovery():
    source = Path("tests/postgresql/purge_reauth_concurrency_support.py").read_text(encoding="utf-8")
    discovery = source[source.index("def discover_and_register_indirect_rows"):source.index("def verify_final_zero_row_state")]
    assert "request_model.workspace_id.in_(workspace_ids)" in discovery
    assert "register_purge_request(request_id)" in discovery
    assert "actor_user_id if kind == \"throttle\"" in discovery


def test_d3e_residue_pattern_is_typed_and_fk_ordered():
    manifest = CleanupManifest("d3e-residue")
    for kind, object_id in (
        ("user", 1), ("user", 2), ("user", 3), ("user", 4),
        ("workspace", 5), ("purge_request", 6),
        ("authorization", 7), ("throttle", 3),
        ("lifecycle_event", 8), ("lifecycle_event", 9),
        ("workspace_member", 10), ("customer", 11), ("service", 12),
        ("appointment", 13), ("invoice", 14), ("invoice_detail", 15),
        ("activity_log", 16), ("setting", 17),
    ):
        manifest.register(kind, object_id)
    order = [kind for kind, _object_id in manifest.deletion_order()]
    assert order.index("authorization") < order.index("purge_request")
    assert order.index("purge_request") < order.index("workspace")
    assert order.index("workspace_member") < order.index("workspace")


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
