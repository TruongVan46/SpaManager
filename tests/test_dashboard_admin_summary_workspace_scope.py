import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_dashboard_admin_summary_scope.sqlite"
if TEST_DB_FILE.exists():
    TEST_DB_FILE.unlink()

os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"

from flask import session

from app import app
from extensions import db
from models.activity_log import ActivityLog
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from routes.dashboard import _build_admin_summary
from utils.timezone_utils import utc_now


class DashboardAdminSummaryWorkspaceScopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        cls.app_context.pop()
        if TEST_DB_FILE.exists():
            TEST_DB_FILE.unlink()

    def setUp(self):
        db.session.rollback()
        ActivityLog.query.delete()
        WorkspaceMember.query.delete()
        Workspace.query.delete()
        User.query.delete()
        db.session.commit()

        self.workspace_a = Workspace(name="Dashboard A", slug="dashboard-a", status="active")
        self.workspace_b = Workspace(name="Dashboard B", slug="dashboard-b", status="active")
        self.manager = self._user("dashboard-manager", "OWNER", True)
        self.user_a = self._user("dashboard-a-user", "STAFF", False)
        self.user_b = self._user("dashboard-b-user", "STAFF", True)
        self.removed_user = self._user("dashboard-removed", "STAFF", True)
        self.stale_removed_user = self._user("dashboard-stale-removed", "STAFF", True)
        self.invited_user = self._user("dashboard-invited", "STAFF", True)
        self.deleted_user = self._user("dashboard-deleted", "STAFF", True)
        db.session.add_all([self.workspace_a, self.workspace_b])
        db.session.add_all([
            self.manager,
            self.user_a,
            self.user_b,
            self.removed_user,
            self.stale_removed_user,
            self.invited_user,
            self.deleted_user,
        ])
        db.session.flush()
        db.session.add_all([
            WorkspaceMember(workspace=self.workspace_a, user=self.manager, role="owner", status="active"),
            WorkspaceMember(workspace=self.workspace_b, user=self.manager, role="owner", status="active"),
            WorkspaceMember(workspace=self.workspace_a, user=self.user_a, role="staff", status="active"),
            WorkspaceMember(workspace=self.workspace_b, user=self.user_b, role="staff", status="active"),
            WorkspaceMember(workspace=self.workspace_a, user=self.removed_user, role="staff", status="removed"),
            WorkspaceMember(workspace=self.workspace_a, user=self.stale_removed_user, role="staff", status="active", removed_at=utc_now()),
            WorkspaceMember(workspace=self.workspace_a, user=self.invited_user, role="staff", status="invited"),
            WorkspaceMember(workspace=self.workspace_a, user=self.deleted_user, role="staff", status="active"),
        ])
        self.deleted_user.deleted_at = utc_now()
        now = utc_now()
        self.a_time = now - timedelta(hours=2)
        self.b_time = now - timedelta(hours=1)
        db.session.add_all([
            ActivityLog(workspace_id=self.workspace_a.id, created_at=self.a_time, module="A", action="WARN", description="A warning", severity="WARNING"),
            ActivityLog(workspace_id=self.workspace_b.id, created_at=self.b_time - timedelta(minutes=2), module="B", action="WARN", description="B warning 1", severity="WARNING"),
            ActivityLog(workspace_id=self.workspace_b.id, created_at=self.b_time - timedelta(minutes=1), module="B", action="ERROR", description="B error", severity="ERROR"),
            ActivityLog(workspace_id=self.workspace_b.id, created_at=self.b_time, module="B", action="WARN", description="B warning 2", severity="WARNING"),
            ActivityLog(workspace_id=None, created_at=now, module="GLOBAL", action="WARN", description="Global warning", severity="WARNING"),
            ActivityLog(workspace_id=self.workspace_a.id, created_at=now - timedelta(days=8), module="A", action="WARN", description="Old warning", severity="WARNING"),
            ActivityLog(workspace_id=self.workspace_a.id, created_at=now, module="A", action="INFO", description="Informational event", severity="INFO"),
        ])
        db.session.commit()
        self.request_context = app.test_request_context()
        self.request_context.push()
        session["auth_user_id"] = self.manager.id
        session["user_id"] = self.manager.id
        session["_enable_workspace_isolation"] = True

    def tearDown(self):
        self.request_context.pop()
        db.session.rollback()

    @staticmethod
    def _user(username, role, is_active):
        user = User(username=username, full_name=username, email=f"{username}@example.test", role=role, is_active=is_active, approval_status="active")
        user.set_password("Password123!")
        return user

    def _summary_for(self, workspace_id):
        session["current_workspace_id"] = workspace_id
        summary = _build_admin_summary()
        self.assertIsNotNone(summary)
        return summary

    def test_workspace_a_metrics_are_scoped_and_preserve_user_semantics(self):
        summary = self._summary_for(self.workspace_a.id)
        self.assertEqual(summary["users"], {"active": 1, "inactive": 1, "total": 2})
        self.assertEqual(summary["activity"]["warning_count"], 1)
        self.assertEqual(summary["activity"]["error_count"], 0)
        self.assertIsNotNone(summary["activity"]["latest_time"])

    def test_workspace_b_metrics_change_with_current_workspace(self):
        summary_a = self._summary_for(self.workspace_a.id)
        summary_b = self._summary_for(self.workspace_b.id)
        self.assertEqual(summary_b["users"], {"active": 2, "inactive": 0, "total": 2})
        self.assertEqual(summary_b["activity"]["warning_count"], 2)
        self.assertEqual(summary_b["activity"]["error_count"], 1)
        self.assertNotEqual(summary_a["activity"]["latest_time"], summary_b["activity"]["latest_time"])

    def test_invalid_workspace_fails_closed_without_global_statistics(self):
        session["current_workspace_id"] = 999999
        self.assertIsNone(_build_admin_summary())
        self.assertNotIn("current_workspace_id", session)

    def test_no_alerts_returns_zero_and_no_latest_time(self):
        session["current_workspace_id"] = self.workspace_a.id
        ActivityLog.query.filter(ActivityLog.workspace_id == self.workspace_a.id).delete()
        db.session.commit()
        summary = _build_admin_summary()
        self.assertEqual(summary["activity"]["warning_count"], 0)
        self.assertEqual(summary["activity"]["error_count"], 0)
        self.assertIsNone(summary["activity"]["latest_time"])

    def test_dashboard_query_string_cannot_override_current_workspace(self):
        client = app.test_client()
        with client.session_transaction() as client_session:
            client_session["auth_user_id"] = self.manager.id
            client_session["user_id"] = self.manager.id
            client_session["current_workspace_id"] = self.workspace_a.id
            client_session["_enable_workspace_isolation"] = True

        response = client.get("/api/dashboard/data?workspace_id=%s" % self.workspace_b.id)
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["admin_summary"]["users"], {"active": 1, "inactive": 1, "total": 2})
        self.assertEqual(payload["admin_summary"]["activity"]["warning_count"], 1)
