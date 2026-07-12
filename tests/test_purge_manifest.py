import hashlib
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from sqlalchemy import inspect, text


TEST_DB_FILE = Path(tempfile.gettempdir()) / f"spamanager_purge_manifest_{uuid.uuid4().hex}.sqlite"
os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["SPAMANAGER_TEST_PROCESS"] = "1"

from app import app
from extensions import db
from models.workspace import Workspace
from models.activity_log import ActivityLog
from models.appointment import Appointment
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from models.service import Service
from models.setting import Setting
from models.user import User
from models.workspace import WorkspaceMember
from services.purge_manifest import (
    EMPTY_DIGEST,
    PurgeManifestError,
    build_manifest,
    build_purge_plan,
    canonicalize_manifest,
    row_set_sha256,
)


class PurgeManifestTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global WorkspacePurgeRequest
        from models.purge import WorkspacePurgeRequest
        cls.app_context = app.app_context()
        cls.app_context.push()
        db.session.remove()
        with db.engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            for table_name in inspect(db.engine).get_table_names():
                connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
            connection.execute(text("PRAGMA foreign_keys=ON"))
        db.create_all()
        if inspect(db.engine).has_table("workspace_purge_requests") or inspect(db.engine).has_table("purge_legal_holds") or inspect(db.engine).has_table("purge_lifecycle_events"):
            raise AssertionError("db.create_all created workflow tables before migration 0007")
        import importlib
        importlib.import_module("migrations.versions.0007_permanent_purge_workflow").upgrade()

    @classmethod
    def tearDownClass(cls):
        try:
            db.session.remove()
            db.engine.dispose()
        finally:
            cls.app_context.pop()
            if TEST_DB_FILE.exists():
                TEST_DB_FILE.unlink()

    def setUp(self):
        db.session.remove()
        for model in (WorkspacePurgeRequest, ActivityLog, InvoiceDetail, Appointment, Invoice, Customer, Service, Setting, WorkspaceMember, Workspace, User):
            db.session.query(model).delete(synchronize_session=False)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()

    def test_row_set_fingerprint_is_numeric_and_fail_closed(self):
        self.assertEqual(row_set_sha256([]), EMPTY_DIGEST)
        self.assertEqual(row_set_sha256([10, 2, 1]), row_set_sha256([1, 10, 2]))
        for invalid in ([1, 1], [0], [-1], ["1"], [True]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(PurgeManifestError):
                    row_set_sha256(invalid)

    def test_canonical_payload_excludes_request_id_and_uses_lifecycle_identity(self):
        payload = {
            "manifest_version": "purge-manifest-v1",
            "lifecycle_id": "00000000-0000-0000-0000-000000000002",
            "workspace_id": 7,
            "target_deleted_at": "2026-01-01T00:00:00.000000Z",
            "target_deleted_by_id": 42,
            "retention": {
                "eligible_at": "2026-01-31T00:00:00.000000Z",
                "policy_version": "retention-v1",
            },
            "destructive": [],
            "preserved": [],
            "external_assets": [],
        }
        text = canonicalize_manifest(payload)
        self.assertNotIn("request_id", text)
        self.assertFalse(text.endswith("\n"))
        self.assertEqual(
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "7d2f2531e8d2fb8819cf91e80c43b7a2e9e4d34070b35b1ad297e3a02c0cdcea",
        )

    def test_vector_2_and_vector_3_change_only_invoice_detail_digest(self):
        def payload(invoice_detail_digest):
            one = "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b"
            destructive = []
            for table, scope, digest in (
                ("invoice_details", "invoice_details_via_invoices.workspace_id", invoice_detail_digest),
                ("appointments", "appointments.workspace_id", one),
                ("invoices", "invoices.workspace_id", one),
                ("customers", "customers.workspace_id", one),
                ("services", "services.workspace_id", one),
                ("settings", "settings.workspace_id", one),
                ("workspace_members", "workspace_members.workspace_id", one),
            ):
                destructive.append({"table": table, "action": "DELETE", "scope": scope, "count": 1, "row_set_sha256": digest})
            return {
                "manifest_version": "purge-manifest-v1",
                "lifecycle_id": "00000000-0000-0000-0000-000000000002",
                "workspace_id": 7,
                "target_deleted_at": "2026-01-01T00:00:00.000000Z",
                "target_deleted_by_id": 42,
                "retention": {"eligible_at": "2026-01-31T00:00:00.000000Z", "policy_version": "retention-v1"},
                "destructive": destructive,
                "preserved": [],
                "external_assets": [],
            }

        vector_2 = canonicalize_manifest(payload("6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b"))
        vector_3 = canonicalize_manifest(payload("d4735e3a265e16eee03f59718b9b5d03019c07d8b6c51f90da3a666eec13ab35"))
        self.assertNotEqual(vector_2, vector_3)
        self.assertNotEqual(hashlib.sha256(vector_2.encode()).hexdigest(), hashlib.sha256(vector_3.encode()).hexdigest())

    def test_vector_4_canonicalizes_all_row_sets_independently_of_input_order(self):
        expected_row_digest = "881af7b459033bb64ca9409734a3357fde03846195317a9ac027be16814549db"
        expected_text = (
            '{"manifest_version":"purge-manifest-v1","lifecycle_id":"00000000-0000-0000-0000-000000000004",'
            '"workspace_id":7,"target_deleted_at":"2026-01-01T00:00:00.000000Z","target_deleted_by_id":42,'
            '"retention":{"eligible_at":"2026-01-31T00:00:00.000000Z","policy_version":"retention-v1"},'
            '"destructive":[{"table":"invoice_details","action":"DELETE","scope":"invoice_details_via_invoices.workspace_id",'
            '"count":3,"row_set_sha256":"881af7b459033bb64ca9409734a3357fde03846195317a9ac027be16814549db"},'
            '{"table":"appointments","action":"DELETE","scope":"appointments.workspace_id","count":3,'
            '"row_set_sha256":"881af7b459033bb64ca9409734a3357fde03846195317a9ac027be16814549db"},'
            '{"table":"invoices","action":"DELETE","scope":"invoices.workspace_id","count":3,'
            '"row_set_sha256":"881af7b459033bb64ca9409734a3357fde03846195317a9ac027be16814549db"},'
            '{"table":"customers","action":"DELETE","scope":"customers.workspace_id","count":3,'
            '"row_set_sha256":"881af7b459033bb64ca9409734a3357fde03846195317a9ac027be16814549db"},'
            '{"table":"services","action":"DELETE","scope":"services.workspace_id","count":3,'
            '"row_set_sha256":"881af7b459033bb64ca9409734a3357fde03846195317a9ac027be16814549db"},'
            '{"table":"settings","action":"DELETE","scope":"settings.workspace_id","count":3,'
            '"row_set_sha256":"881af7b459033bb64ca9409734a3357fde03846195317a9ac027be16814549db"},'
            '{"table":"workspace_members","action":"DELETE","scope":"workspace_members.workspace_id","count":3,'
            '"row_set_sha256":"881af7b459033bb64ca9409734a3357fde03846195317a9ac027be16814549db"}],'
            '"preserved":[{"table":"users","disposition":"PRESERVE"},{"table":"activity_logs","disposition":"PRESERVE"},'
            '{"table":"workspace_purge_requests","disposition":"PRESERVE"},{"table":"purge_legal_holds","disposition":"PRESERVE"},'
            '{"table":"purge_lifecycle_events","disposition":"PRESERVE"},{"table":"workspaces","disposition":"PRESERVE_TERMINAL_TOMBSTONE"}],'
            '"external_assets":[{"category":"workspace_logo","ownership":"WORKSPACE","disposition":"REQUIRE_ABSENT",'
            '"inventory_status":"RESOLVED","count":0,"row_set_sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},'
            '{"category":"user_avatar","ownership":"USER","disposition":"PRESERVE","inventory_status":"NOT_IN_PURGE_SCOPE",'
            '"count":null,"row_set_sha256":null},{"category":"global_backup","ownership":"GLOBAL","disposition":"GLOBAL_PRESERVE",'
            '"inventory_status":"NOT_IN_PURGE_SCOPE","count":null,"row_set_sha256":null},{"category":"operational_log","ownership":"GLOBAL",'
            '"disposition":"GLOBAL_PRESERVE","inventory_status":"NOT_IN_PURGE_SCOPE","count":null,"row_set_sha256":null},'
            '{"category":"transient_export_import","ownership":"REQUEST_SCOPED","disposition":"NOT_PERSISTENT",'
            '"inventory_status":"NOT_IN_PURGE_SCOPE","count":null,"row_set_sha256":null}]}'
        )

        def payload(raw_groups):
            tables = (
                ("invoice_details", "invoice_details_via_invoices.workspace_id"),
                ("appointments", "appointments.workspace_id"),
                ("invoices", "invoices.workspace_id"),
                ("customers", "customers.workspace_id"),
                ("services", "services.workspace_id"),
                ("settings", "settings.workspace_id"),
                ("workspace_members", "workspace_members.workspace_id"),
            )
            return {
                "manifest_version": "purge-manifest-v1",
                "lifecycle_id": "00000000-0000-0000-0000-000000000004",
                "workspace_id": 7,
                "target_deleted_at": "2026-01-01T00:00:00.000000Z",
                "target_deleted_by_id": 42,
                "retention": {
                    "eligible_at": "2026-01-31T00:00:00.000000Z",
                    "policy_version": "retention-v1",
                },
                "destructive": [
                    {
                        "table": table,
                        "action": "DELETE",
                        "scope": scope,
                        "count": len(ids),
                        "row_set_sha256": row_set_sha256(ids),
                    }
                    for (table, scope), ids in zip(tables, raw_groups)
                ],
                "preserved": [
                    {"table": "users", "disposition": "PRESERVE"},
                    {"table": "activity_logs", "disposition": "PRESERVE"},
                    {"table": "workspace_purge_requests", "disposition": "PRESERVE"},
                    {"table": "purge_legal_holds", "disposition": "PRESERVE"},
                    {"table": "purge_lifecycle_events", "disposition": "PRESERVE"},
                    {"table": "workspaces", "disposition": "PRESERVE_TERMINAL_TOMBSTONE"},
                ],
                "external_assets": [
                    {
                        "category": "workspace_logo",
                        "ownership": "WORKSPACE",
                        "disposition": "REQUIRE_ABSENT",
                        "inventory_status": "RESOLVED",
                        "count": 0,
                        "row_set_sha256": EMPTY_DIGEST,
                    },
                    {
                        "category": "user_avatar",
                        "ownership": "USER",
                        "disposition": "PRESERVE",
                        "inventory_status": "NOT_IN_PURGE_SCOPE",
                        "count": None,
                        "row_set_sha256": None,
                    },
                    {
                        "category": "global_backup",
                        "ownership": "GLOBAL",
                        "disposition": "GLOBAL_PRESERVE",
                        "inventory_status": "NOT_IN_PURGE_SCOPE",
                        "count": None,
                        "row_set_sha256": None,
                    },
                    {
                        "category": "operational_log",
                        "ownership": "GLOBAL",
                        "disposition": "GLOBAL_PRESERVE",
                        "inventory_status": "NOT_IN_PURGE_SCOPE",
                        "count": None,
                        "row_set_sha256": None,
                    },
                    {
                        "category": "transient_export_import",
                        "ownership": "REQUEST_SCOPED",
                        "disposition": "NOT_PERSISTENT",
                        "inventory_status": "NOT_IN_PURGE_SCOPE",
                        "count": None,
                        "row_set_sha256": None,
                    },
                ],
            }

        run_a = canonicalize_manifest(payload(([10, 2, 1], [1, 10, 2], [2, 10, 1], [10, 1, 2], [2, 1, 10], [1, 2, 10], [10, 2, 1])))
        run_b = canonicalize_manifest(payload(([1, 10, 2], [10, 1, 2], [2, 1, 10], [1, 2, 10], [10, 2, 1], [2, 10, 1], [1, 10, 2])))
        self.assertEqual(run_a, run_b)
        self.assertEqual(run_a, expected_text)
        self.assertNotIn("request_id", run_a)
        self.assertIn('"lifecycle_id":"00000000-0000-0000-0000-000000000004"', run_a)
        self.assertEqual(set(json.loads(run_a)["retention"]), {"eligible_at", "policy_version"})
        self.assertEqual(hashlib.sha256(run_a.encode("utf-8")).hexdigest(), "4f8e536fc63ae4342039ded875e1b14507b5df5cf8317d066564c298886d75b3")
        self.assertEqual(hashlib.sha256(run_b.encode("utf-8")).hexdigest(), "4f8e536fc63ae4342039ded875e1b14507b5df5cf8317d066564c298886d75b3")
        self.assertFalse(run_a.endswith("\n"))

    def test_builder_uses_actual_request_schema_and_workspace_scope(self):
        workspace = Workspace(
            name="Manifest Workspace",
            slug=f"manifest-{uuid.uuid4().hex}",
            status="active",
            deleted_at=datetime(2026, 1, 1),
        )
        db.session.add(workspace)
        db.session.flush()
        request = WorkspacePurgeRequest(
            lifecycle_id="00000000-0000-0000-0000-000000000010",
            workspace_id=workspace.id,
            target_deleted_at=workspace.deleted_at,
            target_deleted_by_snapshot="owner",
            target_workspace_name=workspace.name,
            target_workspace_slug=workspace.slug,
            requested_by_snapshot="requester",
            eligible_at=datetime(2026, 2, 1),
            retention_policy_version="retention-v1",
            manifest_version="purge-manifest-v1",
            manifest_canonical_text="{}",
            manifest_hash="0" * 64,
            idempotency_key="manifest-test-10",
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        db.session.add(request)
        db.session.commit()
        canonical_text, digest = build_manifest(db.session, request, workspace, build_purge_plan(db.session, workspace))
        self.assertIn('"lifecycle_id":"00000000-0000-0000-0000-000000000010"', canonical_text)
        self.assertNotIn('"request_id"', canonical_text)
        self.assertEqual(len(digest), 64)

    def test_runtime_mapping_matches_migrated_workflow_schema(self):
        inspector = inspect(db.engine)
        expected = {
            "workspace_purge_requests": set(WorkspacePurgeRequest.__table__.columns.keys()),
        }
        from models.purge import PurgeLegalHold, PurgeLifecycleEvent
        expected["purge_legal_holds"] = set(PurgeLegalHold.__table__.columns.keys())
        expected["purge_lifecycle_events"] = set(PurgeLifecycleEvent.__table__.columns.keys())
        for table_name, columns in expected.items():
            self.assertEqual(set(inspector.get_columns(table_name)[i]["name"] for i in range(len(inspector.get_columns(table_name)))), columns)
        self.assertEqual(
            {column.name for column in models_purge_workspace_terminal_columns()},
            {"id", "deleted_at", "deleted_by_id", "purged_at", "purge_request_id"},
        )


def models_purge_workspace_terminal_columns():
    from models.purge import workspace_terminal_state_table
    return workspace_terminal_state_table.columns
