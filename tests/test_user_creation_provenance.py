import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_DB = Path(tempfile.gettempdir()) / "spamanager_user_creation_provenance.sqlite"
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"

from flask import session
from sqlalchemy.exc import SQLAlchemyError

from app import app
from core.exceptions import BusinessException, PermissionDeniedException, ValidationException
from extensions import db
from models.account_purge import UserCreationProvenance
from models.activity_log import ActivityLog
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from services.account_purge_service import AccountPurgeService
from services.user_service import UserService


class UserCreationProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context()
        cls.context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        if TEST_DB.exists():
            TEST_DB.unlink()
        cls.context.pop()

    def setUp(self):
        db.session.rollback()
        db.drop_all()
        db.create_all()
        self.workspace = Workspace(name="Managed", slug="managed-provenance", status="active")
        db.session.add(self.workspace)
        db.session.flush()
        self.owner = self._user("owner", "OWNER")
        self._membership(self.owner, "owner")
        self.admin = self._user("admin", "ADMIN")
        self._membership(self.admin, "admin")
        self.staff = self._user("staff", "STAFF")
        self._membership(self.staff, "staff")
        db.session.commit()

    def _user(self, username, role, *, is_active=True):
        user = User(
            username=username,
            email=f"{username}@example.test",
            full_name=username.title(),
            role=role,
            is_active=is_active,
            approval_status=User.APPROVAL_ACTIVE,
        )
        user.set_password("StrongPassword123!")
        db.session.add(user)
        db.session.flush()
        return user

    def _membership(self, user, role, status="active"):
        membership = WorkspaceMember(
            workspace_id=self.workspace.id,
            user_id=user.id,
            role=role,
            status=status,
        )
        db.session.add(membership)
        db.session.flush()
        return membership

    def _create(self, actor, username, role):
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = actor.id
            session["user_id"] = actor.id
            return UserService.create_user(
                actor=actor,
                username=username,
                full_name=username.title(),
                password="StrongPassword123!",
                email=f"{username}@example.test",
                role=role,
            )

    def test_owner_staff_and_admin_provenance_are_authoritative(self):
        staff = self._create(self.owner, "created_staff", "staff")
        admin = self._create(self.owner, "created_admin", "ADMIN")

        records = UserCreationProvenance.query.filter(
            UserCreationProvenance.user_id.in_([staff.id, admin.id])
        ).order_by(UserCreationProvenance.user_id).all()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].created_by_user_id, self.owner.id)
        self.assertEqual(records[0].created_in_workspace_id, self.workspace.id)
        self.assertEqual(records[0].creation_source, "WORKSPACE_OWNER")
        self.assertEqual(records[0].created_role, "STAFF")
        self.assertEqual(records[0].provenance_version, 1)
        self.assertEqual(records[1].created_role, "ADMIN")

    def test_admin_can_create_staff_with_admin_source_but_not_admin(self):
        created = self._create(self.admin, "admin_created_staff", "STAFF")
        provenance = UserCreationProvenance.query.filter_by(user_id=created.id).one()
        self.assertEqual(provenance.creation_source, "WORKSPACE_ADMIN")
        with self.assertRaises(ValidationException):
            self._create(self.admin, "admin_created_admin", "ADMIN")

    def test_unauthorized_creator_and_inconsistent_membership_fail_closed(self):
        with self.assertRaises(PermissionDeniedException):
            self._create(self.staff, "staff_created", "STAFF")

        self.admin.role = "OWNER"
        db.session.commit()
        with self.assertRaises(PermissionDeniedException):
            self._create(self.admin, "inconsistent_created", "STAFF")
        self.assertEqual(User.query.filter_by(username="inconsistent_created").count(), 0)

    def test_provenance_failure_rolls_back_everything(self):
        before_logs = ActivityLog.query.count()
        original_flush = db.session.flush
        calls = {"count": 0}

        def fail_on_provenance_flush(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 3:
                raise SQLAlchemyError("simulated provenance failure")
            return original_flush(*args, **kwargs)

        with patch.object(db.session, "flush", side_effect=fail_on_provenance_flush):
            with self.assertRaises(BusinessException) as raised:
                self._create(self.owner, "rollback_target", "STAFF")
        self.assertEqual(getattr(raised.exception, "code", None), "PROVENANCE_PERSISTENCE_ERROR")
        self.assertIsNone(User.query.filter_by(username="rollback_target").first())
        self.assertEqual(WorkspaceMember.query.filter_by(workspace_id=self.workspace.id).count(), 3)
        self.assertEqual(UserCreationProvenance.query.count(), 0)
        self.assertEqual(ActivityLog.query.count(), before_logs)

    def test_soft_delete_preserves_provenance_and_account_purge_becomes_eligible(self):
        target = self._create(self.owner, "purge_target", "STAFF")
        provenance_before = UserCreationProvenance.query.filter_by(user_id=target.id).one()
        with app.test_request_context():
            session["current_workspace_id"] = self.workspace.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.owner.id
            session["user_id"] = self.owner.id
            UserService.soft_delete_user(self.owner, target.id, reason="retired")

        with app.test_request_context():
            session["current_workspace_id"] = self.workspace.id
            session["_enable_workspace_isolation"] = True
            removed = UserService.search_removed_paginated(page=1, per_page=25)
        self.assertIn(target.id, [user.id for user in removed.items])
        result = AccountPurgeService.inspect_eligibility(
            requester_id=self.owner.id,
            target_user_id=target.id,
            managing_workspace_id=self.workspace.id,
        )
        self.assertTrue(result.eligible)
        self.assertEqual(result.reason_code, "ELIGIBLE")
        self.assertEqual(UserCreationProvenance.query.filter_by(user_id=target.id).one().id, provenance_before.id)

        with app.test_request_context():
            session["current_workspace_id"] = self.workspace.id
            session["_enable_workspace_isolation"] = True
            session["auth_user_id"] = self.owner.id
            session["user_id"] = self.owner.id
            UserService.restore_user(self.owner, target.id)
        provenance_after = UserCreationProvenance.query.filter_by(user_id=target.id).one()
        self.assertEqual(provenance_after.created_role, "STAFF")
        self.assertEqual(provenance_after.id, provenance_before.id)


if __name__ == "__main__":
    unittest.main()
