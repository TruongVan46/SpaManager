import ast
from pathlib import Path


ROOT = Path(__file__).parent


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
    for name in ("conftest.py", "rehearsal_runtime.py", "test_purge_runtime_postgresql.py"):
        assert not (_module_imports(ROOT / name) & forbidden)


def test_reset_helper_has_explicit_allowlist_and_protects_revision():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
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


def test_runtime_contract_preserves_all_three_users_and_adds_counted_drift_row():
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    assert "assert verification.query(fixture[\"models\"].User).count() == 3" in source
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


def test_rollback_audit_uses_unique_description():
    source = (ROOT / "test_purge_runtime_postgresql.py").read_text(encoding="utf-8")
    assert "verification.query(fixture[\"models\"].ActivityLog).filter_by(" in source
    assert "workspace_id=fixture[\"workspace_id\"]" in source
    assert "description=fixture[\"audit_description\"]" in source


def test_create_runtime_uses_bare_raise():
    source = (ROOT / "rehearsal_runtime.py").read_text(encoding="utf-8")
    # Find the except block in create_runtime
    assert "except Exception:" in source
    assert "raise" in source
    assert "raise orig_exc" not in source


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
