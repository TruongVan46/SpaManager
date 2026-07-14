import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.postgresql import rehearsal_runtime


ROOT = Path(__file__).parents[2]


def _target():
    return SimpleNamespace(
        backend="postgresql",
        host="127.0.0.1",
        port=5433,
        database="spamanager_purge_rehearsal_test",
    )


def _enabled_environment():
    return {
        "APP_ENV": "testing",
        "SPAMANAGER_TEST_PROCESS": "1",
        "SPAMANAGER_ALLOW_POSTGRES_TESTS": "1",
        "SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL": "1",
        "TEST_DATABASE_URL": "present",
    }


def test_rehearsal_boundary_sets_literal_boolean_true():
    application = SimpleNamespace(config={"PERMANENT_PURGE_EXECUTION_ENABLED": False})

    rehearsal_runtime.configure_rehearsal_app(
        application,
        _target(),
        _enabled_environment(),
    )

    assert application.config["PERMANENT_PURGE_EXECUTION_ENABLED"] is True
    assert type(application.config["PERMANENT_PURGE_EXECUTION_ENABLED"]) is bool


def test_rehearsal_boundary_requires_all_gates_and_fails_closed():
    application = SimpleNamespace(config={"PERMANENT_PURGE_EXECUTION_ENABLED": False})
    environment = _enabled_environment()
    environment["SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL"] = "0"

    with pytest.raises(rehearsal_runtime.RehearsalIdentityError):
        rehearsal_runtime.configure_rehearsal_app(application, _target(), environment)

    assert application.config["PERMANENT_PURGE_EXECUTION_ENABLED"] is False


def test_application_default_execution_flag_remains_disabled():
    source = (ROOT / "config.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "PERMANENT_PURGE_EXECUTION_ENABLED"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    value = assignments[0].value
    assert isinstance(value, ast.Call)
    assert isinstance(value.func, ast.Name)
    assert value.func.id == "_parse_bool_env"
    assert isinstance(value.args[-1], ast.Constant)
    assert value.args[-1].value is False


def test_runtime_contract_couples_flag_to_rehearsal_boundary():
    source = (ROOT / "tests" / "postgresql" / "rehearsal_runtime.py").read_text(encoding="utf-8")
    assert 'application.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True' in source
    assert "configure_rehearsal_app(app, target, environ)" in source
    assert '"SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL"' in source
    assert '"TEST_DATABASE_URL"' in source
