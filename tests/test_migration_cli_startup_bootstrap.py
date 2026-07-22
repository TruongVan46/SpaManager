import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, ".")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SPAMANAGER_BOOTSTRAP_ACCOUNTS_ENABLED", "0")
from app import (  # noqa: E402
    _initialize_startup_database_bootstrap,
    _is_flask_database_migration_cli,
)
import app as app_module  # noqa: E402


class MigrationCliStartupBootstrapTests(unittest.TestCase):
    def test_detection_accepts_flask_database_commands(self):
        commands = (
            ["python", "-m", "flask", "--app", "app", "db", "upgrade"],
            ["flask", "--app", "app", "db", "downgrade"],
            ["flask", "--app", "app", "db", "current"],
            ["flask", "--app", "app", "db", "history"],
            ["/venv/lib/python3.12/site-packages/flask/__main__.py", "--app", "app", "db", "upgrade"],
            ["flask", "--app", "app", "db", "heads"],
            ["flask", "--app", "app", "db", "stamp", "0010_account_purge_foundation"],
        )
        for argv in commands:
            with self.subTest(argv=argv):
                self.assertTrue(_is_flask_database_migration_cli(argv))

    def test_detection_rejects_normal_runtime_and_unrelated_commands(self):
        commands = (
            ["flask", "--app", "app", "run"],
            ["gunicorn", "app:app"],
            ["pytest", "tests", "db", "upgrade"],
            ["python", "-m", "flask", "--app", "app", "shell"],
        )
        for argv in commands:
            with self.subTest(argv=argv):
                self.assertFalse(_is_flask_database_migration_cli(argv))

    def test_migration_cli_skips_entire_startup_database_bootstrap(self):
        argv = ["python", "-m", "flask", "--app", "app", "db", "upgrade"]
        with patch.object(app_module, "_run_startup_database_bootstrap") as bootstrap, patch.object(
            app_module, "_baseline_schema_is_ready"
        ) as readiness:
            self.assertFalse(_initialize_startup_database_bootstrap(argv))
        bootstrap.assert_not_called()
        readiness.assert_not_called()

    def test_normal_runtime_preserves_startup_bootstrap(self):
        with patch.object(app_module, "_run_startup_database_bootstrap") as bootstrap:
            self.assertTrue(_initialize_startup_database_bootstrap(["gunicorn", "app:app"]))
        bootstrap.assert_called_once_with()

    def test_normal_runtime_bootstrap_errors_are_not_swallowed(self):
        error = RuntimeError("schema mismatch")
        with patch.object(app_module, "_run_startup_database_bootstrap", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "schema mismatch"):
                _initialize_startup_database_bootstrap(["gunicorn", "app:app"])


if __name__ == "__main__":
    unittest.main()
