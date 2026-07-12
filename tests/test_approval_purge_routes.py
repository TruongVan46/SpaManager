import os
import unittest

os.environ["APP_ENV"] = "testing"
os.environ.setdefault("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ["SPAMANAGER_TEST_PROCESS"] = "1"

from app import app


class ApprovalPurgeRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.previous_flag = app.config.get("PERMANENT_PURGE_UI_ENABLED")

    def tearDown(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = self.previous_flag

    def test_flag_disabled_returns_not_found_before_auth_or_query(self):
        for value in (None, False, "", "false", "malformed"):
            with self.subTest(value=value):
                if value is None:
                    app.config.pop("PERMANENT_PURGE_UI_ENABLED", None)
                else:
                    app.config["PERMANENT_PURGE_UI_ENABLED"] = value
                self.assertEqual(self.client.get("/approval/purge-requests").status_code, 404)
                self.assertEqual(self.client.post("/approval/workspaces/1/purge-request").status_code, 404)

    def test_true_flag_reaches_auth_guard(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        response = self.client.get("/approval/purge-requests")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_url_map_has_no_execute_or_confirmation_route(self):
        routes = [rule.rule.lower() for rule in app.url_map.iter_rules()]
        self.assertFalse(any("purge" in route and ("execute" in route or "confirm" in route) for route in routes))

    def test_approval_route_does_not_reference_internal_execution_service(self):
        with open("routes/approval.py", encoding="utf-8") as source:
            self.assertNotIn("execute_workspace_purge", source.read())

    def test_detail_template_uses_id_matrix_and_read_only_guards(self):
        with open("templates/approval/purge_request_detail.html", encoding="utf-8") as source:
            template = source.read()
        self.assertIn("summary.requested_by_id == current_user.id", template)
        self.assertIn("summary.requested_by_id != current_user.id", template)
        self.assertIn("not summary.outcome_unknown", template)
        self.assertIn("summary.manifest_valid", template)
        self.assertNotIn("url_for('approval.execute", template)
        self.assertNotIn("url_for('approval.retry", template)
        self.assertNotIn("url_for('approval.reconcile", template)


if __name__ == "__main__":
    unittest.main()
