import os
import hashlib
import json
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import inspect, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

TEST_DB_FILE = Path(tempfile.gettempdir()) / f"spamanager_purge_request_{uuid.uuid4().hex}.sqlite"
os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["SPAMANAGER_TEST_PROCESS"] = "1"

from app import app
from extensions import db
from models.purge import PurgeLifecycleEvent, WorkspacePurgeRequest
from models.purge import workspace_terminal_state_table
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.user_service import UserService
from services.purge_request_service import (
    PurgeRequestAuthorizationError,
    PurgeRequestConflictError,
    PurgeRequestService,
)


class PurgeRequestServiceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()
        if not inspect(db.engine).has_table("workspace_purge_requests"):
            db.create_all()
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
        for model in (PurgeLifecycleEvent, WorkspacePurgeRequest, WorkspaceMember, Workspace, User):
            db.session.query(model).delete(synchronize_session=False)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()

    def _fixture(self):
        requester = User(username=f"requester_{uuid.uuid4().hex[:8]}", full_name="Requester", role="APPROVAL_OWNER", approval_status="active", is_active=True)
        approver = User(username=f"approver_{uuid.uuid4().hex[:8]}", full_name="Approver", role="APPROVAL_OWNER", approval_status="active", is_active=True)
        requester.set_password("RequestPassword123!")
        approver.set_password("ApprovePassword123!")
        db.session.add_all([requester, approver])
        db.session.flush()
        workspace = Workspace(
            name="Deleted Target", slug=f"deleted-{uuid.uuid4().hex}", status="active",
            deleted_at=datetime(2026, 1, 1), deleted_by_id=requester.id,
        )
        db.session.add(workspace)
        db.session.commit()
        return requester, approver, workspace

    def test_create_request_uses_exact_phrase_and_immutable_manifest(self):
        requester, approver, workspace = self._fixture()
        with self.assertRaises(PurgeRequestConflictError):
            PurgeRequestService.create_purge_request(
                workspace_id=workspace.id, requester_user_id=requester.id,
                confirmation_phrase=f"request purge {workspace.slug}", now=datetime(2026, 2, 1),
            )
        summary = PurgeRequestService.create_purge_request(
            workspace_id=workspace.id, requester_user_id=requester.id,
            confirmation_phrase=f"  REQUEST PURGE {workspace.slug}  ", now=datetime(2026, 2, 1),
        )
        stored = db.session.get(WorkspacePurgeRequest, summary.id)
        self.assertEqual(stored.status, "PENDING_APPROVAL")
        self.assertEqual(stored.retention_policy_version, "workspace-purge-30d-v1")
        self.assertEqual(stored.eligible_at, datetime(2026, 1, 31))
        self.assertNotIn("request_id", stored.manifest_canonical_text)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="request_created").count(), 1)

    def test_duplicate_same_lifecycle_is_blocked(self):
        requester, approver, workspace = self._fixture()
        PurgeRequestService.create_purge_request(
            workspace_id=workspace.id, requester_user_id=requester.id,
            confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
        )
        with self.assertRaises(PurgeRequestConflictError) as error:
            PurgeRequestService.create_purge_request(
                workspace_id=workspace.id, requester_user_id=requester.id,
                confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
            )
        self.assertEqual(error.exception.code, "DUPLICATE_LIFECYCLE")
        self.assertEqual(db.session.query(WorkspacePurgeRequest).count(), 1)

    def test_approval_requires_other_actor_and_exact_phrase(self):
        requester, approver, workspace = self._fixture()
        summary = PurgeRequestService.create_purge_request(
            workspace_id=workspace.id, requester_user_id=requester.id,
            confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
        )
        with self.assertRaises(PurgeRequestConflictError):
            PurgeRequestService.approve_purge_request(
                request_id=summary.id, approver_user_id=approver.id,
                confirmation_phrase=f"APPROVE PURGE {workspace.slug} wrong", now=datetime(2026, 2, 1),
            )
        with self.assertRaises(PurgeRequestAuthorizationError):
            PurgeRequestService.approve_purge_request(
                request_id=summary.id, approver_user_id=requester.id,
                confirmation_phrase=f"APPROVE PURGE {workspace.slug} {summary.lifecycle_id}", now=datetime(2026, 2, 1),
            )
        approved = PurgeRequestService.approve_purge_request(
            request_id=summary.id, approver_user_id=approver.id,
            confirmation_phrase=f"APPROVE PURGE {workspace.slug} {summary.lifecycle_id}", now=datetime(2026, 2, 1),
        )
        self.assertEqual(approved.status, "APPROVED")

    def test_terminal_marker_blocks_approval_without_mutating_request_or_events(self):
        requester, approver, workspace = self._fixture()
        summary = PurgeRequestService.create_purge_request(
            workspace_id=workspace.id, requester_user_id=requester.id,
            confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
        )
        stored = db.session.get(WorkspacePurgeRequest, summary.id)
        before_status = stored.status
        before_manifest = stored.manifest_hash
        before_events = db.session.query(PurgeLifecycleEvent).filter_by(request_id=summary.id).count()
        with patch.object(PurgeRequestService, "_terminal", return_value={"purged_at": None, "purge_request_id": summary.id}):
            with self.assertRaises(PurgeRequestConflictError) as error:
                PurgeRequestService.approve_purge_request(
                    request_id=summary.id, approver_user_id=approver.id,
                    confirmation_phrase=f"APPROVE PURGE {workspace.slug} {summary.lifecycle_id}", now=datetime(2026, 2, 1),
                )
        self.assertEqual(error.exception.code, "ALREADY_PURGED")
        db.session.expire_all()
        stored = db.session.get(WorkspacePurgeRequest, summary.id)
        self.assertEqual(stored.status, before_status)
        self.assertEqual(stored.manifest_hash, before_manifest)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(request_id=summary.id).count(), before_events)

    def test_integrity_error_with_existing_lifecycle_maps_to_duplicate(self):
        requester, approver, workspace = self._fixture()
        original_commit = Session.commit

        def commit_then_raise(session):
            original_commit(session)
            raise IntegrityError("simulated duplicate", {}, Exception("duplicate"))

        with patch.object(Session, "commit", new=commit_then_raise):
            with self.assertRaises(PurgeRequestConflictError) as error:
                PurgeRequestService.create_purge_request(
                    workspace_id=workspace.id, requester_user_id=requester.id,
                    confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
                )
        self.assertEqual(error.exception.code, "DUPLICATE_LIFECYCLE")
        self.assertEqual(db.session.query(WorkspacePurgeRequest).count(), 1)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="request_created").count(), 1)

    def test_unrelated_integrity_error_maps_to_persistence_error(self):
        requester, approver, workspace = self._fixture()
        with patch.object(Session, "commit", side_effect=IntegrityError("simulated unrelated", {}, Exception("other"))):
            with self.assertRaises(PurgeRequestConflictError) as error:
                PurgeRequestService.create_purge_request(
                    workspace_id=workspace.id, requester_user_id=requester.id,
                    confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
                )
        self.assertEqual(error.exception.code, "PERSISTENCE_ERROR")

    def test_pending_retention_promotes_atomically_at_eligible_boundary(self):
        requester, approver, workspace = self._fixture()
        workspace.deleted_at = datetime(2026, 2, 1)
        db.session.commit()
        summary = PurgeRequestService.create_purge_request(
            workspace_id=workspace.id, requester_user_id=requester.id,
            confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
        )
        self.assertEqual(summary.status, "PENDING_RETENTION")
        with self.assertRaises(PurgeRequestConflictError) as before:
            PurgeRequestService.approve_purge_request(
                request_id=summary.id, approver_user_id=approver.id,
                confirmation_phrase=f"APPROVE PURGE {workspace.slug} {summary.lifecycle_id}", now=datetime(2026, 1, 31, 23, 59, 59),
            )
        self.assertEqual(before.exception.code, "RETENTION_NOT_REACHED")
        approved = PurgeRequestService.approve_purge_request(
            request_id=summary.id, approver_user_id=approver.id,
            confirmation_phrase=f"APPROVE PURGE {workspace.slug} {summary.lifecycle_id}", now=datetime(2026, 3, 3),
        )
        self.assertEqual(approved.status, "APPROVED")
        events = db.session.query(PurgeLifecycleEvent).filter_by(request_id=summary.id).all()
        self.assertEqual(sum(event.event_type == "retention_reached" for event in events), 1)
        self.assertEqual(sum(event.event_type == "pending_approval" for event in events), 1)

    def test_malformed_manifest_summary_is_safe_and_not_approvable(self):
        requester, approver, workspace = self._fixture()
        summary = PurgeRequestService.create_purge_request(
            workspace_id=workspace.id, requester_user_id=requester.id,
            confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
        )
        stored = db.session.get(WorkspacePurgeRequest, summary.id)
        stored.manifest_canonical_text = "{bad-json"
        db.session.commit()
        read_summary = PurgeRequestService.get_summary(summary.id)
        self.assertFalse(read_summary.manifest_valid)
        self.assertEqual(read_summary.manifest_error, "MANIFEST_INVALID")
        self.assertEqual(read_summary.destructive_counts, {})

    def test_manifest_payload_validation_rejects_version_hash_shape_and_unsafe_counts(self):
        invalid_payloads = (
            ("payload_version", {"manifest_version": "purge-manifest-v0", "destructive": []}),
            ("unknown_table", {"manifest_version": "purge-manifest-v1", "destructive": [{"table": "users", "count": 1}], "preserved": [], "external_assets": []}),
            ("duplicate_table", {"manifest_version": "purge-manifest-v1", "destructive": [{"table": "customers", "count": 1}, {"table": "customers", "count": 1}], "preserved": [], "external_assets": []}),
            ("bool_count", {"manifest_version": "purge-manifest-v1", "destructive": [{"table": "customers", "count": True}], "preserved": [], "external_assets": []}),
            ("negative_count", {"manifest_version": "purge-manifest-v1", "destructive": [{"table": "customers", "count": -1}], "preserved": [], "external_assets": []}),
            ("wrong_shape", {"manifest_version": "purge-manifest-v1", "destructive": {}, "preserved": [], "external_assets": []}),
        )
        for name, payload in invalid_payloads:
            with self.subTest(name=name):
                requester, approver, workspace = self._fixture()
                summary = PurgeRequestService.create_purge_request(
                    workspace_id=workspace.id, requester_user_id=requester.id,
                    confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
                )
                stored = db.session.get(WorkspacePurgeRequest, summary.id)
                stored.manifest_canonical_text = json.dumps(payload, separators=(",", ":"))
                stored.manifest_hash = hashlib.sha256(stored.manifest_canonical_text.encode("utf-8")).hexdigest()
                db.session.commit()
                read_summary = PurgeRequestService.get_summary(summary.id)
                self.assertFalse(read_summary.manifest_valid)

    def test_restore_invalidation_failure_rolls_back_restore(self):
        approver = User(username=f"restore_actor_{uuid.uuid4().hex[:8]}", full_name="Approval", role="APPROVAL_OWNER", approval_status="active", is_active=True)
        owner = User(username=f"owner_{uuid.uuid4().hex[:8]}", full_name="Owner", role="OWNER", approval_status="active", is_active=False, deleted_at=datetime(2026, 1, 1), deleted_by_id=1)
        approver.set_password("ApprovalPassword123!")
        owner.set_password("OwnerPassword123!")
        db.session.add_all([approver, owner])
        db.session.flush()
        owner.deleted_by_id = approver.id
        workspace = Workspace(name="Restore Target", slug=f"restore-{uuid.uuid4().hex}", status="active", deleted_at=datetime(2026, 1, 1), deleted_by_id=approver.id)
        db.session.add(workspace)
        db.session.flush()
        db.session.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner", status="active"))
        db.session.commit()
        summary = PurgeRequestService.create_purge_request(
            workspace_id=workspace.id, requester_user_id=approver.id,
            confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
        )
        with patch("services.purge_request_service.PurgeRequestService._event", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                UserService.restore_owner_workspace(approver, owner.id)
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(User, owner.id).deleted_at)
        self.assertIsNotNone(db.session.get(Workspace, workspace.id).deleted_at)
        self.assertIsNone(db.session.get(WorkspacePurgeRequest, summary.id).invalidated_at)

    def test_restore_candidate_scope_ignores_skipped_executing_workspace(self):
        approver = User(username=f"scope_actor_{uuid.uuid4().hex[:8]}", full_name="Approval", role="APPROVAL_OWNER", approval_status="active", is_active=True)
        other_actor = User(username=f"other_actor_{uuid.uuid4().hex[:8]}", full_name="Other", role="APPROVAL_OWNER", approval_status="active", is_active=True)
        owner = User(username=f"scope_owner_{uuid.uuid4().hex[:8]}", full_name="Owner", role="OWNER", approval_status="active", is_active=False, deleted_at=datetime(2026, 1, 1), deleted_by_id=1)
        for account in (approver, other_actor, owner):
            account.set_password("ScopePassword123!")
        db.session.add_all([approver, other_actor, owner])
        db.session.flush()
        owner.deleted_by_id = approver.id
        workspace_a = Workspace(name="Matching", slug=f"matching-{uuid.uuid4().hex}", status="active", deleted_at=datetime(2026, 1, 1), deleted_by_id=approver.id)
        workspace_b = Workspace(name="Skipped", slug=f"skipped-{uuid.uuid4().hex}", status="active", deleted_at=datetime(2026, 1, 1), deleted_by_id=other_actor.id)
        db.session.add_all([workspace_a, workspace_b])
        db.session.flush()
        db.session.add_all([
            WorkspaceMember(workspace_id=workspace_a.id, user_id=owner.id, role="owner", status="active"),
            WorkspaceMember(workspace_id=workspace_b.id, user_id=owner.id, role="owner", status="active"),
        ])
        db.session.commit()
        request_a = PurgeRequestService.create_purge_request(
            workspace_id=workspace_a.id, requester_user_id=approver.id,
            confirmation_phrase=f"REQUEST PURGE {workspace_a.slug}", now=datetime(2026, 2, 1),
        )
        request_b = PurgeRequestService.create_purge_request(
            workspace_id=workspace_b.id, requester_user_id=approver.id,
            confirmation_phrase=f"REQUEST PURGE {workspace_b.slug}", now=datetime(2026, 2, 1),
        )
        db.session.query(WorkspacePurgeRequest).filter_by(id=request_b.id).update({"status": "EXECUTING"})
        db.session.commit()
        UserService.restore_owner_workspace(approver, owner.id)
        db.session.expire_all()
        self.assertIsNone(db.session.get(Workspace, workspace_a.id).deleted_at)
        self.assertIsNotNone(db.session.get(Workspace, workspace_b.id).deleted_at)
        self.assertIsNotNone(db.session.get(WorkspacePurgeRequest, request_a.id).invalidated_at)
        self.assertEqual(db.session.get(WorkspacePurgeRequest, request_b.id).status, "EXECUTING")

    def test_already_invalidated_restore_request_gets_no_second_event(self):
        approver = User(username=f"already_actor_{uuid.uuid4().hex[:8]}", full_name="Approval", role="APPROVAL_OWNER", approval_status="active", is_active=True)
        owner = User(username=f"already_owner_{uuid.uuid4().hex[:8]}", full_name="Owner", role="OWNER", approval_status="active", is_active=False, deleted_at=datetime(2026, 1, 1), deleted_by_id=1)
        approver.set_password("AlreadyPassword123!")
        owner.set_password("AlreadyPassword123!")
        db.session.add_all([approver, owner])
        db.session.flush()
        owner.deleted_by_id = approver.id
        workspace = Workspace(name="Already Invalidated", slug=f"already-{uuid.uuid4().hex}", status="active", deleted_at=datetime(2026, 1, 1), deleted_by_id=approver.id)
        db.session.add(workspace)
        db.session.flush()
        db.session.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner", status="active"))
        db.session.commit()
        summary = PurgeRequestService.create_purge_request(
            workspace_id=workspace.id, requester_user_id=approver.id,
            confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
        )
        old_time = datetime(2026, 2, 2)
        stored = db.session.get(WorkspacePurgeRequest, summary.id)
        stored.invalidated_at = old_time
        stored.invalidated_by_restore = True
        stored.invalidation_reason = "Already invalidated."
        db.session.add(PurgeLifecycleEvent(
            request_id=stored.id, lifecycle_id_snapshot=stored.lifecycle_id,
            workspace_id=workspace.id, workspace_name_snapshot=workspace.name,
            event_sequence=2, event_type="manifest_invalidated", actor_id=approver.id,
            actor_snapshot=approver.username, event_at=old_time,
            status_before=stored.status, status_after=stored.status,
            reason_code="MANIFEST_INVALIDATED", sanitized_summary="Already invalidated.",
        ))
        db.session.commit()
        before_count = db.session.query(PurgeLifecycleEvent).filter_by(request_id=stored.id, event_type="manifest_invalidated").count()
        UserService.restore_owner_workspace(approver, owner.id)
        db.session.expire_all()
        after = db.session.get(WorkspacePurgeRequest, stored.id)
        self.assertEqual(after.invalidated_at, old_time)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(request_id=stored.id, event_type="manifest_invalidated").count(), before_count)

    def test_restore_invalidation_is_scoped_to_matching_lifecycle(self):
        requester, approver, workspace = self._fixture()
        summary = PurgeRequestService.create_purge_request(
            workspace_id=workspace.id, requester_user_id=requester.id,
            confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=datetime(2026, 2, 1),
        )
        with db.session.begin_nested():
            workspace.deleted_at = None
            PurgeRequestService.invalidate_requests_for_workspace_restore(
                db.session, workspace.id, datetime(2026, 1, 1), requester.id, now=datetime(2026, 2, 1),
            )
        db.session.commit()
        stored = db.session.get(WorkspacePurgeRequest, summary.id)
        self.assertIsNotNone(stored.invalidated_at)
        self.assertTrue(stored.invalidated_by_restore)
        self.assertEqual(db.session.query(PurgeLifecycleEvent).filter_by(event_type="manifest_invalidated").count(), 1)


if __name__ == "__main__":
    unittest.main()
