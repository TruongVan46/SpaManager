import ast
import hashlib
import importlib.util
import json
import inspect
import ast
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "migrations" / "versions" / "0009_immediate_purge_eligibility.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0009", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = _load_migration()


class ImmediatePurgeEligibilityMigrationTests(unittest.TestCase):
    def test_revision_metadata(self):
        self.assertEqual(MIGRATION.revision, "0009_immediate_purge_eligibility")
        self.assertEqual(MIGRATION.down_revision, "0008_durable_purge_reauth_state")
        self.assertEqual(inspect.signature(MIGRATION.upgrade), inspect.Signature())
        self.assertEqual(inspect.signature(MIGRATION.downgrade), inspect.Signature())

    def test_custom_runtime_import_contract(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        joined = "\n".join(ast.unparse(node) for node in imports)
        self.assertNotIn("alembic", joined.lower())
        self.assertNotIn("flask_migrate", joined.lower())
        self.assertNotIn("Flask-Migrate", joined)
        self.assertIn("from extensions import db", source)
        self.assertIn("with db.engine.begin() as connection", source)
        self.assertNotIn("op.get_bind", source)

    def test_no_application_imports(self):
        tree = ast.parse(MIGRATION_PATH.read_text(encoding="utf-8"))
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        joined = "\n".join(ast.unparse(node) for node in imports)
        self.assertNotIn("services.", joined)
        self.assertNotIn("models.", joined)
        self.assertNotIn("from app", joined)

    def test_canonical_contract_and_hash(self):
        payload = {"a": "á", "retention": {"eligible_at": "2026-01-01T00:00:00.000000Z", "policy_version": "x"}}
        text = MIGRATION._canonical_json(payload)
        self.assertEqual(text, json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=False))
        self.assertEqual(MIGRATION._sha256(text), hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(MIGRATION._utc_text(datetime(2026, 1, 1, 2, 3, 4, 5)), "2026-01-01T02:03:04.000005Z")

    def test_immediate_transform_preserves_unrelated_manifest_data(self):
        payload = {
            "manifest_version": "purge-manifest-v1",
            "lifecycle_id": "life",
            "workspace_id": 7,
            "target_deleted_at": "2026-01-01T00:00:00.000000Z",
            "target_deleted_by_id": 2,
            "retention": {"eligible_at": "2026-01-31T00:00:00.000000Z", "policy_version": MIGRATION.OLD_POLICY},
            "destructive": [{"table": "customers", "action": "DELETE"}],
        }
        text, digest = MIGRATION._transform_manifest(payload, datetime(2026, 1, 1), MIGRATION.NEW_POLICY)
        transformed = json.loads(text)
        self.assertEqual(transformed["retention"], {"eligible_at": "2026-01-01T00:00:00.000000Z", "policy_version": MIGRATION.NEW_POLICY})
        self.assertEqual(transformed["destructive"], payload["destructive"])
        self.assertEqual(digest, MIGRATION._sha256(text))

    def test_downgrade_reconstructs_legacy_retention(self):
        payload = {"manifest_version": "purge-manifest-v1", "retention": {"eligible_at": "2026-01-01T00:00:00.000000Z", "policy_version": MIGRATION.NEW_POLICY}}
        text, _ = MIGRATION._transform_manifest(payload, datetime(2026, 1, 1), MIGRATION.OLD_POLICY)
        self.assertEqual(json.loads(text)["retention"]["policy_version"], MIGRATION.OLD_POLICY)

    def test_event_payload_allow_list_and_no_pii(self):
        details = MIGRATION._migration_details(MIGRATION.OLD_POLICY, MIGRATION.NEW_POLICY, datetime(2026, 1, 1), datetime(2026, 1, 1), "a" * 64, "b" * 64)
        payload = json.loads(details)
        self.assertEqual(set(payload), {"revision", "old_policy_version", "new_policy_version", "old_eligible_at", "new_eligible_at", "old_manifest_hash", "new_manifest_hash"})
        self.assertRegex(payload["old_manifest_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(payload["new_manifest_hash"], r"^[0-9a-f]{64}$")
        forbidden_keys = {"manifest", "manifest_text", "manifest_canonical_text", "username", "email", "password", "token", "secret", "oauth_id", "url"}
        self.assertFalse(forbidden_keys.intersection(payload))
        self.assertNotIn('"manifest":', details.lower())
        self.assertNotIn('"manifest_text":', details.lower())
        self.assertNotIn('"manifest_canonical_text":', details.lower())
        self.assertNotIn("password", details.lower())
        self.assertNotIn("username", details.lower())

    def test_constraint_parser_exact_sets(self):
        def expression(values):
            return "CHECK (event_type IN (" + MIGRATION._quoted_values(values) + "))"

        self.assertEqual(MIGRATION._event_type_literals(expression(MIGRATION.OLD_EVENT_TYPES)), MIGRATION.OLD_EVENT_TYPES)
        self.assertEqual(MIGRATION._event_type_literals(expression(MIGRATION.EVENT_TYPES)), MIGRATION.EVENT_TYPES)
        self.assertEqual(
            MIGRATION._event_type_literals(expression(("request_created", "unexpected_event"))),
            ("request_created", "unexpected_event"),
        )

        class ConstraintResult:
            def __init__(self, definition):
                self.definition = definition

            def fetchall(self):
                return [("c", self.definition)]

        class ConstraintConnection:
            dialect = type("Dialect", (), {"name": "postgresql"})()

            def __init__(self, definition):
                self.definition = definition

            def execute(self, *_args, **_kwargs):
                return ConstraintResult(self.definition)

        self.assertRaises(
            RuntimeError,
            MIGRATION._assert_postgres_event_constraint,
            ConstraintConnection(expression(MIGRATION.OLD_EVENT_TYPES[:-1] + ("unexpected_event",))),
            MIGRATION.OLD_EVENT_TYPES,
            "test",
        )
        with self.assertRaises(ValueError):
            MIGRATION._event_type_literals("CHECK (event_type IN ('request_created')) OR 1=1")
        with self.assertRaises(ValueError):
            MIGRATION._event_type_literals("CHECK (event_type IN ('request_created))")
        with self.assertRaises(ValueError):
            MIGRATION._event_type_literals("CHECK (event_type = ANY (ARRAY['request_created', 42]::text[]))")
        with self.assertRaises(ValueError):
            MIGRATION._event_type_literals("CHECK (status IN ('ACTIVE'))")

        duplicate = MIGRATION.EVENT_TYPES + (MIGRATION.MIGRATION_EVENT,)
        self.assertRaises(
            RuntimeError,
            MIGRATION._assert_postgres_event_constraint,
            ConstraintConnection(expression(duplicate)),
            MIGRATION.EVENT_TYPES,
            "test",
        )

    def test_constraint_parser_postgresql_character_varying_regression_matrix(self):
        def actual_expression(values, cast="character varying", mixed=False):
            rendered = []
            for index, value in enumerate(values):
                literal = MIGRATION._quoted_values((value,))
                if mixed and index % 2:
                    literal += "::text"
                else:
                    literal += f"::{cast}"
                rendered.append(f"({literal})")
            return (
                "CHECK (((event_type)::text = ANY "
                "(ARRAY["
                + ", ".join(rendered)
                + "]::text[])))"
            )

        old_actual = actual_expression(MIGRATION.OLD_EVENT_TYPES)
        new_actual = actual_expression(MIGRATION.EVENT_TYPES)

        self.assertEqual(MIGRATION._event_type_literals(old_actual), MIGRATION.OLD_EVENT_TYPES)
        self.assertEqual(len(MIGRATION._event_type_literals(old_actual)), 23)
        self.assertNotIn(MIGRATION.MIGRATION_EVENT, MIGRATION._event_type_literals(old_actual))
        self.assertEqual(MIGRATION._event_type_literals(new_actual), MIGRATION.EVENT_TYPES)
        self.assertEqual(len(MIGRATION._event_type_literals(new_actual)), 24)
        self.assertEqual(MIGRATION._event_type_literals(new_actual).count(MIGRATION.MIGRATION_EVENT), 1)
        self.assertEqual(MIGRATION._event_type_literals(actual_expression(MIGRATION.OLD_EVENT_TYPES, mixed=True)), MIGRATION.OLD_EVENT_TYPES)
        self.assertEqual(MIGRATION._event_type_literals("CHECK (event_type IN (" + MIGRATION._quoted_values(MIGRATION.OLD_EVENT_TYPES) + "))"), MIGRATION.OLD_EVENT_TYPES)
        unknown = actual_expression(MIGRATION.OLD_EVENT_TYPES[:-1] + ("unexpected_event",))
        self.assertRaises(RuntimeError, MIGRATION._assert_postgres_event_constraint, type("C", (), {"dialect": type("D", (), {"name": "postgresql"})(), "execute": lambda self, *a, **k: type("R", (), {"fetchall": lambda self: [("c", unknown)]})()})(), MIGRATION.OLD_EVENT_TYPES, "test")
        self.assertRaises(RuntimeError, MIGRATION._assert_postgres_event_constraint, type("C", (), {"dialect": type("D", (), {"name": "postgresql"})(), "execute": lambda self, *a, **k: type("R", (), {"fetchall": lambda self: [("c", actual_expression(MIGRATION.OLD_EVENT_TYPES[:-1]))]})()})(), MIGRATION.OLD_EVENT_TYPES, "test")
        duplicate = MIGRATION.OLD_EVENT_TYPES + (MIGRATION.OLD_EVENT_TYPES[0],)
        self.assertRaises(RuntimeError, MIGRATION._assert_postgres_event_constraint, type("C", (), {"dialect": type("D", (), {"name": "postgresql"})(), "execute": lambda self, *a, **k: type("R", (), {"fetchall": lambda self: [("c", actual_expression(duplicate))]})()})(), MIGRATION.OLD_EVENT_TYPES, "test")
        self.assertRaises(ValueError, MIGRATION._event_type_literals, actual_expression(MIGRATION.OLD_EVENT_TYPES).replace("::character varying", "::integer", 1))
        self.assertRaises(ValueError, MIGRATION._event_type_literals, actual_expression(MIGRATION.OLD_EVENT_TYPES).replace("::character varying", "::custom.event_type", 1))
        self.assertRaises(ValueError, MIGRATION._event_type_literals, actual_expression(MIGRATION.OLD_EVENT_TYPES).replace("::character varying", "::character varying(", 1))
        self.assertRaises(ValueError, MIGRATION._event_type_literals, "CHECK (event_type = ANY (ARRAY['request_created]::character varying]::text[]))")
        cast_like = "CHECK (event_type IN (" + MIGRATION._quoted_values(("literal ::integer text",)) + "))"
        self.assertEqual(MIGRATION._event_type_literals(cast_like), ("literal ::integer text",))
        self.assertRaises(RuntimeError, MIGRATION._assert_postgres_event_constraint, type("C", (), {"dialect": type("D", (), {"name": "postgresql"})(), "execute": lambda self, *a, **k: type("R", (), {"fetchall": lambda self: [("c", actual_expression(MIGRATION.OLD_EVENT_TYPES + (MIGRATION.MIGRATION_EVENT,)))]})()})(), MIGRATION.OLD_EVENT_TYPES, "test")

    def test_constraint_sets_are_immutable_and_expanded_once(self):
        self.assertEqual(len(MIGRATION.OLD_EVENT_TYPES), 23)
        self.assertEqual(len(MIGRATION.EVENT_TYPES), 24)
        self.assertEqual(set(MIGRATION.EVENT_TYPES), set(MIGRATION.OLD_EVENT_TYPES) | {MIGRATION.MIGRATION_EVENT})
        self.assertEqual(MIGRATION.EVENT_TYPES.count(MIGRATION.MIGRATION_EVENT), 1)

    def test_constraint_preflight_is_before_drop_and_postflight_is_present(self):
        def calls(function):
            tree = ast.parse(inspect.getsource(function))
            return [
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            ]

        upgrade_calls = calls(MIGRATION.upgrade)
        downgrade_calls = calls(MIGRATION.downgrade)
        self.assertLess(upgrade_calls.index("_assert_postgres_event_constraint"), upgrade_calls.index("_replace_event_constraint"))
        self.assertGreater(upgrade_calls.index("_assert_postgres_event_constraint", upgrade_calls.index("_replace_event_constraint")), upgrade_calls.index("_replace_event_constraint"))
        self.assertLess(downgrade_calls.index("_assert_postgres_event_constraint"), downgrade_calls.index("_replace_event_constraint"))
        self.assertGreater(downgrade_calls.index("_assert_postgres_event_constraint", downgrade_calls.index("_replace_event_constraint")), downgrade_calls.index("_replace_event_constraint"))

    def test_event_type_constraint_preserves_old_values(self):
        self.assertEqual(set(MIGRATION.EVENT_TYPES), set(MIGRATION.OLD_EVENT_TYPES) | {MIGRATION.MIGRATION_EVENT})
        self.assertEqual(len(set(MIGRATION.EVENT_TYPES) - set(MIGRATION.OLD_EVENT_TYPES)), 1)

    def test_sql_scope_has_no_status_or_terminal_update(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn("WHERE r.status = 'PENDING_RETENTION'", source)
        self.assertIn("status = 'PENDING_RETENTION'", source)
        self.assertNotIn("SET status =", source)
        self.assertIn("purged_at IS NULL AND purge_request_id IS NULL", source)

    def test_downgrade_deletes_only_exact_event(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn("DELETE FROM purge_lifecycle_events WHERE id = :event_id", source)
        self.assertIn("AND event_type = :event_type", source)
        self.assertNotIn("DELETE FROM purge_lifecycle_events WHERE request_id = :request_id", source)

    def test_cross_lifecycle_historical_evidence_and_workspace_states(self):
        base = {
            "status": "PENDING_RETENTION",
            "retention_policy_version": MIGRATION.OLD_POLICY,
            "invalidated_at": datetime(2026, 1, 1),
            "invalidated_by_restore": True,
            "outcome_unknown": False,
        }
        exact = {
            "restore_event_count": 1,
            "restore_exact_count": 1,
            "later_event_count": 0,
            "migration_event_count": 0,
        }
        cases = {
            "R01": MIGRATION._is_currently_restored({"deleted_at": None, "deleted_by_id": None, "purged_at": None, "purge_request_id": None}),
            "R16": not MIGRATION._is_exact_historical_restore_invalidated(base, dict(exact, restore_exact_count=0)),
            "R17": not MIGRATION._is_exact_historical_restore_invalidated(base, dict(exact, restore_event_count=2)),
            "R18": not MIGRATION._is_exact_historical_restore_invalidated(base, dict(exact, later_event_count=1)),
            "R19": not MIGRATION._is_exact_historical_restore_invalidated(base, dict(exact, migration_event_count=1)),
            "R20": not MIGRATION._is_exact_historical_restore_invalidated(dict(base, outcome_unknown=True), exact),
        }
        for label, result in cases.items():
            with self.subTest(label=label):
                self.assertTrue(result)

    def test_cross_lifecycle_source_contract_r02_to_r25(self):
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        requirements = {
            "R02": "def _classify_candidates(connection, rows):",
            "R03": "def _verify_historical_unchanged",
            "R04": "_verify_upgrade(connection, selected_ids)",
            "R05": "def _restore_request",
            "R06": "historical_snapshots",
            "R07": "successor is missing or ambiguous",
            "R08": "successor is unsafe",
            "R09": "if len(matching) != 1:",
            "R10": "or successor[\"lifecycle_id\"] == historical[\"lifecycle_id\"]",
            "R11": "successor[\"target_deleted_at\"] != historical[\"deleted_at\"]",
            "R12": "created[\"event_count\"] == 1",
            "R13": "created[\"event_count\"] == 1",
            "R14": "created[\"event_at\"] > historical[\"invalidated_at\"]",
            "R15": "historical[\"deleted_at\"] <= historical[\"invalidated_at\"]",
            "R21": "successor[\"workspace_id\"] != historical[\"workspace_id\"]",
            "R22": "ORDER BY r.id",
            "R23": "candidate classification does not reconcile",
            "R24": "parsed, historical = _classify_candidates(connection, rows)",
            "R25": "_validate_candidate(successor, connection)",
        }
        for label, required_text in requirements.items():
            with self.subTest(label=label):
                self.assertIn(required_text, source)


if __name__ == "__main__":
    unittest.main()
