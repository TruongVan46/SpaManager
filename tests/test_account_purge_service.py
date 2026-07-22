import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_account_purge_service_test.sqlite"
if not os.environ.get("TEST_DATABASE_URL"):
    if TEST_DB_FILE.exists():
        TEST_DB_FILE.unlink()
    os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("SPAMANAGER_BOOTSTRAP_ACCOUNTS_ENABLED", "0")

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models.account_purge import (  # noqa: E402
    AccountPurgeLegalHold,
    AccountPurgeLifecycleEvent,
    AccountPurgeRequest,
    UserCreationProvenance,
)
from models.user import User  # noqa: E402
from models.workspace import Workspace, WorkspaceMember  # noqa: E402
from services.account_purge_service import (  # noqa: E402
    AccountPurgeAuthorizationError,
    AccountPurgeConflictError,
    AccountPurgeIneligibleError,
    AccountPurgePersistenceError,
    AccountPurgeService,
)
from utils.timezone_utils import utc_now  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402


class AccountPurgeServiceTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        if TEST_DB_FILE.exists():
            TEST_DB_FILE.unlink()

    def setUp(self):
        self.context = app.app_context()
        self.context.push()
        if db.engine.dialect.name == "postgresql":
            with db.engine.begin() as connection:
                for table_name in inspect(db.engine).get_table_names():
                    connection.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
        else:
            db.drop_all()
        db.create_all()
        self.owner = self._user("owner", "OWNER")
        self.target = self._user("target", "STAFF")
        self.workspace = Workspace(
            name="Managing Workspace",
            slug="managing-workspace",
            status="active",
            created_by_id=self.owner.id,
        )
        db.session.add(self.workspace)
        db.session.flush()
        self._membership(self.owner, self.workspace, "owner", "active")
        self.target_membership = self._membership(
            self.target, self.workspace, "staff", "removed", removed=True,
        )
        self.provenance = UserCreationProvenance(
            user_id=self.target.id,
            created_by_user_id=self.owner.id,
            created_in_workspace_id=self.workspace.id,
            creation_source="WORKSPACE_OWNER",
            created_role="STAFF",
            provenance_version=1,
        )
        db.session.add(self.provenance)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.context.pop()

    @staticmethod
    def _user(username, role, *, is_active=True, auth_provider="local", oauth_id=None):
        user = User(
            username=username,
            full_name=username.title(),
            role=role,
            is_active=is_active,
            approval_status=User.APPROVAL_ACTIVE,
            auth_provider=auth_provider,
            oauth_id=oauth_id,
        )
        user.set_password("StrongPassword123!")
        db.session.add(user)
        db.session.flush()
        return user

    @staticmethod
    def _membership(user, workspace, role, status, *, removed=False):
        membership = WorkspaceMember(
            user_id=user.id,
            workspace_id=workspace.id,
            role=role,
            status=status,
            removed_at=utc_now() if removed else None,
            removal_reason="workspace owner removal" if removed else None,
        )
        db.session.add(membership)
        db.session.flush()
        return membership

    def test_eligibility_requires_authoritative_deleted_workspace_state(self):
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertTrue(result.eligible)
        self.assertEqual(result.reason_code, "ELIGIBLE")
        self.assertEqual(result.provenance_status, "VALID")
        self.assertEqual(result.soft_delete_status, "REMOVED")

    def test_request_creation_persists_requested_row_and_event_atomically(self):
        request = AccountPurgeService.create_request(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
            reason="  Owner requested removal  for   policy  ",
        )
        self.assertEqual(request.state, "REQUESTED")
        self.assertEqual(request.target_provenance_id, self.provenance.id)
        self.assertEqual(request.reason, "Owner requested removal for policy")
        self.assertEqual(request.requester_name_snapshot, self.owner.full_name)
        self.assertEqual(request.target_username_snapshot, self.target.username)
        event = AccountPurgeLifecycleEvent.query.filter_by(request_id=request.id).one()
        self.assertEqual(event.event_type, "REQUESTED")
        self.assertEqual(event.to_state, "REQUESTED")
        self.assertEqual(event.actor_id, self.owner.id)
        self.assertEqual(self.target.account_purge_state, "NOT_PURGED")

    def test_requester_must_be_active_owner_of_managing_workspace(self):
        self.owner.role = "ADMIN"
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "REQUESTER_NOT_ACTIVE_OWNER")
        with self.assertRaises(AccountPurgeAuthorizationError):
            AccountPurgeService.create_request(
                requester_id=self.owner.id,
                target_user_id=self.target.id,
                managing_workspace_id=self.workspace.id,
                reason="reason",
            )

    def test_self_purge_and_protected_roles_fail_closed(self):
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.owner.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "SELF_PURGE_FORBIDDEN")
        self.target.role = "OWNER"
        self.target_membership.role = "owner"
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "TARGET_ROLE_PROTECTED")

    def test_missing_or_invalid_provenance_fails_closed(self):
        db.session.delete(self.provenance)
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "PROVENANCE_MISSING")

        self.provenance = UserCreationProvenance(
            user_id=self.target.id,
            created_by_user_id=self.owner.id,
            created_in_workspace_id=self.workspace.id,
            creation_source="LEGACY_UNKNOWN",
            created_role="STAFF",
            provenance_version=1,
        )
        db.session.add(self.provenance)
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "PROVENANCE_UNKNOWN")

    def test_google_and_external_workspace_history_fail_closed(self):
        self.target.auth_provider = "google"
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "GOOGLE_ACCOUNT_NOT_SUPPORTED")

        self.target.auth_provider = "local"
        external = Workspace(name="External", slug="external", status="active")
        db.session.add(external)
        db.session.flush()
        self._membership(self.target, external, "staff", "removed", removed=True)
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "EXTERNAL_WORKSPACE_HISTORY")

    def test_active_hold_and_active_request_block(self):
        hold = AccountPurgeLegalHold(
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
            state="ACTIVE",
            reason="Legal review",
            placed_by_name_snapshot=self.owner.full_name,
        )
        db.session.add(hold)
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "ACTIVE_LEGAL_HOLD")

        db.session.delete(hold)
        db.session.commit()
        request = AccountPurgeRequest(
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
            target_provenance_id=self.provenance.id,
            state="REQUESTED",
            requester_name_snapshot=self.owner.full_name,
            requester_role_snapshot="OWNER",
            target_role_snapshot="STAFF",
        )
        db.session.add(request)
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "ACTIVE_REQUEST_EXISTS")
        with self.assertRaises(AccountPurgeConflictError):
            AccountPurgeService.create_request(
                requester_id=self.owner.id,
                target_user_id=self.target.id,
                managing_workspace_id=self.workspace.id,
                reason="duplicate",
            )

    def test_active_membership_and_removed_metadata_are_required(self):
        self.target_membership.status = "active"
        self.target_membership.removed_at = None
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "TARGET_NOT_SOFT_DELETED")

        self.target_membership.status = "removed"
        self.target_membership.removed_at = None
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "INCONSISTENT_STATE")

    def test_released_hold_and_terminal_request_do_not_block(self):
        hold = AccountPurgeLegalHold(
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
            state="RELEASED",
            reason="Resolved",
            placed_by_name_snapshot=self.owner.full_name,
            released_at=utc_now(),
            released_by_name_snapshot=self.owner.full_name,
            release_reason="Resolved",
        )
        terminal_request = AccountPurgeRequest(
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
            target_provenance_id=self.provenance.id,
            state="CANCELLED",
            requester_name_snapshot=self.owner.full_name,
            requester_role_snapshot="OWNER",
            target_role_snapshot="STAFF",
        )
        db.session.add_all([hold, terminal_request])
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "ELIGIBLE")

    def test_wrong_workspace_and_source_role_fail_closed(self):
        other = Workspace(name="Other", slug="other", status="active")
        db.session.add(other)
        db.session.flush()
        self.provenance.created_in_workspace_id = other.id
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "PROVENANCE_WORKSPACE_MISMATCH")

        self.provenance.created_in_workspace_id = self.workspace.id
        self.provenance.creation_source = "SYSTEM_BOOTSTRAP"
        db.session.commit()
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertEqual(result.reason_code, "PROVENANCE_SOURCE_NOT_ELIGIBLE")

    def test_event_failure_rolls_back_request(self):
        with patch(
            "services.account_purge_service.AccountPurgeLifecycleEvent",
            side_effect=RuntimeError("event failure"),
        ):
            with self.assertRaises(AccountPurgePersistenceError):
                AccountPurgeService.create_request(
                    requester_id=self.owner.id,
                    target_user_id=self.target.id,
                    managing_workspace_id=self.workspace.id,
                    reason="atomicity",
                )
        self.assertEqual(AccountPurgeRequest.query.count(), 0)
        self.assertEqual(AccountPurgeLifecycleEvent.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
