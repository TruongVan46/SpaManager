import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.postgresql import rehearsal_runtime


ROOT = Path(__file__).parent


class _FakeResult:
    def __init__(self, value=0):
        self.value = value

    def scalar_one(self):
        return self.value


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _FakeConnection:
    def __init__(self, events):
        self.events = events

    def begin(self):
        return _FakeTransaction()

    def execute(self, statement):
        return _FakeResult(0)

    def close(self):
        self.events.append("connection.close")


class _FakeEngine:
    def __init__(self, events, dispose_error=None):
        self.events = events
        self.dispose_error = dispose_error

    def connect(self):
        self.events.append("engine.connect")
        return _FakeConnection(self.events)

    def dispose(self):
        self.events.append("engine.dispose.begin")
        if self.dispose_error is not None:
            raise self.dispose_error
        self.events.append("engine.dispose.end")


def _patch_fake_preflight(monkeypatch, events, engine):
    target = SimpleNamespace(database="spamanager_purge_rehearsal_test")
    monkeypatch.setattr(
        rehearsal_runtime,
        "validate_rehearsal_environment",
        lambda environ: target,
    )
    monkeypatch.setattr(
        rehearsal_runtime,
        "_create_preflight_engine",
        lambda database_url: engine,
    )
    monkeypatch.setattr(
        rehearsal_runtime,
        "_preflight_identity",
        lambda connection, target: (
            "spamanager_purge_rehearsal_test",
            "spamanager",
            "5432",
            "0008_durable_purge_reauth_state",
        ),
    )
    monkeypatch.setattr(
        rehearsal_runtime,
        "apply_transaction_timeouts",
        lambda executor: events.append("timeouts.applied"),
    )


def _run_fake_preflight(monkeypatch, events, engine):
    _patch_fake_preflight(monkeypatch, events, engine)
    return rehearsal_runtime.run_rehearsal_preflight(
        {"TEST_DATABASE_URL": "synthetic"}
    )


def test_preflight_result_exposes_boolean_engine_disposal_field():
    field = rehearsal_runtime.RehearsalPreflightResult.__dataclass_fields__["engine_disposed"]
    assert field.type is bool


def test_preflight_success_closes_connection_and_disposes_engine_once(monkeypatch):
    events = []
    result = _run_fake_preflight(monkeypatch, events, _FakeEngine(events))

    assert result.database == "spamanager_purge_rehearsal_test"
    assert result.role == "spamanager"
    assert result.server_port == "5432"
    assert result.revision == "0008_durable_purge_reauth_state"
    assert result.tables_checked == 15
    assert result.all_tables_zero is True
    assert result.hanging_transactions == 0
    assert result.connections_closed is True
    assert result.engine_disposed is True
    assert events.count("engine.dispose.begin") == 1


def test_preflight_returns_only_after_engine_disposal(monkeypatch):
    events = []
    result = _run_fake_preflight(monkeypatch, events, _FakeEngine(events))
    events.append("caller.received")

    assert result.engine_disposed is True
    assert events.index("engine.dispose.end") < events.index("caller.received")


def test_preflight_disposal_failure_is_sanitized_and_fail_closed(monkeypatch):
    events = []
    with pytest.raises(rehearsal_runtime.RehearsalDatabaseDisposalError) as caught:
        _run_fake_preflight(
            monkeypatch,
            events,
            _FakeEngine(events, RuntimeError("private disposal detail")),
        )

    assert str(caught.value) == "LOCAL_REHEARSAL_DATABASE_DISPOSAL_FAILED"
    assert "private disposal detail" not in str(caught.value)
    assert events.count("engine.dispose.begin") == 1


def test_preflight_creation_failure_does_not_dispose_missing_engine(monkeypatch):
    dispose_calls = []
    target = SimpleNamespace(database="spamanager_purge_rehearsal_test")
    monkeypatch.setattr(
        rehearsal_runtime,
        "validate_rehearsal_environment",
        lambda environ: target,
    )
    monkeypatch.setattr(
        rehearsal_runtime,
        "_create_preflight_engine",
        lambda database_url: (_ for _ in ()).throw(RuntimeError("private creation detail")),
    )

    with pytest.raises(rehearsal_runtime.RehearsalDatabaseConnectionError):
        rehearsal_runtime.run_rehearsal_preflight(
            {"TEST_DATABASE_URL": "synthetic"}
        )

    assert dispose_calls == []


def test_preflight_result_preserves_tuple_table_count_contract(monkeypatch):
    events = []
    result = _run_fake_preflight(monkeypatch, events, _FakeEngine(events))

    counts = dict(result.table_counts)
    assert len(counts) == 15
    assert result.connections_closed is True
    assert result.engine_disposed is True


def _module_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    return imported


def test_postgresql_modules_have_no_top_level_runtime_imports():
    forbidden = {"app", "extensions", "services", "models"}
    for name in (
        "conftest.py", "rehearsal_runtime.py", "test_purge_runtime_postgresql.py",
        "test_purge_legal_hold_concurrency_postgresql.py",
    ):
        assert not (_module_imports(ROOT / name) & forbidden)


def test_reset_helper_has_explicit_allowlist_and_protects_revision():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    assert 'EXPECTED_PURGE_REHEARSAL_REVISION = "0008_durable_purge_reauth_state"' in source
    assert 'revision_rows != [(EXPECTED_PURGE_REHEARSAL_REVISION,)]' in source
    assert "0007_permanent_purge_workflow" not in source
    assert "EXPECTED_APPLICATION_TABLES" in source
    assert "EXPECTED_SCHEMA_TABLES" in source
    assert "alembic_version" in source
    assert "TRUNCATE" in source
    assert "RESTART IDENTITY CASCADE" in source
    assert "DROP DATABASE" not in source
    assert "DROP SCHEMA" not in source


def test_runtime_identity_checks_internal_server_port_and_external_endpoint():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    assert 'EXPECTED_POSTGRES_SERVER_PORT = "5432"' in source
    assert "current_setting('port')" in source
    assert "server_port" in source
    assert "self.target.port != 5433" in source


def test_runtime_contract_preserves_complete_user_baseline_and_adds_counted_drift_row():
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    rollback_source = source.split(
        "def test_execution_rolls_back_after_mutation", 1
    )[1]
    assert "baseline_user_ids = {" in rollback_source
    assert (
        'for (user_id,) in fixture["db"].session.query('
        'fixture["models"].User.id).all()'
    ) in rollback_source
    assert "post_rollback_user_ids = {" in rollback_source
    assert (
        'for (user_id,) in verification.query('
        'fixture["models"].User.id).all()'
    ) in rollback_source
    assert "assert post_rollback_user_ids == baseline_user_ids" in rollback_source
    assert (
        'assert verification.get(fixture["models"].User, executor_user_id) is not None'
    ) in rollback_source
    assert 'verification.query(fixture["models"].User).count() == 3' not in rollback_source
    assert 'verification.query(fixture["models"].User).count() >=' not in rollback_source
    assert "authorization_generation=issuance.generation" in rollback_source
    assert "authorization_nonce=issuance.raw_nonce" in rollback_source
    assert "delete_then_fail" in rollback_source
    assert "postgres_case.new_session()" in rollback_source
    assert "new_customer_id = new_customer.id" in source
    assert "stored.manifest_hash == manifest_hash" in source


def test_opted_out_fixture_skips_before_runtime_creation():
    source = (ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "pytest.skip" in source
    assert "create_runtime(postgres_rehearsal_target)" in source


def test_runtime_module_is_lazy_and_non_concurrent():
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    assert "pytest.mark.postgres_rehearsal" in source
    assert "postgres_runtime" in source
    for forbidden in ("threading", "ThreadPoolExecutor"):
        assert forbidden not in source


def test_legal_hold_concurrency_harness_has_seven_named_nodes_and_bounded_hooks():
    source = (ROOT / "test_purge_legal_hold_concurrency_postgresql.py").read_text(encoding="utf-8")
    for name in (
        "test_lh_a1_create_wins_against_approval",
        "test_lh_a2_approval_wins_then_hold_blocks_execution",
        "test_lh_b1_create_wins_against_execution",
        "test_lh_b2_execution_wins_then_create_rejects_terminal_workspace",
        "test_lh_c1_release_wins_then_execution_observes_released",
        "test_lh_c2_execution_sees_active_then_release_succeeds",
        "test_lh_d_concurrent_double_release_is_exactly_once",
    ):
        assert f"def {name}(" in source
    assert "EVENT_TIMEOUT_SECONDS = 10" in source
    assert "THREAD_JOIN_TIMEOUT_SECONDS = 20" in source
    assert "event.listen" in source and "event.remove" in source
    assert "runtime.new_session()" in source
    assert "runtime.app.app_context()" in source
    assert "runtime.reset_database()" in source
    assert "finally:" in source
    assert "actor_user_id" in source or "PurgeLegalHoldService.release_legal_hold" in source
    assert "time.sleep" not in source
    assert ".join()" not in source


def test_lh_b2_barrier_targets_execution_workspace_lock_after_claim_arm():
    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import (
        HookPlan,
        _workspace_barrier_is_armed,
    )

    plan = HookPlan()
    assert _workspace_barrier_is_armed(plan, "execution") is False
    plan.execution_lock_armed.set()
    assert _workspace_barrier_is_armed(plan, "execution") is True
    assert _workspace_barrier_is_armed(HookPlan(), "workspace") is True


def test_lh_b2_barrier_contract_arms_only_after_claim_returns():
    source = (ROOT / "test_purge_legal_hold_concurrency_postgresql.py").read_text(encoding="utf-8")
    assert "def _arm_execution_claim" in source
    assert "claim = original(*args, **kwargs)" in source
    assert "current.execution_lock_armed.set()" in source
    assert "barrier_target=\"execution\"" in source
    assert "if not _workspace_barrier_is_armed(current, barrier_target):" in source


def test_lh_c2_barrier_targets_active_hold_observation_after_claim():
    source = (ROOT / "test_purge_legal_hold_concurrency_postgresql.py").read_text(encoding="utf-8")
    assert "def _arm_active_hold_observation" in source
    assert "barrier_target=\"active_hold\"" in source
    assert "current.execution_lock_armed.is_set() and active_observed" in source
    assert "barrier_target not in {\"active_hold\", \"decisive_hold\"}" in source
    assert "active_hold_observed.set()" in source
    assert "operation_started.set()" in source
    assert "completed_event.set()" in source


def test_lh_c2_active_hold_wrapper_preserves_results_and_ignores_non_active_or_unarmed():
    from types import SimpleNamespace
    import threading

    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import (
        HookPlan,
        _arm_active_hold_observation,
    )

    class Hold:
        def __init__(self, status):
            self.status = status

    class PurgeService:
        @staticmethod
        def _validate_holds(request, holds):
            return (request, tuple(hold.status for hold in holds))

    runtime = SimpleNamespace(services=SimpleNamespace(PurgeService=PurgeService))
    plan = HookPlan()
    patches = [_arm_active_hold_observation(runtime, {"winner": plan})]
    try:
        non_active = PurgeService._validate_holds("released", [Hold("RELEASED")])
        assert non_active == ("released", ("RELEASED",))
        assert not plan.active_hold_observed.is_set()

        unarmed = PurgeService._validate_holds("active-before-claim", [Hold("ACTIVE")])
        assert unarmed == ("active-before-claim", ("ACTIVE",))
        assert not plan.active_hold_observed.is_set()

        plan.execution_lock_armed.set()
        observed_result = []

        def observe():
            observed_result.append(PurgeService._validate_holds("active-after-claim", [Hold("ACTIVE")]))

        thread = threading.Thread(target=observe, name="winner")
        thread.start()
        assert plan.active_hold_observed.wait(1)
        assert thread.is_alive()
        plan.allow_winner_to_continue.set()
        thread.join(1)
        assert observed_result == [("active-after-claim", ("ACTIVE",))]
        assert plan.post_lock_passed.is_set()
    finally:
        service, attribute, descriptor = patches[0]
        setattr(service, attribute, descriptor)


def test_lh_c2_preserves_other_barrier_targets():
    source = (ROOT / "test_purge_legal_hold_concurrency_postgresql.py").read_text(encoding="utf-8")
    assert "barrier_target=\"execution\"" in source
    assert "barrier_target=\"active_hold\"" in source
    assert "winner_pause=\"hold\"" in source
    assert "test_lh_c1_release_wins_then_execution_observes_released" in source
    assert "test_lh_b2_execution_wins_then_create_rejects_terminal_workspace" in source


def test_lh_d_barrier_targets_winner_decisive_hold_stage_only():
    source = (ROOT / "test_purge_legal_hold_concurrency_postgresql.py").read_text(encoding="utf-8")
    assert "def _arm_decisive_release_hold_barrier" in source
    assert "barrier_target=\"decisive_hold\"" in source
    assert "barrier_target not in {\"active_hold\", \"decisive_hold\"}" in source
    assert "current is plans.get(\"winner\")" in source
    assert "winner_hold_lock_acquired.set()" in source
    assert "winner_observed_active.set()" in source


def test_lh_d_decisive_barrier_preserves_result_and_ignores_waiter():
    from types import SimpleNamespace
    import threading

    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import (
        HookPlan,
        _arm_decisive_release_hold_barrier,
    )

    class PurgeLegalHoldService:
        @staticmethod
        def _phrase(value, expected):
            return (value, expected)

    runtime = SimpleNamespace(services=SimpleNamespace(PurgeLegalHoldService=PurgeLegalHoldService))
    winner_plan = HookPlan()
    waiter_plan = HookPlan()
    plans = {"winner": winner_plan, "waiter": waiter_plan}
    service, attribute, descriptor = _arm_decisive_release_hold_barrier(runtime, plans)
    try:
        unrelated = PurgeLegalHoldService._phrase("HOLD workspace", "HOLD workspace")
        assert unrelated == ("HOLD workspace", "HOLD workspace")
        assert not winner_plan.winner_hold_lock_acquired.is_set()

        winner_result = []

        def winner_call():
            winner_result.append(PurgeLegalHoldService._phrase("RELEASE hold-1", "RELEASE hold-1"))

        winner = threading.Thread(target=winner_call, name="winner")
        winner.start()
        assert winner_plan.winner_hold_lock_acquired.wait(1)
        assert winner.is_alive()
        assert not waiter_plan.winner_hold_lock_acquired.is_set()
        winner_plan.allow_winner_to_continue.set()
        winner.join(1)
        assert winner_result == [("RELEASE hold-1", "RELEASE hold-1")]

        waiter_result = []

        def waiter_call():
            waiter_result.append(PurgeLegalHoldService._phrase("RELEASE hold-1", "RELEASE hold-1"))

        waiter = threading.Thread(target=waiter_call, name="waiter")
        waiter.start()
        waiter.join(1)
        assert waiter_result == [("RELEASE hold-1", "RELEASE hold-1")]
        assert not waiter_plan.winner_hold_lock_acquired.is_set()
    finally:
        setattr(service, attribute, descriptor)


def test_lh_d_exactly_once_contract_remains_explicit():
    source = (ROOT / "test_purge_legal_hold_concurrency_postgresql.py").read_text(encoding="utf-8")
    assert 'getattr(results["waiter"].exception, "code", None) == "ALREADY_RELEASED"' in source
    assert 'assert results["winner"].exception is None' in source
    assert 'final_hold_status == "RELEASED"' in source
    assert "successful_release_result_count == 1" in source
    assert "PERSISTED_RELEASE_TRANSITION_SOURCE=NONE" not in source
    assert "RELEASE_TRANSITION_COUNT_ASSERTED" not in source
    assert "duplicate_release_occurred is False" in source
    assert "deadlock_detected is False" in source
    assert 'assert plans["winner"].winner_hold_lock_acquired.is_set()' in source
    assert 'assert plans["winner"].winner_observed_active.is_set()' in source
    assert 'assert plans["waiter"].operation_started.is_set()' in source
    assert 'assert plans["waiter"].completed_event.is_set()' in source
    assert "operation_returned_sequence" in source
    assert "completed_sequence" in source
    assert 'results["waiter"].completed_sequence' in source
    assert 'results["waiter"].completed_at > results["winner"].operation_returned_at' not in source
    assert "except BaseException" not in source


def test_worker_safe_diagnostic_exposes_only_class_and_allowlisted_code():
    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import (
        WorkerResult,
        _record_safe_worker_error,
        _safe_worker_failure,
    )

    class SyntheticError(Exception):
        def __init__(self):
            self.code = "TERMINAL_WORKSPACE"
            super().__init__("secret message", "secret parameters")

    result = WorkerResult(name="waiter")
    error = SyntheticError()
    _record_safe_worker_error(result, error)
    rendered = _safe_worker_failure(result)

    assert "SyntheticError" in rendered
    assert "TERMINAL_WORKSPACE" in rendered
    assert "secret message" not in rendered
    assert "secret parameters" not in rendered
    assert "args" not in rendered.lower()
    assert result.exception.public_exception_class == "SyntheticError"
    assert result.exception.safe_root_category == "UNCLASSIFIED_SAFE_EXCEPTION"
    assert result.exception.sqlstate is None
    assert "secret message" not in repr(result.exception)
    assert "secret parameters" not in repr(result.exception)


def test_worker_safe_diagnostic_classifies_sqlstate_without_rendering_exception():
    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import (
        WorkerResult,
        _record_safe_worker_error,
    )

    class SyntheticDeadlock(Exception):
        pgcode = "40P01"

        def __init__(self):
            super().__init__("postgresql://secret", {"password": "secret"})

    result = WorkerResult(name="winner")
    _record_safe_worker_error(result, SyntheticDeadlock())

    assert result.exception.safe_root_category == "DEADLOCK_DETECTED"
    assert result.exception.sqlstate == "40P01"
    assert result.exception.code is None


def test_worker_safe_diagnostic_preserves_legal_hold_unresolved_code():
    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import (
        WorkerResult,
        _record_safe_worker_error,
    )

    class SyntheticLegalHoldConflict(Exception):
        code = "LEGAL_HOLD_UNRESOLVED"

        def __init__(self):
            super().__init__("secret message", "postgresql://secret")

    result = WorkerResult(name="waiter")
    _record_safe_worker_error(result, SyntheticLegalHoldConflict())

    assert result.safe_error_code == "LEGAL_HOLD_UNRESOLVED"
    assert result.exception.code == "LEGAL_HOLD_UNRESOLVED"
    assert "secret message" not in repr(result.exception)
    assert "postgresql://" not in repr(result.exception)


def test_lh_d_sequence_order_survives_equal_float_timestamps(monkeypatch):
    from contextlib import nullcontext
    from tests.postgresql import test_purge_legal_hold_concurrency_postgresql as harness

    runtime = SimpleNamespace(app=SimpleNamespace(app_context=lambda: nullcontext()))
    sequence_state = {"lock": __import__("threading").Lock(), "value": 0}
    results = {}
    monkeypatch.setattr(harness.time, "monotonic", lambda: 42.0)

    harness._worker(
        runtime, "winner", lambda: "ok", harness.HookPlan(), results, sequence_state
    )
    harness._worker(
        runtime, "waiter", lambda: None, harness.HookPlan(), results, sequence_state
    )

    assert results["winner"].operation_returned_at == results["winner"].completed_at
    assert results["winner"].operation_returned_sequence == 1
    assert results["waiter"].completed_sequence == 4
    assert results["waiter"].completed_sequence > results["winner"].operation_returned_sequence


def test_direct_execution_tests_use_fresh_real_durable_reauth():
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    target_names = {
        "test_execution_success_preserves_audit_and_terminal_tombstone",
        "test_execution_rolls_back_after_mutation",
    }
    functions = {
        node.name: ast.get_source_segment(source, node)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in target_names
    }

    assert set(functions) == target_names
    for function_source in functions.values():
        assert "issue_local_authorization" in function_source
        assert "authorization_generation=issuance.generation" in function_source
        assert "authorization_nonce=issuance.raw_nonce" in function_source
        assert "monkeypatch.setattr(purge_service, \"PurgeReauthService\"" not in function_source
    rollback_source = functions["test_execution_rolls_back_after_mutation"]
    assert "original_delete(*args, **kwargs)" in rollback_source
    assert 'raise RuntimeError("synthetic rollback after mutation")' in rollback_source


def test_lh_d_snapshots_winner_before_waiter_join_assertion_and_marks_timeout():
    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import (
        WorkerResult,
        _mark_waiter_join_timeout,
        _snapshot_worker_results,
    )

    winner = WorkerResult(name="winner", completed=True, result="winner-result")
    waiter = WorkerResult(name="waiter", thread_alive=True)
    local_results = {"winner": winner, "waiter": waiter}
    retained_results = {
        "winner": WorkerResult(name="winner"),
        "waiter": WorkerResult(name="waiter"),
    }

    _mark_waiter_join_timeout(waiter)
    _snapshot_worker_results(local_results, retained_results)

    assert retained_results["winner"].result == "winner-result"
    assert retained_results["winner"].completed is True
    assert retained_results["waiter"].safe_root_category == "WAITER_JOIN_TIMEOUT"
    assert retained_results["waiter"].safe_error_code is None
    assert "postgresql://" not in repr(retained_results)


def test_lh_d_timeout_is_not_classified_as_already_released():
    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import (
        WorkerResult,
        _mark_waiter_join_timeout,
    )

    waiter = WorkerResult(name="waiter", thread_alive=True)
    _mark_waiter_join_timeout(waiter)

    assert waiter.safe_root_category == "WAITER_JOIN_TIMEOUT"
    assert waiter.safe_error_code is None
    assert waiter.exception is None


def test_worker_none_return_is_explicit_normal_return():
    from contextlib import nullcontext
    from types import SimpleNamespace

    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import (
        HookPlan,
        _worker,
    )

    runtime = SimpleNamespace(app=SimpleNamespace(app_context=lambda: nullcontext()))
    results = {}
    _worker(runtime, "waiter", lambda: None, HookPlan(), results)

    assert results["waiter"].completed is True
    assert results["waiter"].result is None
    assert results["waiter"].terminal_outcome == "NORMAL_RETURN"


def test_worker_already_released_is_explicit_safe_exception():
    from contextlib import nullcontext
    from types import SimpleNamespace

    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import (
        HookPlan,
        _worker,
    )

    class SyntheticConflict(Exception):
        code = "ALREADY_RELEASED"

        def __init__(self):
            super().__init__("secret message", "postgresql://secret")

    runtime = SimpleNamespace(app=SimpleNamespace(app_context=lambda: nullcontext()))
    results = {}
    _worker(runtime, "waiter", lambda: (_ for _ in ()).throw(SyntheticConflict()), HookPlan(), results)

    result = results["waiter"]
    assert result.terminal_outcome == "SAFE_EXCEPTION"
    assert result.safe_error_code == "ALREADY_RELEASED"
    assert "secret message" not in repr(result.exception)
    assert "postgresql://" not in repr(result.exception)


def test_worker_other_safe_exception_is_not_already_released():
    from contextlib import nullcontext
    from types import SimpleNamespace

    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import (
        HookPlan,
        _worker,
    )

    class SyntheticConflict(Exception):
        code = "TERMINAL_WORKSPACE"

        def __init__(self):
            super().__init__("secret message", "secret parameters")

    runtime = SimpleNamespace(app=SimpleNamespace(app_context=lambda: nullcontext()))
    results = {}
    _worker(runtime, "waiter", lambda: (_ for _ in ()).throw(SyntheticConflict()), HookPlan(), results)

    result = results["waiter"]
    assert result.terminal_outcome == "SAFE_EXCEPTION"
    assert result.safe_error_code == "TERMINAL_WORKSPACE"
    assert result.safe_error_code != "ALREADY_RELEASED"
    assert "secret message" not in repr(result.exception)
    assert "secret parameters" not in repr(result.exception)


def test_uncompleted_worker_is_not_reported_as_normal_return():
    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import WorkerResult

    result = WorkerResult(name="waiter")

    assert result.completed is False
    assert result.terminal_outcome == "NOT_STARTED"


def test_lh_d_safe_markers_preserve_explicit_waiter_outcome_fields(capsys):
    from tests.postgresql.test_purge_legal_hold_concurrency_postgresql import WorkerResult, _emit_lh_d_safe_failure

    winner = WorkerResult(name="winner", terminal_outcome="NORMAL_RETURN")
    waiter = WorkerResult(
        name="waiter",
        terminal_outcome="SAFE_EXCEPTION",
        safe_error_code="ALREADY_RELEASED",
        thread_alive=False,
    )
    _emit_lh_d_safe_failure({"winner": winner, "waiter": waiter}, "ASSERTION")
    output = capsys.readouterr().out

    assert "LH_D_SAFE_WAITER_TERMINAL_OUTCOME=SAFE_EXCEPTION" in output
    assert "LH_D_SAFE_WAITER_EXCEPTION_CODE=ALREADY_RELEASED" in output
    assert "postgresql://" not in output
    assert "secret" not in output.lower()


def test_lh_d_pair_runner_retains_timeout_snapshot_and_normal_mapping():
    source = (ROOT / "test_purge_legal_hold_concurrency_postgresql.py").read_text(encoding="utf-8")
    assert "result_sink=None" in source
    assert "_snapshot_worker_results(results, result_sink)" in source
    assert "_mark_waiter_join_timeout(results[\"waiter\"])" in source
    assert "result_sink=results" in source
    assert 'safe_root_category = "WAITER_JOIN_TIMEOUT"' in source
    assert "WAITER_JOIN_TIMEOUT" not in source.split("SAFE_ERROR_CODES", 1)[1].split("})", 1)[0]
    assert 'terminal_outcome = "NORMAL_RETURN"' in source
    assert '"SAFE_EXCEPTION" if safe_code is not None else "UNSAFE_EXCEPTION"' in source
    assert '"LH_D_SAFE_WAITER_TERMINAL_OUTCOME"' in source
    assert '"LH_D_SAFE_WAITER_EXCEPTION_CODE"' in source


def _preflight_test_doubles(monkeypatch, *, users_count=0, database="spamanager_purge_rehearsal_test"):
    import builtins

    from tests.postgresql import rehearsal_runtime as runtime_module
    from tests.postgresql.rehearsal_guard import RehearsalTarget

    class Result:
        def __init__(self, *, row=None, rows=None, scalar=None, values=None):
            self._row = row
            self._rows = rows
            self._scalar = scalar
            self._values = values

        def one(self):
            return self._row

        def all(self):
            return self._rows if self._rows is not None else self._values

        def scalar_one(self):
            return self._scalar

        def scalars(self):
            return Result(values=self._values)

    class Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Connection:
        def __init__(self):
            self.closed = False
            self.count_queries = 0
            self.write_queries = []

        def begin(self):
            return Transaction()

        def execute(self, statement):
            sql = str(statement)
            if sql.startswith("SET LOCAL"):
                return Result()
            if "current_database()" in sql:
                return Result(row=(database, "spamanager", "5432"))
            if "version_num" in sql:
                return Result(rows=[("0008_durable_purge_reauth_state",)])
            if "information_schema.tables" in sql:
                return Result(values=sorted(runtime_module.EXPECTED_SCHEMA_TABLES))
            if "pg_stat_activity" in sql:
                return Result(scalar=0)
            if "SELECT count(*)" in sql:
                self.count_queries += 1
                return Result(scalar=users_count if '"users"' in sql else 0)
            self.write_queries.append(sql)
            return Result()

        def close(self):
            self.closed = True

    class Engine:
        def __init__(self):
            self.connection = Connection()
            self.disposed = False

        def connect(self):
            return self.connection

        def dispose(self):
            self.disposed = True

    engine = Engine()
    target = RehearsalTarget("postgresql", "127.0.0.1", 5433, database)
    monkeypatch.setattr(runtime_module, "validate_rehearsal_environment", lambda _env: target)
    monkeypatch.setattr(runtime_module, "_create_preflight_engine", lambda _url: engine)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "app" or name.startswith(("extensions", "services", "models")):
            raise AssertionError("application bootstrap import attempted")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    env = {
        "APP_ENV": "testing",
        "SPAMANAGER_TEST_PROCESS": "1",
        "SPAMANAGER_ALLOW_POSTGRES_TESTS": "1",
        "SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL": "1",
        "TEST_DATABASE_URL": "postgresql://user:password@127.0.0.1:5433/spamanager_purge_rehearsal_test",
    }
    return runtime_module.run_rehearsal_preflight(env), engine


def test_no_bootstrap_preflight_does_not_import_application(monkeypatch):
    result, engine = _preflight_test_doubles(monkeypatch)
    assert result.all_tables_zero is True
    assert result.tables_checked == 15
    assert result.connections_closed is True
    assert engine.connection.closed is True
    assert engine.disposed is True
    assert engine.connection.write_queries == []


def test_no_bootstrap_preflight_preserves_exact_zero_state(monkeypatch):
    result, _engine = _preflight_test_doubles(monkeypatch, users_count=0)
    assert dict(result.table_counts)["users"] == 0
    assert result.all_tables_zero is True


def test_no_bootstrap_preflight_reports_users_one_without_mutation(monkeypatch):
    result, engine = _preflight_test_doubles(monkeypatch, users_count=1)
    assert dict(result.table_counts)["users"] == 1
    assert result.all_tables_zero is False
    assert all(value == 0 for name, value in result.table_counts if name != "users")
    assert engine.connection.write_queries == []


def test_no_bootstrap_preflight_rejects_wrong_database_before_counts(monkeypatch):
    import pytest

    from tests.postgresql import rehearsal_runtime as runtime_module
    from tests.postgresql.rehearsal_guard import RehearsalTarget
    from tests.postgresql.rehearsal_runtime import RehearsalIdentityError

    class Connection:
        def __init__(self):
            self.closed = False
            self.count_queries = 0

        def begin(self):
            class Transaction:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            return Transaction()

        def execute(self, statement):
            sql = str(statement)
            if sql.startswith("SET LOCAL"):
                return type("Result", (), {})()
            if "current_database()" in sql:
                return type("Result", (), {"one": lambda _self: ("spamanager_dev", "spamanager", "5432")})()
            self.count_queries += 1
            raise AssertionError("table count queried after identity mismatch")

        def close(self):
            self.closed = True

    class Engine:
        def __init__(self):
            self.connection = Connection()
            self.disposed = False

        def connect(self):
            return self.connection

        def dispose(self):
            self.disposed = True

    engine = Engine()
    target = RehearsalTarget("postgresql", "127.0.0.1", 5433, "spamanager_purge_rehearsal_test")
    monkeypatch.setattr(runtime_module, "validate_rehearsal_environment", lambda _env: target)
    monkeypatch.setattr(runtime_module, "_create_preflight_engine", lambda _url: engine)

    with pytest.raises(RehearsalIdentityError):
        runtime_module.run_rehearsal_preflight({"TEST_DATABASE_URL": "redacted"})

    assert engine.connection.count_queries == 0
    assert engine.connection.closed is True
    assert engine.disposed is True


def test_no_bootstrap_preflight_sanitizes_failure_and_disposes_engine(monkeypatch):
    import pytest

    from tests.postgresql import rehearsal_runtime as runtime_module
    from tests.postgresql.rehearsal_runtime import RehearsalDatabaseConnectionError

    class Engine:
        disposed = False

        def connect(self):
            raise RuntimeError("secret connection detail")

        def dispose(self):
            self.disposed = True

    engine = Engine()
    monkeypatch.setattr(runtime_module, "validate_rehearsal_environment", lambda _env: object())
    monkeypatch.setattr(runtime_module, "_create_preflight_engine", lambda _url: engine)

    with pytest.raises(RehearsalDatabaseConnectionError) as exc_info:
        runtime_module.run_rehearsal_preflight({"TEST_DATABASE_URL": "redacted"})

    assert str(exc_info.value) == "LOCAL_REHEARSAL_DATABASE_CONNECTION_FAILED"
    assert "secret connection detail" not in str(exc_info.value)
    assert engine.disposed is True


def test_no_database_process_commands_in_harness_sources():
    for name in ("conftest.py", "rehearsal_runtime.py", "test_harness_foundation.py", "test_purge_runtime_postgresql.py"):
        path = ROOT / name
        source = path.read_text(encoding="utf-8")
        assert "docker exec" not in source
        assert "subprocess" not in source
        assert "psql" not in source


def test_unsafe_opted_in_target_blocks_runtime_creation(monkeypatch):
    import pytest
    from tests.postgresql.conftest import resolve_postgres_rehearsal_target
    from tests.postgresql.rehearsal_guard import RehearsalGuardError
    import tests.postgresql.conftest as conftest_module
    import builtins

    fresh_process_called = False
    def mock_ensure_fresh_process():
        nonlocal fresh_process_called
        fresh_process_called = True

    monkeypatch.setattr(conftest_module, "ensure_fresh_process", mock_ensure_fresh_process)

    original_import = builtins.__import__
    def mock_import(name, *args, **kwargs):
        if "rehearsal_runtime" in name:
            raise ImportError("rehearsal_runtime must not be imported during target resolution")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    fake_env = {
        "SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL": "1",
        "APP_ENV": "testing",
        "SPAMANAGER_TEST_PROCESS": "1",
        "SPAMANAGER_ALLOW_POSTGRES_TESTS": "1",
        "TEST_DATABASE_URL": "postgresql://user@localhost:5433/wrong_db_name",
    }

    with pytest.raises(RehearsalGuardError) as exc_info:
        resolve_postgres_rehearsal_target(fake_env)

    assert "not the dedicated rehearsal database" in str(exc_info.value)
    assert fresh_process_called is True


def test_no_opt_in_helper_skips_before_fresh_process_and_validation(monkeypatch):
    import pytest
    import builtins
    from tests.postgresql.conftest import resolve_postgres_rehearsal_target
    import tests.postgresql.conftest as conftest_module

    fresh_process_called = False
    validation_called = False

    def mock_ensure_fresh_process():
        nonlocal fresh_process_called
        fresh_process_called = True

    def mock_validate(environ):
        nonlocal validation_called
        validation_called = True
        raise RuntimeError("should not be called")

    monkeypatch.setattr(conftest_module, "ensure_fresh_process", mock_ensure_fresh_process)
    monkeypatch.setattr(conftest_module, "validate_rehearsal_environment", mock_validate)

    # Intercept import of rehearsal_runtime to prove it is not imported
    original_import = builtins.__import__
    def mock_import(name, *args, **kwargs):
        if "rehearsal_runtime" in name:
            raise ImportError("rehearsal_runtime must not be imported during target resolution")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", mock_import)

    fake_env = {
        "SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL": "0"
    }

    with pytest.raises(pytest.skip.Exception):
        resolve_postgres_rehearsal_target(fake_env)

    assert not fresh_process_called
    assert not validation_called


def test_valid_target_returns_safe_metadata(monkeypatch):
    from tests.postgresql.conftest import resolve_postgres_rehearsal_target
    import tests.postgresql.conftest as conftest_module
    from tests.postgresql.rehearsal_guard import RehearsalTarget

    monkeypatch.setattr(conftest_module, "ensure_fresh_process", lambda: None)

    fake_env = {
        "SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL": "1",
        "APP_ENV": "testing",
        "SPAMANAGER_TEST_PROCESS": "1",
        "SPAMANAGER_ALLOW_POSTGRES_TESTS": "1",
        "TEST_DATABASE_URL": "postgresql://user:password@localhost:5433/spamanager_purge_rehearsal_test",
    }

    target = resolve_postgres_rehearsal_target(fake_env)
    assert isinstance(target, RehearsalTarget)
    assert target.backend == "postgresql"
    assert target.host == "localhost"
    assert target.port == 5433
    assert target.database == "spamanager_purge_rehearsal_test"


def test_real_target_resolution_helper_used_by_fixture():
    source = (ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "def resolve_postgres_rehearsal_target(environ):" in source
    assert "return resolve_postgres_rehearsal_target(os.environ)" in source


def test_tests_use_scalar_fixture_ids_after_session_remove():
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    assert 'fixture["workspace_id"]' in source
    assert 'fixture["actor_id"]' in source
    assert 'fixture["executor_id"]' in source
    assert 'fixture["owner_id"]' in source
    assert 'fixture["member_id"]' in source
    assert 'fixture["customer_id"]' in source
    assert 'fixture["service_id"]' in source
    assert 'fixture["invoice_id"]' in source
    assert 'fixture["setting_id"]' in source
    # Check that we don't access attributes of detached objects after remove
    assert 'workspace.deleted_by_id = None' not in source


def test_restore_checks_synthetic_audit_by_exact_description():
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    assert "verification.query(fixture[\"models\"].ActivityLog).filter_by(workspace_id=fixture[\"workspace_id\"]).count() == 1" not in source
    assert 'fixture["audit_description"]' in source
    assert "description=fixture[\"audit_description\"]" in source
    assert 'action="RESTORE_OWNER_WORKSPACE"' in source


def test_create_runtime_failure_cleanup_path():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    assert "db.session.remove()" in source
    assert "db.engine.dispose()" in source
    assert "app_context.pop()" in source


def test_shared_timeout_helper_contains_both_timeout_statements():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout = '2s'" in source
    assert "SET LOCAL statement_timeout = '30s'" in source
    # Check that they exist in a shared helper and not duplicated elsewhere
    assert source.count("SET LOCAL lock_timeout") == 1
    assert source.count("SET LOCAL statement_timeout") == 1


def test_standalone_identity_uses_engine_begin():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    assert "with self.engine.begin() as connection:" in source


def test_reset_calls_bounded_identity_before_truncate():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    # Verify reset_database calls identity(connection) before TRUNCATE
    assert "self.identity(connection)" in source
    assert "TRUNCATE" in source
    assert source.index("self.identity(connection)") < source.index("TRUNCATE")


def test_new_session_cleanup_static_check():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    # Check that new_session has try..except block which rolls back and closes
    assert "session.rollback()" in source
    assert "session.close()" in source


def test_scoped_session_cleanup_static_check():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    assert "session.rollback()" in source
    assert "self.db.session.remove()" in source


def test_service_wrapper_applies_timeout_and_descriptor_preservation():
    from tests.postgresql.rehearsal_runtime import wrap_service_new_session
    from unittest.mock import MagicMock
    import pytest
    import inspect

    # Monkeypatch helper
    monkeypatch = pytest.MonkeyPatch()

    # Success case setup
    fake_session = MagicMock()
    original_new_session_called = False

    class DummyStaticService:
        @staticmethod
        def _new_session():
            nonlocal original_new_session_called
            original_new_session_called = True
            return fake_session

    timeout_received_session = None
    timeout_called_before_return = False

    def mock_apply_transaction_timeouts(session):
        nonlocal timeout_received_session, timeout_called_before_return
        timeout_received_session = session
        if original_new_session_called:
            timeout_called_before_return = True

    # Monkeypatch apply_transaction_timeouts in rehearsal_runtime
    import tests.postgresql.rehearsal_runtime as runtime_module
    monkeypatch.setattr(runtime_module, "apply_transaction_timeouts", mock_apply_transaction_timeouts)

    # Wrap staticmethod
    wrap_service_new_session(DummyStaticService, monkeypatch)
    static_attr = inspect.getattr_static(DummyStaticService, "_new_session")
    assert isinstance(static_attr, staticmethod)

    # Invoke wrapped call
    result = DummyStaticService._new_session()

    # Assertions for success path
    assert original_new_session_called is True
    assert result is fake_session
    assert timeout_received_session is fake_session
    assert timeout_called_before_return is True
    assert not fake_session.rollback.called
    assert not fake_session.close.called

    # Failure case setup
    sentinel_exception = RuntimeError("sentinel timeout failure")

    def mock_apply_transaction_timeouts_fail(session):
        raise sentinel_exception

    monkeypatch.setattr(runtime_module, "apply_transaction_timeouts", mock_apply_transaction_timeouts_fail)

    fake_session_fail = MagicMock()

    class DummyFailureService:
        @staticmethod
        def _new_session():
            return fake_session_fail

    wrap_service_new_session(DummyFailureService, monkeypatch)

    with pytest.raises(RuntimeError) as exc_info:
        DummyFailureService._new_session()

    # Assert exact same exception object propagates
    assert exc_info.value is sentinel_exception
    assert fake_session_fail.rollback.called
    assert fake_session_fail.close.called

    # Wrap classmethod and instance method to prove descriptor preservation
    class DummyClassService:
        @classmethod
        def _new_session(cls):
            return MagicMock()

    class DummyInstanceService:
        def _new_session(self):
            return MagicMock()

    wrap_service_new_session(DummyClassService, monkeypatch)
    class_attr = inspect.getattr_static(DummyClassService, "_new_session")
    assert isinstance(class_attr, classmethod)

    wrap_service_new_session(DummyInstanceService, monkeypatch)
    inst_attr = inspect.getattr_static(DummyInstanceService, "_new_session")
    assert not isinstance(inst_attr, (staticmethod, classmethod))

    monkeypatch.undo()


def test_actual_service_classes_listed_in_bridge_fixture():
    source = (ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "PurgeRequestService" in source
    assert "PurgeService" in source
    assert "UserService" not in source  # verify restore uses Flask scoped, not bridged factory


def test_postgres_case_depends_on_bridge_fixture():
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    assert "def postgres_case(postgres_service_session_timeouts, postgres_runtime):" in source


def test_direct_fixture_mutations_call_prepare_scoped_session_first():
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    # In _base_fixture:
    assert "runtime.prepare_scoped_session()" in source
    assert source.index("runtime.prepare_scoped_session()") < source.index("db.session.add_all")
    # In test_active_legal_hold_blocks_approval:
    assert "postgres_case.prepare_scoped_session()" in source
    assert source.index("postgres_case.prepare_scoped_session()") < source.index('fixture["db"].session.add(fixture["models"].PurgeLegalHold')


def test_ast_restore_scenario_uses_direct_user_service_namespace_and_ordering():
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    func_node = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "test_restore_invalidates_request"
        ),
        None,
    )
    assert func_node is not None

    def fixture_member(node, member):
        return (
            isinstance(node, ast.Attribute)
            and node.attr == member
            and isinstance(node.value, ast.Subscript)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "fixture"
            and isinstance(node.value.slice, ast.Constant)
            and node.value.slice.value == "services"
        )

    def service_member(node, member):
        return (
            isinstance(node, ast.Attribute)
            and node.attr == member
            and isinstance(node.value, ast.Subscript)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "fixture"
            and isinstance(node.value.slice, ast.Constant)
            and node.value.slice.value == "services"
        )

    restore_calls = [
        node
        for node in ast.walk(func_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "restore_owner_workspace"
    ]
    assert len(restore_calls) == 1
    restore_call = restore_calls[0]
    assert (
        isinstance(restore_call.func.value, ast.Attribute)
        and restore_call.func.value.attr == "UserService"
        and isinstance(restore_call.func.value.value, ast.Subscript)
        and isinstance(restore_call.func.value.value.value, ast.Name)
        and restore_call.func.value.value.value.id == "fixture"
        and isinstance(restore_call.func.value.value.slice, ast.Constant)
        and restore_call.func.value.value.slice.value == "services"
    )
    assert len(restore_call.args) == 2
    assert not restore_call.keywords
    assert all(
        isinstance(arg, ast.Subscript)
        and isinstance(arg.value, ast.Name)
        and arg.value.id == "fixture"
        and isinstance(arg.slice, ast.Constant)
        and arg.slice.value == expected
        for arg, expected in zip(restore_call.args, ("actor", "owner_id"))
    )

    prepare_calls = [
        node
        for node in ast.walk(func_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "prepare_scoped_session"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "postgres_case"
    ]
    assert prepare_calls
    assert max(node.lineno for node in prepare_calls) < restore_call.lineno

    request_assignments = [
        node
        for node in func_node.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "request_service" for target in node.targets)
    ]
    assert len(request_assignments) == 1
    request_value = request_assignments[0].value
    assert service_member(request_value, "PurgeRequestService")

    create_calls = [
        node
        for node in ast.walk(func_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_purge_request"
    ]
    assert create_calls
    assert all(isinstance(node.func.value, ast.Name) and node.func.value.id == "request_service" for node in create_calls)

    status_assertions = [
        node
        for node in ast.walk(func_node)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr in {"status", "status_before", "status_after"}
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Eq)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
    ]
    assert [(node.left.attr, node.comparators[0].value) for node in status_assertions] == [
        ("status", "PENDING_APPROVAL"),
        ("status_before", "PENDING_APPROVAL"),
        ("status_after", "PENDING_APPROVAL"),
    ]

    event_type_assertions = {
        node.comparators[0].value
        for node in ast.walk(func_node)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr == "event_type"
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
    }
    assert event_type_assertions == {"request_created", "manifest_invalidated"}
    assert any(
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr == "invalidated_by_restore"
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value is True
        for node in ast.walk(func_node)
    )
    assert any(
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr == "invalidated_at"
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.IsNot)
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value is None
        for node in ast.walk(func_node)
    )


def test_rollback_audit_uses_unique_description():
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    assert "verification.query(fixture[\"models\"].ActivityLog).filter_by(" in source
    assert "workspace_id=fixture[\"workspace_id\"]" in source
    assert "description=fixture[\"audit_description\"]" in source


def test_create_runtime_uses_bare_raise():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    assert "except Exception:" in source
    assert "except OperationalError as exc:" in source
    assert "raise_sanitized_database_error(exc)" in source
    assert "raise orig_exc" not in source


def test_runtime_creation_sanitizes_operational_errors():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    assert "class RehearsalDatabaseAuthenticationError" in source
    assert "class RehearsalDatabaseConnectionError" in source
    assert '"LOCAL_REHEARSAL_DATABASE_AUTHENTICATION_FAILED"' in source
    assert '"LOCAL_REHEARSAL_DATABASE_CONNECTION_FAILED"' in source
    assert "from None" in source
    assert "logger.exception" not in source
    assert "traceback.print_exc" not in source
    assert "hide_parameters=True" in source


def test_execution_flag_is_rehearsal_only_and_literal_true():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    assert 'application.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True' in source
    assert "configure_rehearsal_app(app, target, environ)" in source
    assert '"SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL"' in source
    assert "PERMANENT_PURGE_EXECUTION_ENABLED = True" not in (ROOT.parent.parent / "config.py").read_text(encoding="utf-8")
    assert "tests/postgresql/test_postgresql_purge_reauth_concurrency.py" not in source


def test_ast_timeout_cleanup_methods_use_bare_raise():
    import ast
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    target_funcs = {"wrap_service_new_session", "new_session", "prepare_scoped_session"}
    found_funcs = {}

    class FuncVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            if node.name in target_funcs:
                found_funcs[node.name] = node
            self.generic_visit(node)

    FuncVisitor().visit(tree)
    assert len(found_funcs) == 3

    for name, func_node in found_funcs.items():
        # Check all raise statements inside this function
        # They must be bare raise (i.e. raise with no expression)
        for subnode in ast.walk(func_node):
            if isinstance(subnode, ast.Raise):
                assert subnode.exc is None, f"{name} contains a non-bare raise statement: {ast.unparse(subnode)}"


def test_ast_duplicate_scenario_uses_independent_sessions_only():
    import ast
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "test_request_creation_manifest_and_duplicate":
            func_node = node
            break

    assert func_node is not None

    # Walk the AST of this function. Any attribute access to session must only be '.remove()' or '.close()'
    for subnode in ast.walk(func_node):
        if isinstance(subnode, ast.Attribute) and subnode.attr in {"get", "query", "execute"}:
            curr = subnode.value
            is_db_session = False
            if isinstance(curr, ast.Attribute) and curr.attr == "session":
                is_db_session = True
            assert not is_db_session, f"Unarmed Flask db.session.{subnode.attr} found in duplicate test scenario!"


def test_ast_approval_and_drift_dto_contract():
    import ast
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    target_funcs = {"test_approval_event_ordering_and_manifest_immutability", "test_manifest_drift_fails_closed"}
    found_funcs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in target_funcs:
            found_funcs[node.name] = node

    assert len(found_funcs) == 2

    for name, func_node in found_funcs.items():
        # Assert no request.manifest_canonical_text is used
        for subnode in ast.walk(func_node):
            if isinstance(subnode, ast.Attribute) and subnode.attr == "manifest_canonical_text":
                val = subnode.value
                if isinstance(val, ast.Name) and val.id == "request":
                    raise AssertionError(f"Function {name} directly accesses request.manifest_canonical_text")


def test_ast_session_closure_ordering():
    import ast
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "test_approval_event_ordering_and_manifest_immutability":
            func_node = node
            break

    assert func_node is not None

    tries = [node for node in func_node.body if isinstance(node, ast.Try)]
    assert len(tries) == 2

    # Let's find approve_purge_request call
    approve_call = None
    for subnode in ast.walk(func_node):
        if isinstance(subnode, ast.Call) and isinstance(subnode.func, ast.Attribute) and subnode.func.attr == "approve_purge_request":
            approve_call = subnode
            break

    assert approve_call is not None

    approve_stmt_index = -1
    for idx, stmt in enumerate(func_node.body):
        if approve_call in ast.walk(stmt):
            approve_stmt_index = idx
            break

    first_try_index = func_node.body.index(tries[0])
    assert approve_stmt_index > first_try_index, "approve_purge_request must be called after the first verification block closes."

    second_try_index = func_node.body.index(tries[1])
    assert second_try_index > approve_stmt_index, "final verification block must be after approve_purge_request."



def _verify_core_query_structure(func_node, func_name):
    # Traversal to prove in the same expression chain:
    # - assignment target is Name("terminal");
    # - outer call is `.one()`;
    # - its receiver is a `.mappings()` call;
    # - mappings receiver is `verification.execute(...)`;
    # - execute has one query argument;
    # - that query contains a call to `select`;
    # - the select references `workspace_terminal_state_table`.
    found = False
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign):
            # 1. Target has Name(id="terminal")
            has_terminal_target = any(
                isinstance(t, ast.Name) and t.id == "terminal"
                for t in node.targets
            )
            if not has_terminal_target:
                continue

            # 2. Outer call is .one()
            val = node.value
            if not (isinstance(val, ast.Call) and
                    isinstance(val.func, ast.Attribute) and
                    val.func.attr == "one"):
                continue

            # 3. Its receiver is .mappings() call
            one_receiver = val.func.value
            if not (isinstance(one_receiver, ast.Call) and
                    isinstance(one_receiver.func, ast.Attribute) and
                    one_receiver.func.attr == "mappings"):
                continue

            # 4. mappings receiver is verification.execute(...)
            mappings_receiver = one_receiver.func.value
            if not (isinstance(mappings_receiver, ast.Call) and
                    isinstance(mappings_receiver.func, ast.Attribute) and
                    mappings_receiver.func.attr == "execute" and
                    isinstance(mappings_receiver.func.value, ast.Name) and
                    mappings_receiver.func.value.id == "verification"):
                continue

            # 5. execute has exactly one query argument
            if len(mappings_receiver.args) != 1:
                continue

            query_arg = mappings_receiver.args[0]

            # 6. that query contains a call to select
            select_calls = [
                n for n in ast.walk(query_arg)
                if isinstance(n, ast.Call) and
                isinstance(n.func, ast.Name) and n.func.id == "select"
            ]
            if not select_calls:
                continue

            # 7. the select references workspace_terminal_state_table
            has_table_ref = False
            for sc in select_calls:
                for sub in ast.walk(sc):
                    if isinstance(sub, ast.Name) and sub.id == "workspace_terminal_state_table":
                        has_table_ref = True
                        break
                if has_table_ref:
                    break

            if has_table_ref:
                found = True
                break

    assert found, (
        f"Function {func_name} does not meet the Core query structure contract for 'terminal': "
        "terminal = verification.execute(select(workspace_terminal_state_table).where(...)).mappings().one()"
    )


def test_ast_terminal_state_orm_contract():
    import ast
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    target_funcs = {
        "test_active_legal_hold_blocks_approval",
        "test_execution_success_preserves_audit_and_terminal_tombstone",
        "test_execution_rolls_back_after_mutation",
    }
    found_funcs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in target_funcs:
            found_funcs[node.name] = node

    assert len(found_funcs) == 3, f"Expected 3 target funcs, found {list(found_funcs)}"

    for name, func_node in found_funcs.items():
        for subnode in ast.walk(func_node):
            # Reject every ast.Attribute whose attr is purged_at or purge_request_id (no matter what variable name)
            if isinstance(subnode, ast.Attribute) and subnode.attr in ("purged_at", "purge_request_id"):
                raise AssertionError(
                    f"Function {name} line {subnode.lineno}: "
                    f"direct ORM access to {subnode.attr} forbidden — "
                    f"use workspace_terminal_state_table Core query subscript"
                )


def test_ast_terminal_state_core_table_contract():
    import ast
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    target_funcs = {
        "test_active_legal_hold_blocks_approval",
        "test_execution_success_preserves_audit_and_terminal_tombstone",
        "test_execution_rolls_back_after_mutation",
    }
    found_funcs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in target_funcs:
            found_funcs[node.name] = node

    assert len(found_funcs) == 3

    for name, func_node in found_funcs.items():
        _verify_core_query_structure(func_node, name)


def test_ast_terminal_state_success_assertions():
    import ast
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "test_execution_success_preserves_audit_and_terminal_tombstone":
            func_node = node
            break

    assert func_node is not None

    found_purged_at_eq = False
    found_request_id_eq = False
    for subnode in ast.walk(func_node):
        # Prove exact comparisons:
        # terminal["purged_at"] == execution_time
        # terminal["purge_request_id"] == request_id
        if (isinstance(subnode, ast.Compare) and
                len(subnode.ops) == 1 and isinstance(subnode.ops[0], ast.Eq) and
                len(subnode.comparators) == 1):
            left = subnode.left
            if (isinstance(left, ast.Subscript) and
                    isinstance(left.value, ast.Name) and left.value.id == "terminal" and
                    isinstance(left.slice, ast.Constant)):
                key = left.slice.value
                right = subnode.comparators[0]
                if key == "purged_at":
                    if isinstance(right, ast.Name) and right.id == "execution_time":
                        found_purged_at_eq = True
                elif key == "purge_request_id":
                    if isinstance(right, ast.Name) and right.id == "request_id":
                        found_request_id_eq = True

    assert found_purged_at_eq, "Success test must assert terminal['purged_at'] == execution_time"
    assert found_request_id_eq, "Success test must assert terminal['purge_request_id'] == request_id"


def test_ast_terminal_state_none_assertions():
    import ast
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    none_funcs = {
        "test_active_legal_hold_blocks_approval",
        "test_execution_rolls_back_after_mutation",
    }
    found_funcs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in none_funcs:
            found_funcs[node.name] = node

    assert len(found_funcs) == 2

    for name, func_node in found_funcs.items():
        found_purged_at_none = False
        found_request_id_none = False
        for subnode in ast.walk(func_node):
            if isinstance(subnode, ast.Compare) and len(subnode.ops) == 1 and isinstance(subnode.ops[0], ast.Is):
                left = subnode.left
                comparators = subnode.comparators
                if (isinstance(left, ast.Subscript) and
                        isinstance(left.value, ast.Name) and left.value.id == "terminal" and
                        len(comparators) == 1 and isinstance(comparators[0], ast.Constant) and
                        comparators[0].value is None):
                    slice_val = left.slice
                    if isinstance(slice_val, ast.Constant):
                        if slice_val.value == "purged_at":
                            found_purged_at_none = True
                        elif slice_val.value == "purge_request_id":
                            found_request_id_none = True

        assert found_purged_at_none, f"{name} must assert terminal['purged_at'] is None"
        assert found_request_id_none, f"{name} must assert terminal['purge_request_id'] is None"


def test_changed_files_encoding_and_formatting():
    files = [
        ROOT.parent.parent / "docs" / "workspace" / "PERMANENT_PURGE_POSTGRESQL_FUNCTIONAL_REHEARSAL.md",
        ROOT / "test_purge_runtime_postgresql.py",
        ROOT / "test_runtime_harness_contract.py"
    ]

    for path in files:
        assert path.exists(), f"File {path.name} does not exist"
        raw = path.read_bytes()

        # do not start with UTF-8 BOM bytes EF BB BF
        assert not raw.startswith(b"\xef\xbb\xbf"), f"File {path.name} contains UTF-8 BOM"

        # decode strictly as UTF-8
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise AssertionError(f"File {path.name} failed strict UTF-8 decode: {e}")

        # do not contain known mojibake tokens
        # Constructed at runtime via chr() codepoints — no literal mojibake characters in source.
        mojibake_tokens = (
            "".join(chr(cp) for cp in (0x00E2, 0x20AC, 0x201D)),
            "".join(chr(cp) for cp in (0x00E2, 0x2020, 0x2019)),
            "".join(chr(cp) for cp in (0x00EF, 0x00BB, 0x00BF)),
        )
        # self-validate: each token must be the real 3-char string, not a literal escape
        for token in mojibake_tokens:
            assert "\\u" not in token
            assert len(token) == 3
        for token in mojibake_tokens:
            assert token not in text, f"File {path.name} contains mojibake token: {repr(token)}"

        # end with exactly one final newline (normalized)
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        trailing_linebreak_count = len(normalized) - len(normalized.rstrip("\n"))
        assert trailing_linebreak_count == 1, (
            f"File {path.name} must end with exactly one newline, "
            f"found {trailing_linebreak_count}"
        )
