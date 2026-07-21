"""
tests/test_app_env_fail_closed.py

Regression tests verifying that APP_ENV config selection fails closed:
  - Missing, empty, whitespace-only, or unsupported APP_ENV raises RuntimeError.
  - Valid values (development, testing, production) select the correct class.
  - Surrounding whitespace and uppercase characters are normalized.
  - Error messages do not contain DATABASE_URL, SECRET_KEY or password values.

All checks run in isolated subprocesses; no application state is imported into
this test process beyond project-root path resolution.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Safe disposable production-like values (never real credentials)
_SAFE_DATABASE_URL = "postgresql://audit_user:audit_pass@127.0.0.1:1/audit_db"
_SAFE_SECRET_KEY = "safe-audit-secret-key-for-testing-only"
_SAFE_OWNER_PASSWORD = "safe-audit-owner-password"

# Probe code: prints "OK:<ClassName>" on success or raises on failure.
_PROBE = (
    "import config; "
    "cfg = config.get_active_config(); "
    "print('OK:' + type(cfg).__name__)"
)

_TESTING_SQLITE = (
    Path(tempfile.gettempdir()) / "spamanager_app_env_test_probe.sqlite"
).as_posix()
_TESTING_ENV_VARS = {"TEST_DATABASE_URL": "sqlite:///" + _TESTING_SQLITE}


def _run(env_overrides: dict, *, extra_vars=None):
    env = os.environ.copy()
    for key in (
        "APP_ENV", "DATABASE_URL", "SECRET_KEY", "DEFAULT_OWNER_PASSWORD",
        "SPAMANAGER_TEST_PROCESS", "PYTEST_CURRENT_TEST",
        "TEST_DATABASE_URL", "SPAMANAGER_ALLOW_POSTGRES_TESTS",
    ):
        env.pop(key, None)
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    if extra_vars:
        env.update(extra_vars)
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


_PRODUCTION_ENV = {
    "APP_ENV": "production",
    "DATABASE_URL": _SAFE_DATABASE_URL,
    "SECRET_KEY": _SAFE_SECRET_KEY,
    "DEFAULT_OWNER_PASSWORD": _SAFE_OWNER_PASSWORD,
}


class TestAppEnvMissingFails(unittest.TestCase):
    def test_missing_app_env_raises(self):
        result = _run({"APP_ENV": None})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("APP_ENV", result.stderr)

    def test_missing_app_env_error_message_lists_accepted_values(self):
        result = _run({"APP_ENV": None})
        self.assertIn("development", result.stderr)
        self.assertIn("testing", result.stderr)
        self.assertIn("production", result.stderr)

    def test_missing_app_env_error_message_has_no_secret(self):
        result = _run({"APP_ENV": None})
        self.assertNotIn(_SAFE_DATABASE_URL, result.stderr)
        self.assertNotIn(_SAFE_SECRET_KEY, result.stderr)
        self.assertNotIn(_SAFE_OWNER_PASSWORD, result.stderr)


class TestAppEnvEmptyFails(unittest.TestCase):
    def test_empty_string_raises(self):
        result = _run({"APP_ENV": ""})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("APP_ENV", result.stderr)

    def test_whitespace_only_raises(self):
        result = _run({"APP_ENV": "   "})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("APP_ENV", result.stderr)

    def test_tab_whitespace_raises(self):
        result = _run({"APP_ENV": "\t"})
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_empty_error_mentions_accepted_values(self):
        result = _run({"APP_ENV": ""})
        self.assertIn("development", result.stderr)
        self.assertIn("testing", result.stderr)
        self.assertIn("production", result.stderr)


class TestAppEnvUnknownFails(unittest.TestCase):
    def _assert_fails_closed(self, app_env_value):
        result = _run({"APP_ENV": app_env_value})
        self.assertNotEqual(
            result.returncode, 0,
            f"Expected failure for APP_ENV={app_env_value!r} but process succeeded: {result.stdout}"
        )
        self.assertIn("APP_ENV", result.stderr)

    def test_prodution_misspelled_raises(self):
        self._assert_fails_closed("prodution")

    def test_staging_raises(self):
        self._assert_fails_closed("staging")

    def test_prod_abbreviation_raises(self):
        self._assert_fails_closed("prod")

    def test_dev_abbreviation_raises(self):
        self._assert_fails_closed("dev")

    def test_test_abbreviation_raises(self):
        self._assert_fails_closed("test")

    def test_unexpected_value_raises(self):
        self._assert_fails_closed("unexpected_value")

    def test_unknown_error_mentions_accepted_values(self):
        result = _run({"APP_ENV": "staging"})
        self.assertIn("development", result.stderr)
        self.assertIn("testing", result.stderr)
        self.assertIn("production", result.stderr)

    def test_unknown_error_includes_bad_value(self):
        result = _run({"APP_ENV": "staging"})
        self.assertIn("staging", result.stderr)

    def test_unknown_error_has_no_secret(self):
        result = _run({"APP_ENV": "staging"})
        self.assertNotIn(_SAFE_SECRET_KEY, result.stderr)
        self.assertNotIn(_SAFE_DATABASE_URL, result.stderr)
        self.assertNotIn(_SAFE_OWNER_PASSWORD, result.stderr)


class TestAppEnvValidValues(unittest.TestCase):
    def test_development_selects_development_config(self):
        result = _run({"APP_ENV": "development"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DevelopmentConfig", result.stdout)

    def test_testing_selects_testing_config(self):
        result = _run({"APP_ENV": "testing"}, extra_vars=_TESTING_ENV_VARS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TestingConfig", result.stdout)

    def test_production_selects_production_config(self):
        result = _run(_PRODUCTION_ENV)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ProductionConfig", result.stdout)


class TestAppEnvNormalization(unittest.TestCase):
    def test_production_with_surrounding_spaces(self):
        result = _run({**_PRODUCTION_ENV, "APP_ENV": " production "})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ProductionConfig", result.stdout)

    def test_production_uppercase(self):
        result = _run({**_PRODUCTION_ENV, "APP_ENV": "PRODUCTION"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ProductionConfig", result.stdout)

    def test_development_mixed_case(self):
        result = _run({"APP_ENV": "Development"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DevelopmentConfig", result.stdout)

    def test_testing_uppercase(self):
        result = _run({"APP_ENV": "TESTING"}, extra_vars=_TESTING_ENV_VARS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TestingConfig", result.stdout)


class TestProductionConfigStillFailsClosed(unittest.TestCase):
    def test_production_missing_database_url_raises(self):
        env = {"APP_ENV": "production", "SECRET_KEY": _SAFE_SECRET_KEY, "DEFAULT_OWNER_PASSWORD": _SAFE_OWNER_PASSWORD}
        result = _run(env)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("DATABASE_URL", result.stderr)

    def test_production_missing_secret_key_raises(self):
        env = {"APP_ENV": "production", "DATABASE_URL": _SAFE_DATABASE_URL, "DEFAULT_OWNER_PASSWORD": _SAFE_OWNER_PASSWORD}
        result = _run(env)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("SECRET_KEY", result.stderr)

    def test_production_error_does_not_expose_credentials(self):
        env = {"APP_ENV": "production", "SECRET_KEY": _SAFE_SECRET_KEY, "DEFAULT_OWNER_PASSWORD": _SAFE_OWNER_PASSWORD}
        result = _run(env)
        self.assertNotIn(_SAFE_SECRET_KEY, result.stderr)
        self.assertNotIn("audit_pass", result.stderr)


if __name__ == "__main__":
    unittest.main()
