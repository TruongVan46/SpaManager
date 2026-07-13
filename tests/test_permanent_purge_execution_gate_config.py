import os
import unittest

os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SPAMANAGER_TEST_PROCESS", "1")

from config import (
    BaseConfig,
    _parse_bool_env,
    is_permanent_purge_execution_enabled,
    is_permanent_purge_ui_enabled,
)


class PermanentPurgeExecutionGateConfigTestCase(unittest.TestCase):
    def test_execution_flag_defaults_false(self):
        self.assertFalse(BaseConfig.PERMANENT_PURGE_EXECUTION_ENABLED)

    def test_execution_flag_parsing_is_fail_closed(self):
        for value in ("1", "true", "yes", "on", "y", "t", " TRUE ", " YeS "):
            with self.subTest(value=value):
                self.assertTrue(_parse_bool_env(value, False))
        for value in (None, "", "0", "false", "off", "no", "random"):
            with self.subTest(value=value):
                self.assertFalse(_parse_bool_env(value, False))
                self.assertFalse(is_permanent_purge_execution_enabled(value))

    def test_execution_helper_accepts_only_boolean_true(self):
        self.assertTrue(is_permanent_purge_execution_enabled(True))
        self.assertFalse(is_permanent_purge_execution_enabled(False))
        self.assertFalse(is_permanent_purge_execution_enabled("true"))
        self.assertFalse(is_permanent_purge_execution_enabled(1))

    def test_ui_and_execution_helpers_are_independent(self):
        self.assertTrue(is_permanent_purge_ui_enabled(True))
        self.assertFalse(is_permanent_purge_execution_enabled(False))


if __name__ == "__main__":
    unittest.main()
