import ast
import importlib.util
import inspect
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "migrations" / "versions" / "0010_account_purge_foundation.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0010", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = _load_migration()


class AccountPurgeFoundationSchemaTests(unittest.TestCase):
    def test_revision_metadata_and_entrypoints(self):
        self.assertEqual(MIGRATION.revision, "0010_account_purge_foundation")
        self.assertEqual(MIGRATION.down_revision, "0009_immediate_purge_eligibility")
        self.assertEqual(inspect.signature(MIGRATION.upgrade), inspect.Signature())
        self.assertEqual(inspect.signature(MIGRATION.downgrade), inspect.Signature())

    def test_migration_is_schema_only_and_does_not_import_application_behavior(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = "\n".join(
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        )
        self.assertNotIn("services.", imports)
        self.assertNotIn("routes.", imports)
        self.assertNotIn("from app", imports)
        self.assertNotIn("unlink(", source.lower())
        self.assertNotIn("os.remove", source.lower())
        self.assertIn("account_purge_requests", source)
        self.assertIn("account_identity_reservations", source)
        self.assertIn("account_purge_avatar_cleanups", source)

    def test_required_tables_and_user_columns_are_explicit(self):
        expected_tables = {
            "user_creation_provenance",
            "account_purge_requests",
            "account_purge_lifecycle_events",
            "account_purge_legal_holds",
            "account_purge_execution_authorizations",
            "account_identity_reservations",
            "account_purge_avatar_cleanups",
        }
        self.assertEqual(set(MIGRATION.NEW_TABLES), expected_tables)
        self.assertEqual(
            MIGRATION.USER_COLUMNS,
            {
                "account_purge_state",
                "account_purged_at",
                "account_purge_request_id",
                "session_revocation_version",
                "session_revoked_at",
                "account_purge_version",
            },
        )

    def test_fail_closed_and_privacy_contracts_are_present(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        for expected in (
            "LEGACY_UNKNOWN",
            "ON DELETE RESTRICT",
            "session_revocation_version >= 0",
            "account_purge_version >= 0",
            "requester_id IS NULL OR requester_id <> target_user_id",
            "requester_id <> approver_id",
            "released_at IS NOT NULL",
            "identity_fingerprint",
            "released_at IS NULL",
            "attempt_count >= 0",
            "state <> 'COMPLETED' OR completed_at IS NOT NULL",
        ):
            self.assertIn(expected, source)

    def test_downgrade_is_guarded_and_drops_only_new_objects(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn("_assert_empty(connection)", source)
        self.assertIn("DROP CONSTRAINT fk_users_account_purge_request", source)
        self.assertIn("for table_name in reversed(NEW_TABLES)", source)
        self.assertIn("DROP TABLE {table_name}", source)
        self.assertIn("account_purge_state <> 'NOT_PURGED'", source)


if __name__ == "__main__":
    unittest.main()
