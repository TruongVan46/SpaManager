import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

TEST_DB = Path(tempfile.gettempdir()) / "spamanager_account_purge_reauth_test.sqlite"
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("TEST_DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")

from app import app
from extensions import db
from models.account_purge import AccountPurgeExecutionAuthorization, AccountPurgeLifecycleEvent
from models.purge import WorkspacePurgeReauthActorThrottle
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.account_purge_approval_service import AccountPurgeApprovalService
from services.account_purge_reauth_service import (
    AccountPurgeReauthError,
    AccountPurgeReauthService,
    EVENT_CLAIMED,
    EVENT_REVOKED,
)
from services.account_purge_service import AccountPurgeService
from models.account_purge import UserCreationProvenance


class AccountPurgeReauthServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context()
        cls.context.push()
        db.create_all()
        if not inspect(db.engine).has_table("workspace_purge_reauth_actor_throttles"):
            with db.engine.begin() as connection:
                connection.execute(text("""
                    CREATE TABLE workspace_purge_reauth_actor_throttles (
                        actor_user_id INTEGER PRIMARY KEY NOT NULL,
                        failed_attempt_count INTEGER NOT NULL DEFAULT 0,
                        first_failed_at DATETIME,
                        last_failed_at DATETIME,
                        locked_until DATETIME,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE RESTRICT
                    )
                """))

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        if TEST_DB.exists():
            TEST_DB.unlink()
        cls.context.pop()

    def setUp(self):
        db.session.remove()
        with db.engine.begin() as connection:
            for table_name in (
                "account_purge_execution_authorizations",
                "workspace_purge_reauth_actor_throttles",
                "account_purge_lifecycle_events",
                "account_purge_legal_holds",
                "account_purge_requests",
                "user_creation_provenance",
                "workspace_members",
                "workspaces",
                "users",
            ):
                connection.execute(text(f"DELETE FROM {table_name}"))
        self.workspace = Workspace(name="Reauth", slug="reauth-managed", status="active")
        self.requester = self._user("reauth_requester", "OWNER")
        self.approver = self._user("reauth_approver", "APPROVAL_OWNER")
        self.executor = self._user("reauth_executor", "APPROVAL_OWNER")
        self.unauthorized = self._user("reauth_staff", "STAFF")
        self.target = self._user("reauth_target", "STAFF")
        db.session.add(self.workspace)
        db.session.flush()
        db.session.add_all([
            WorkspaceMember(workspace_id=self.workspace.id, user_id=self.requester.id, role="owner", status="active"),
            WorkspaceMember(workspace_id=self.workspace.id, user_id=self.target.id, role="staff", status="removed", removed_at=datetime(2026, 1, 1)),
            UserCreationProvenance(
                user_id=self.target.id, created_by_user_id=self.requester.id,
                created_in_workspace_id=self.workspace.id, creation_source="WORKSPACE_OWNER",
                created_role="STAFF", provenance_version=1,
            ),
        ])
        db.session.commit()
        request = AccountPurgeService.create_request(
            requester_id=self.requester.id,
            target_user_id=self.target.id,
            managing_workspace_id=self.workspace.id,
            reason="reauth test request",
            now=datetime(2026, 2, 1),
        )
        AccountPurgeApprovalService.approve_request(
            request_id=request.id, approver_user_id=self.approver.id, expected_version=1
        )
        self.request_id = request.id

    def _user(self, username, role):
        user = User(
            username=username,
            email=f"{username}@example.test",
            full_name=username.title(),
            role=role,
            is_active=True,
            approval_status="active",
        )
        user.set_password("StrongPassword123!")
        db.session.add(user)
        db.session.flush()
        return user

    def _assert_code(self, callback, code):
        with self.assertRaises(AccountPurgeReauthError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_issuance_persists_hash_expiry_event_and_keeps_request_approved(self):
        result = AccountPurgeReauthService.reauthenticate_and_issue(
            self.request_id, self.executor.id, "StrongPassword123!"
        )
        authorization = db.session.get(AccountPurgeExecutionAuthorization, result.authorization_id)
        self.assertEqual(authorization.state, "ACTIVE")
        self.assertEqual(authorization.actor_user_id, self.executor.id)
        self.assertEqual(len(authorization.nonce_hash), 64)
        self.assertEqual(result.expires_at - result.authenticated_at, timedelta(minutes=5))
        self.assertNotIn(result.raw_nonce, repr(result))
        event = AccountPurgeLifecycleEvent.query.filter_by(request_id=self.request_id, event_type="AUTHORIZATION_ISSUED").one()
        self.assertIn(str(result.authorization_id), event.safe_detail)
        self.assertEqual(AccountPurgeApprovalService.inspect_request(request_id=self.request_id).state, "APPROVED")

    def test_wrong_password_records_shared_throttle_without_authorization(self):
        self._assert_code(
            lambda: AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.executor.id, "wrong"),
            "REAUTH_FAILED",
        )
        self.assertEqual(AccountPurgeExecutionAuthorization.query.count(), 0)
        throttle = db.session.query(WorkspacePurgeReauthActorThrottle).filter_by(actor_user_id=self.executor.id).one()
        self.assertEqual(throttle.failed_attempt_count, 1)

    def test_lockout_and_actor_guards_fail_closed(self):
        for _ in range(5):
            with self.assertRaises(AccountPurgeReauthError):
                AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.executor.id, "wrong")
        self._assert_code(
            lambda: AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.executor.id, "StrongPassword123!"),
            "REAUTH_THROTTLED",
        )
        self._assert_code(
            lambda: AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.requester.id, "StrongPassword123!"),
            "REQUESTER_EXECUTOR_CONFLICT",
        )

        self._assert_code(
            lambda: AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.approver.id, "StrongPassword123!"),
            "APPROVER_EXECUTOR_CONFLICT",
        )
        self._assert_code(
            lambda: AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.target.id, "StrongPassword123!"),
            "TARGET_EXECUTOR_CONFLICT",
        )
        self._assert_code(
            lambda: AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.unauthorized.id, "StrongPassword123!"),
            "EXECUTOR_NOT_AUTHORIZED",
        )

    def test_active_authorization_blocks_duplicate_and_inspection_is_safe(self):
        result = AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.executor.id, "StrongPassword123!")
        self._assert_code(
            lambda: AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.executor.id, "StrongPassword123!"),
            "ACTIVE_AUTHORIZATION_EXISTS",
        )
        summary = AccountPurgeReauthService.inspect_authorization(self.request_id, self.executor.id)
        self.assertEqual(summary.authorization_id, result.authorization_id)
        self.assertNotIn("nonce_hash", repr(summary))
        self.assertNotIn(result.raw_nonce, repr(summary))

    def test_timestamp_normalization_is_utc_and_boundary_is_expired(self):
        aware = datetime(2026, 2, 1, tzinfo=timezone.utc)
        naive = datetime(2026, 2, 1)
        self.assertEqual(AccountPurgeReauthService._normalize_utc(aware), aware)
        self.assertEqual(AccountPurgeReauthService._normalize_utc(naive), aware)
        authorization = AccountPurgeExecutionAuthorization(
            request_id=self.request_id, actor_user_id=self.executor.id, method="local_password",
            generation=1, state="ACTIVE", authenticated_at=naive, expires_at=naive,
        )
        summary = AccountPurgeReauthService._summary(authorization, aware)
        self.assertTrue(summary.expired)

    def test_expired_authorization_reissues_with_new_generation_and_old_nonce_fails(self):
        first = AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.executor.id, "StrongPassword123!")
        authorization = db.session.get(AccountPurgeExecutionAuthorization, first.authorization_id)
        authorization.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        second = AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.executor.id, "StrongPassword123!")
        self.assertEqual(second.generation, first.generation + 1)
        self._assert_code(
            lambda: AccountPurgeReauthService.claim_authorization(self.request_id, self.executor.id, first.raw_nonce, first.generation),
            "AUTHORIZATION_VERSION_CONFLICT",
        )

    def test_claim_is_single_use_and_clears_nonce(self):
        issued = AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.executor.id, "StrongPassword123!")
        claimed = AccountPurgeReauthService.claim_authorization(self.request_id, self.executor.id, issued.raw_nonce, issued.generation)
        self.assertEqual(claimed.state, "CLAIMED")
        self.assertEqual(claimed.generation, issued.generation + 1)
        authorization = db.session.get(AccountPurgeExecutionAuthorization, issued.authorization_id)
        self.assertIsNone(authorization.nonce_hash)
        event = AccountPurgeLifecycleEvent.query.filter_by(request_id=self.request_id, event_type=EVENT_CLAIMED).one()
        detail = json.loads(event.safe_detail)
        self.assertEqual(detail["previous_generation"], issued.generation)
        self.assertEqual(detail["generation"], issued.generation + 1)
        with self.assertRaises(AccountPurgeReauthError) as raised:
            AccountPurgeReauthService.claim_authorization(self.request_id, self.executor.id, issued.raw_nonce, issued.generation)
        self.assertEqual(raised.exception.code, "AUTHORIZATION_VERSION_CONFLICT")
        with self.assertRaises(AccountPurgeReauthError) as raised:
            AccountPurgeReauthService.claim_authorization(self.request_id, self.executor.id, issued.raw_nonce, claimed.generation)
        self.assertEqual(raised.exception.code, "AUTHORIZATION_ALREADY_CLAIMED")

    def test_revoke_is_atomic_and_records_actor_generation_reason(self):
        issued = AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.executor.id, "StrongPassword123!")
        result = AccountPurgeReauthService.revoke_authorization(
            self.request_id, self.approver.id, "  security review  ", expected_generation=issued.generation
        )
        self.assertEqual(result.state, "REVOKED")
        self.assertEqual(result.generation, issued.generation + 1)
        event = AccountPurgeLifecycleEvent.query.filter_by(request_id=self.request_id, event_type=EVENT_REVOKED).one()
        self.assertEqual(event.actor_id, self.approver.id)
        self.assertIn(str(issued.authorization_id), event.safe_detail)
        self.assertIn("security review", event.safe_detail)
        detail = json.loads(event.safe_detail)
        self.assertEqual(detail["previous_generation"], issued.generation)
        self.assertEqual(detail["generation"], issued.generation + 1)
        self.assertIsNone(db.session.get(AccountPurgeExecutionAuthorization, issued.authorization_id).nonce_hash)

    def test_claim_and_revoke_guards_and_lifecycle_failure_rollback(self):
        issued = AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.executor.id, "StrongPassword123!")
        self._assert_code(
            lambda: AccountPurgeReauthService.revoke_authorization(self.request_id, self.target.id, "reason"),
            "EXECUTOR_NOT_AUTHORIZED",
        )
        with patch.object(AccountPurgeReauthService, "_add_event", side_effect=SQLAlchemyError("event failure")):
            self._assert_code(
                lambda: AccountPurgeReauthService.revoke_authorization(self.request_id, self.approver.id, "reason", expected_generation=issued.generation),
                "PERSISTENCE_FAILURE",
            )
        authorization = db.session.get(AccountPurgeExecutionAuthorization, issued.authorization_id)
        self.assertEqual(authorization.state, "ACTIVE")
        self.assertEqual(authorization.generation, issued.generation)

    def test_state_helpers_do_not_execute_or_mutate_target(self):
        issued = AccountPurgeReauthService.reauthenticate_and_issue(self.request_id, self.executor.id, "StrongPassword123!")
        claimed = AccountPurgeReauthService.claim_authorization(self.request_id, self.executor.id, issued.raw_nonce, issued.generation)
        started = AccountPurgeReauthService.mark_service_started(self.request_id, self.executor.id, claimed.generation)
        unresolved = AccountPurgeReauthService.mark_claimed_unresolved(self.request_id, self.executor.id, "crash boundary", started.generation)
        self.assertEqual(unresolved.state, "CLAIMED_UNRESOLVED")
        self.assertEqual(claimed.generation, issued.generation + 1)
        self.assertEqual(started.generation, claimed.generation + 1)
        self.assertEqual(unresolved.generation, started.generation + 1)
        target = db.session.get(User, self.target.id)
        self.assertEqual(target.account_purge_state, "NOT_PURGED")
        self.assertIsNone(target.account_purged_at)
        self.assertEqual(db.session.get(AccountPurgeExecutionAuthorization, issued.authorization_id).state, "CLAIMED_UNRESOLVED")


if __name__ == "__main__":
    unittest.main()
