import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestDatabaseIsolationGuardTestCase(unittest.TestCase):
    def _run_config_import(self, updates):
        environment = os.environ.copy()
        environment.update({"SPAMANAGER_TEST_PROCESS": "1", "DATABASE_URL": "postgresql://hidden:hidden@127.0.0.1:1/spamanager_dev"})
        for key, value in updates.items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        return subprocess.run(
            [sys.executable, "-c", "import config; print(config.Config.SQLALCHEMY_DATABASE_URI)"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_missing_test_database_url_fails_before_connection(self):
        result = self._run_config_import({"APP_ENV": None, "TEST_DATABASE_URL": None})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Test database safety guard", result.stderr)
        self.assertNotIn("hidden", result.stderr)

    def test_postgresql_test_database_requires_opt_in_and_test_name(self):
        result = self._run_config_import({"TEST_DATABASE_URL": "postgresql://hidden:hidden@127.0.0.1:1/spamanager_dev"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Test database safety guard", result.stderr)
        self.assertNotIn("hidden", result.stderr)

    def test_postgresql_opt_in_rejects_test_text_outside_database_name(self):
        for url in (
            "postgresql://user_test:hidden@127.0.0.1/spamanager_dev",
            "postgresql://user:hidden@127.0.0.1/spamanager_dev?application_name=_test",
            "postgresql+psycopg2://user:hidden@127.0.0.1/spamanager_dev",
        ):
            with self.subTest(url=url):
                result = self._run_config_import({"TEST_DATABASE_URL": url, "SPAMANAGER_ALLOW_POSTGRES_TESTS": "1"})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("hidden", result.stderr)

    def test_postgresql_opt_in_allows_database_name_ending_test(self):
        result = self._run_config_import({"TEST_DATABASE_URL": "postgresql+psycopg2://user:hidden@127.0.0.1/spamanager_unit_test", "SPAMANAGER_ALLOW_POSTGRES_TESTS": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsupported_scheme_and_normal_development_process(self):
        blocked = self._run_config_import({"TEST_DATABASE_URL": "mysql://user:hidden@127.0.0.1/spamanager_test"})
        self.assertNotEqual(blocked.returncode, 0)
        environment = os.environ.copy()
        environment.pop("SPAMANAGER_TEST_PROCESS", None)
        environment["APP_ENV"] = "development"
        result = subprocess.run([sys.executable, "-c", "import config; print(type(config.Config).__name__)"], cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DevelopmentConfig", result.stdout)

    def test_sqlite_test_database_ignores_development_database_url(self):
        test_path = Path(tempfile.gettempdir()) / "spamanager_isolation_guard_test.sqlite"
        result = self._run_config_import({"TEST_DATABASE_URL": f"sqlite:///{test_path.as_posix()}"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sqlite:///", result.stdout)
        self.assertNotIn("postgresql", result.stdout)
