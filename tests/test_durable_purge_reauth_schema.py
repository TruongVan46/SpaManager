import importlib
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


TEST_DB_FILE = Path(tempfile.gettempdir()) / f"spamanager_reauth_schema_{uuid.uuid4().hex}.sqlite"
os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["SPAMANAGER_TEST_PROCESS"] = "1"

from app import app
from extensions import db
from models.purge import (
    PurgeLifecycleEvent,
    WorkspacePurgeExecutionAuthorization,
    WorkspacePurgeReauthActorThrottle,
    WorkspacePurgeRequest,
)
from models.user import User
from models.workspace import Workspace


MIGRATION_0007 = importlib.import_module("migrations.versions.0007_permanent_purge_workflow")
MIGRATION_0008 = importlib.import_module("migrations.versions.0008_durable_purge_reauth_state")


class DurablePurgeReauthSchemaTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()
        inspector = inspect(db.engine)
        if not inspector.has_table("workspace_purge_requests"):
            db.create_all()
            MIGRATION_0007.upgrade()
        if not inspect(db.engine).has_table("workspace_purge_execution_authorizations"):
            MIGRATION_0008.upgrade()

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
        with db.engine.begin() as connection:
            for table_name in (
                "workspace_purge_execution_authorizations",
                "workspace_purge_reauth_actor_throttles",
                "purge_lifecycle_events",
                "workspace_purge_requests",
                "workspaces",
                "users",
            ):
                connection.execute(text(f"DELETE FROM {table_name}"))

    def tearDown(self):
        db.session.rollback()

    def _parents(self):
        actor = User(
            username=f"reauth_{uuid.uuid4().hex[:10]}",
            full_name="Reauth Actor",
            role="APPROVAL_OWNER",
            approval_status="active",
            is_active=True,
        )
        actor.set_password("Password123!")
        db.session.add(actor)
        db.session.flush()
        workspace = Workspace(
            name="Reauth Target",
            slug=f"reauth-{uuid.uuid4().hex}",
            status="active",
            deleted_at=datetime(2026, 1, 1),
            deleted_by_id=actor.id,
        )
        db.session.add(workspace)
        db.session.flush()
        request = WorkspacePurgeRequest(
            lifecycle_id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            purge_type="workspace",
            status="APPROVED",
            target_deleted_at=workspace.deleted_at,
            target_deleted_by_id=actor.id,
            target_deleted_by_snapshot=actor.username,
            target_workspace_name=workspace.name,
            target_workspace_slug=workspace.slug,
            requested_by_id=actor.id,
            requested_by_snapshot=actor.username,
            eligible_at=datetime(2026, 2, 1),
            retention_policy_version="workspace-purge-30d-v1",
            approved_by_id=actor.id,
            approved_by_snapshot=actor.username,
            approved_at=datetime(2026, 2, 1),
            manifest_version="purge-manifest-v1",
            manifest_canonical_text="{}",
            manifest_hash="0" * 64,
            idempotency_key=str(uuid.uuid4()),
            hold_check_status="CLEAR",
        )
        db.session.add(request)
        db.session.flush()
        event = PurgeLifecycleEvent(
            request_id=request.id,
            lifecycle_id_snapshot=request.lifecycle_id,
            workspace_id=workspace.id,
            workspace_name_snapshot=workspace.name,
            event_sequence=1,
            event_type="execution_started",
            actor_id=actor.id,
            actor_snapshot=actor.username,
            event_at=datetime(2026, 2, 1),
            status_before="APPROVED",
            status_after="EXECUTING",
            created_at=datetime(2026, 2, 1),
        )
        db.session.add(event)
        db.session.commit()
        return actor, request, event

    def _insert_authorization(self, request_id, actor_id, **overrides):
        values = {
            "purge_request_id": request_id,
            "actor_user_id": actor_id,
            "method": "local_password",
            "generation": 1,
            "state": "ACTIVE",
            "nonce_hash": "a" * 64,
            "authenticated_at": datetime(2026, 2, 1),
            "expires_at": datetime(2026, 2, 1, 0, 5),
        }
        values.update(overrides)
        columns = ", ".join(values)
        placeholders = ", ".join(f":{key}" for key in values)
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO workspace_purge_execution_authorizations ({columns}) "
                    f"VALUES ({placeholders})"
                ),
                values,
            )

    def test_exact_tables_and_models_have_no_workspace_binding(self):
        inspector = inspect(db.engine)
        self.assertEqual(
            set(inspector.get_table_names()) & {
                "workspace_purge_execution_authorizations",
                "workspace_purge_reauth_actor_throttles",
            },
            {
                "workspace_purge_execution_authorizations",
                "workspace_purge_reauth_actor_throttles",
            },
        )
        self.assertNotIn("workspace_id", {column["name"] for column in inspector.get_columns("workspace_purge_execution_authorizations")})
        self.assertNotIn("workspace_id", {column["name"] for column in inspector.get_columns("workspace_purge_reauth_actor_throttles")})
        self.assertEqual(WorkspacePurgeExecutionAuthorization.__table__.name, "workspace_purge_execution_authorizations")
        self.assertEqual(WorkspacePurgeReauthActorThrottle.__table__.name, "workspace_purge_reauth_actor_throttles")

    def test_upgrade_verifier_confirms_empty_schema_and_named_contract(self):
        with db.engine.begin() as connection:
            MIGRATION_0008.verify_upgrade(connection)

    def test_valid_active_shape_is_accepted(self):
        actor, request, _ = self._parents()
        self._insert_authorization(request.id, actor.id)
        row = db.session.execute(text("SELECT state FROM workspace_purge_execution_authorizations")).one()
        self.assertEqual(row[0], "ACTIVE")

    def test_invalid_state_method_and_generation_are_rejected(self):
        actor, request, _ = self._parents()
        for overrides in (
            {"state": "UNKNOWN"},
            {"method": "google"},
            {"generation": 0},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(IntegrityError):
                    self._insert_authorization(request.id, actor.id, **overrides)

    def test_active_authorization_can_be_revoked_without_consumption(self):
        actor, request, _ = self._parents()
        self._insert_authorization(
            request.id,
            actor.id,
            state="REVOKED",
            nonce_hash=None,
            revoked_at=datetime(2026, 2, 1),
            revocation_reason="LOGOUT",
        )
        state = db.session.execute(text("SELECT state FROM workspace_purge_execution_authorizations")).scalar_one()
        self.assertEqual(state, "REVOKED")

    def test_claimed_and_unresolved_shapes_are_enforced(self):
        actor, request, _ = self._parents()
        for state in ("CLAIMED", "CLAIMED_UNRESOLVED"):
            self._insert_authorization(
                request.id,
                actor.id,
                state=state,
                nonce_hash=None,
                consumed_at=datetime(2026, 2, 1),
                claimed_at=datetime(2026, 2, 1),
            )
            db.session.execute(text("DELETE FROM workspace_purge_execution_authorizations"))
            db.session.commit()

    def test_service_started_and_consumed_success_require_existing_event(self):
        actor, request, event = self._parents()
        for state in ("SERVICE_STARTED", "CONSUMED_SUCCESS"):
            self._insert_authorization(
                request.id,
                actor.id,
                state=state,
                nonce_hash=None,
                consumed_at=datetime(2026, 2, 1),
                claimed_at=datetime(2026, 2, 1),
                service_started_at=datetime(2026, 2, 1),
                execution_started_event_id=event.id,
            )
            db.session.execute(text("DELETE FROM workspace_purge_execution_authorizations"))
            db.session.commit()

    def test_invalid_active_shape_is_rejected(self):
        actor, request, _ = self._parents()
        with self.assertRaises(IntegrityError):
            self._insert_authorization(request.id, actor.id, nonce_hash=None)

    def test_execution_event_association_is_nullable_unique(self):
        actor, request, event = self._parents()
        self._insert_authorization(request.id, actor.id)
        db.session.execute(text("DELETE FROM workspace_purge_execution_authorizations"))
        db.session.commit()
        second_actor, second_request, _ = self._parents()
        self._insert_authorization(
            second_request.id,
            second_actor.id,
            state="SERVICE_STARTED",
            nonce_hash=None,
            consumed_at=datetime(2026, 2, 1),
            claimed_at=datetime(2026, 2, 1),
            service_started_at=datetime(2026, 2, 1),
            execution_started_event_id=event.id,
        )
        with self.assertRaises(IntegrityError):
            self._insert_authorization(
                request.id,
                actor.id,
                state="SERVICE_STARTED",
                nonce_hash=None,
                consumed_at=datetime(2026, 2, 1),
                claimed_at=datetime(2026, 2, 1),
                service_started_at=datetime(2026, 2, 1),
                execution_started_event_id=event.id,
            )

    def test_actor_global_throttle_contract(self):
        actor, _, _ = self._parents()
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspace_purge_reauth_actor_throttles "
                    "(actor_user_id, failed_attempt_count, first_failed_at, last_failed_at) "
                    "VALUES (:actor_id, 1, :now, :now)"
                ),
                {"actor_id": actor.id, "now": datetime(2026, 2, 1)},
            )
        with self.assertRaises(IntegrityError):
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO workspace_purge_reauth_actor_throttles "
                        "(actor_user_id, failed_attempt_count) VALUES (:actor_id, -1)"
                    ),
                    {"actor_id": actor.id},
                )

    def test_empty_downgrade_succeeds_and_reupgrade_restores_schema(self):
        MIGRATION_0008.downgrade()
        inspector = inspect(db.engine)
        self.assertNotIn("workspace_purge_execution_authorizations", inspector.get_table_names())
        self.assertNotIn("workspace_purge_reauth_actor_throttles", inspector.get_table_names())
        MIGRATION_0008.upgrade()
        with db.engine.begin() as connection:
            MIGRATION_0008.verify_upgrade(connection)

    def test_nonempty_authorization_blocks_downgrade_before_drop(self):
        actor, request, _ = self._parents()
        self._insert_authorization(request.id, actor.id)
        with self.assertRaises(RuntimeError):
            MIGRATION_0008.downgrade()
        inspector = inspect(db.engine)
        self.assertIn("workspace_purge_execution_authorizations", inspector.get_table_names())
        self.assertIn("workspace_purge_reauth_actor_throttles", inspector.get_table_names())

    def test_nonempty_throttle_blocks_downgrade_before_drop(self):
        actor, _, _ = self._parents()
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspace_purge_reauth_actor_throttles "
                    "(actor_user_id, failed_attempt_count, first_failed_at, last_failed_at) "
                    "VALUES (:actor_id, 1, :now, :now)"
                ),
                {"actor_id": actor.id, "now": datetime(2026, 2, 1)},
            )
        with self.assertRaises(RuntimeError):
            MIGRATION_0008.downgrade()
        inspector = inspect(db.engine)
        self.assertIn("workspace_purge_execution_authorizations", inspector.get_table_names())
        self.assertIn("workspace_purge_reauth_actor_throttles", inspector.get_table_names())
