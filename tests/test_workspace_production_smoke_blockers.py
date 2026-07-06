import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Setup unique database file for smoke tests to avoid lock issues
TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_blockers_smoke_test.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_media_blockers_test"

if TEST_DB_FILE.exists():
    try:
        TEST_DB_FILE.unlink()
    except Exception:
        pass
if TEST_MEDIA_ROOT.exists():
    shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["PERSISTENT_ROOT"] = TEST_MEDIA_ROOT.as_posix()
os.environ["UPLOAD_ROOT"] = (TEST_MEDIA_ROOT / "uploads").as_posix()
os.environ["LOGO_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "logos").as_posix()
os.environ["AVATAR_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "avatars").as_posix()

from app import app
from extensions import db
from models.user import User
from models.workspace import Workspace, WorkspaceMember
from models.customer import Customer
from models.activity_log import ActivityLog
from services.customer_service import CustomerService
from services.recycle_bin_service import RecycleBinService
from services.activity_log_service import ActivityLogService
from services.auth_service import AuthService
from core.exceptions import NotFoundException
from flask import session

class TestWorkspaceProductionSmokeBlockers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_context = app.app_context()
        cls.app_context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        if TEST_DB_FILE.exists():
            try:
                TEST_DB_FILE.unlink()
            except Exception:
                pass
        if TEST_MEDIA_ROOT.exists():
            shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        cls.app_context.pop()

    def setUp(self):
        db.session.rollback()
        # Clear tables
        ActivityLog.query.delete()
        WorkspaceMember.query.delete()
        Customer.query.delete()
        User.query.delete()
        Workspace.query.delete()
        db.session.commit()
        
        self.client = app.test_client()

    def tearDown(self):
        db.session.rollback()
        ActivityLog.query.delete()
        WorkspaceMember.query.delete()
        Customer.query.delete()
        User.query.delete()
        Workspace.query.delete()
        db.session.commit()

    def _create_workspace_and_owner(self, slug):
        workspace = Workspace(name=f"Workspace {slug}", slug=slug, status="active")
        db.session.add(workspace)
        db.session.flush()

        owner = User(username=f"owner_{slug}", email=f"owner_{slug}@test.com", role="OWNER", full_name="Owner")
        owner.set_password("Password123!")
        db.session.add(owner)
        db.session.flush()

        member = WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner", status="active")
        db.session.add(member)
        db.session.commit()
        return workspace, owner

    def login_as(self, user, workspace_id):
        from core.auth.constants import AUTH_SESSION_KEY
        with self.client.session_transaction() as sess:
            sess[AUTH_SESSION_KEY] = user.id
            sess["current_workspace_id"] = workspace_id
            sess["_enable_workspace_isolation"] = True

    def test_customer_delete_works_in_workspace(self):
        ws, owner = self._create_workspace_and_owner("ws-a")
        
        # Create customer in workspace A
        customer = Customer(name="Customer A", phone="0901234567", email="a@test.com", workspace_id=ws.id)
        db.session.add(customer)
        db.session.commit()

        self.login_as(owner, ws.id)

        # 1. Test GET can-delete route with AJAX headers
        resp = self.client.get(
            f"/customers/{customer.id}/can-delete",
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["can_delete"])

        # 2. Get CSRF Token from index page
        resp_index = self.client.get("/customers")
        import re
        match = re.search(r'name="csrf-token" content="([^"]+)"', resp_index.get_data(as_text=True))
        csrf_token = match.group(1) if match else ""

        # 3. Test POST delete route with AJAX headers
        resp = self.client.post(
            f"/customers/{customer.id}/delete",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": csrf_token
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["message"], "Đã xóa khách hàng thành công.")

        # 4. Verify soft deleted
        deleted_cust = Customer.query.get(customer.id)
        self.assertIsNotNone(deleted_cust.deleted_at)
        self.assertEqual(deleted_cust.deleted_by, owner.username)

    def test_cross_workspace_customer_delete_blocked(self):
        ws_a, owner_a = self._create_workspace_and_owner("ws-a")
        ws_b, owner_b = self._create_workspace_and_owner("ws-b")

        # Customer A in Workspace A
        customer_a = Customer(name="Cust A", workspace_id=ws_a.id)
        db.session.add(customer_a)
        db.session.commit()

        # Login as B, try to get info or delete A
        self.login_as(owner_b, ws_b.id)

        # GET can-delete -> should raise 404 (NotFoundException) and return JSON
        resp = self.client.get(
            f"/customers/{customer_a.id}/can-delete",
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        print("GET can-delete status:", resp.status_code)
        print("GET can-delete data:", resp.get_data(as_text=True))
        self.assertEqual(resp.status_code, 404)

        # Get CSRF Token from index page
        resp_index = self.client.get("/customers")
        import re
        match = re.search(r'name="csrf-token" content="([^"]+)"', resp_index.get_data(as_text=True))
        csrf_token = match.group(1) if match else ""

        # POST delete -> should also 404
        resp = self.client.post(
            f"/customers/{customer_a.id}/delete",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": csrf_token
            }
        )
        print("POST delete status:", resp.status_code)
        print("POST delete data:", resp.get_data(as_text=True))
        self.assertEqual(resp.status_code, 404)

        # Verify customer A remains unaffected
        db.session.expire_all()
        cust_a_db = Customer.query.get(customer_a.id)
        self.assertIsNone(cust_a_db.deleted_at)

    def test_trash_scoped_to_workspace(self):
        ws_a, owner_a = self._create_workspace_and_owner("ws-a")
        ws_b, owner_b = self._create_workspace_and_owner("ws-b")

        # Soft-deleted items
        from utils.timezone_utils import utc_now
        cust_a = Customer(name="Cust A", workspace_id=ws_a.id, deleted_at=utc_now(), deleted_by="owner_ws-a")
        cust_b = Customer(name="Cust B", workspace_id=ws_b.id, deleted_at=utc_now(), deleted_by="owner_ws-b")
        db.session.add_all([cust_a, cust_b])
        db.session.commit()

        # Context A
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = ws_a.id
            session["auth_user_id"] = owner_a.id

            stats = RecycleBinService.get_statistics()
            self.assertEqual(stats["total"], 1)
            self.assertEqual(stats["customer"], 1)

            items = RecycleBinService.get_deleted_items().items
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], cust_a.id)

            # Restoring B from A should fail (NotFoundException)
            with self.assertRaises(NotFoundException):
                CustomerService.restore(cust_b.id, actor=owner_a.username)

        # Context B
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = ws_b.id
            session["auth_user_id"] = owner_b.id

            stats = RecycleBinService.get_statistics()
            self.assertEqual(stats["total"], 1)
            self.assertEqual(stats["customer"], 1)

            items = RecycleBinService.get_deleted_items().items
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], cust_b.id)

    def test_activity_log_scoped_to_workspace(self):
        ws_a, owner_a = self._create_workspace_and_owner("ws-a")
        ws_b, owner_b = self._create_workspace_and_owner("ws-b")

        # Create activity log entries
        log_a = ActivityLog(module="CUSTOMER", action="CREATE", description="Log A", user_id=owner_a.id)
        log_b = ActivityLog(module="CUSTOMER", action="CREATE", description="Log B", user_id=owner_b.id)
        db.session.add_all([log_a, log_b])
        db.session.commit()

        # Context A
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = ws_a.id
            session["auth_user_id"] = owner_a.id

            logs = ActivityLogService.get_filtered_logs().items
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].id, log_a.id)

            actors = ActivityLogService.get_actor_options()
            self.assertEqual(len(actors), 1)
            self.assertEqual(actors[0].id, owner_a.id)

        # Context B
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = ws_b.id
            session["auth_user_id"] = owner_b.id

            logs = ActivityLogService.get_filtered_logs().items
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].id, log_b.id)

    def test_no_current_workspace_fail_closed(self):
        # Without current_workspace_id
        with app.test_request_context():
            session["_enable_workspace_isolation"] = True
            session["current_workspace_id"] = None

            # Recycle Bin statistics & items empty
            stats = RecycleBinService.get_statistics()
            self.assertEqual(stats["total"], 0)
            self.assertEqual(len(RecycleBinService.get_deleted_items().items), 0)

            # Activity logs empty
            logs = ActivityLogService.get_filtered_logs().items
            self.assertEqual(len(logs), 0)
            self.assertEqual(len(ActivityLogService.get_actor_options()), 0)

if __name__ == "__main__":
    unittest.main()
