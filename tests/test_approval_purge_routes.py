import os
import unittest
from types import SimpleNamespace
from unittest.mock import DEFAULT, patch

os.environ["APP_ENV"] = "testing"
os.environ.setdefault("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ["SPAMANAGER_TEST_PROCESS"] = "1"

from app import app
from config import _parse_bool_env, is_permanent_purge_ui_enabled


class ApprovalPurgeRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.previous_flag = app.config.get("PERMANENT_PURGE_UI_ENABLED")
        self.previous_csrf = app.config.get("CSRF_ENABLED")
        app.config["CSRF_ENABLED"] = True

    def tearDown(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = self.previous_flag
        app.config["CSRF_ENABLED"] = self.previous_csrf

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

    def test_feature_flag_parser_and_runtime_guard_are_strict(self):
        for value in ("1", "true", "yes", "on", "y", "t", " TRUE ", " YeS "):
            with self.subTest(value=value):
                self.assertTrue(_parse_bool_env(value, False))
        for value in (None, "", "0", "false", "off", "no", "random"):
            with self.subTest(value=value):
                self.assertFalse(_parse_bool_env(value, False))
                self.assertFalse(is_permanent_purge_ui_enabled(value))
        self.assertTrue(is_permanent_purge_ui_enabled(True))
        self.assertFalse(is_permanent_purge_ui_enabled("true"))
        self.assertFalse(is_permanent_purge_ui_enabled(1))

    def test_disabled_flag_blocks_every_purge_endpoint_before_service(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = False
        with patch.multiple(
            "routes.approval.PurgeRequestService",
            list_summaries=DEFAULT,
            get_summary=DEFAULT,
            create_purge_request=DEFAULT,
            approve_purge_request=DEFAULT,
            reject_purge_request=DEFAULT,
            cancel_purge_request=DEFAULT,
        ) as mocks:
            requests = (
                ("GET", "/approval/purge-requests"),
                ("GET", "/approval/purge-requests/1"),
                ("POST", "/approval/workspaces/1/purge-request"),
                ("POST", "/approval/purge-requests/1/approve"),
                ("POST", "/approval/purge-requests/1/reject"),
                ("POST", "/approval/purge-requests/1/cancel"),
            )
            for method, path in requests:
                with self.subTest(method=method, path=path):
                    response = self.client.open(path, method=method)
                    self.assertEqual(response.status_code, 404)
            for mock in mocks.values():
                mock.assert_not_called()

    def test_navigation_and_account_actions_use_strict_boolean_template_guards(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = False
        with open("templates/layout/approval_base.html", encoding="utf-8") as source:
            layout = source.read()
        with open("templates/approval/accounts.html", encoding="utf-8") as source:
            accounts = source.read()
        self.assertIn("PERMANENT_PURGE_UI_ENABLED", layout)
        self.assertIn("PERMANENT_PURGE_UI_ENABLED", accounts)
        self.assertIn("sameas true", layout)
        self.assertIn("sameas true", accounts)

    def test_all_purge_post_routes_require_auth_and_authenticated_csrf(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        route_specs = (
            ("/approval/workspaces/1/purge-request", "create_purge_request", {"confirmation_phrase": "REQUEST PURGE demo-slug"}, {"workspace_id": 1, "requester_user_id": 42, "confirmation_phrase": "REQUEST PURGE demo-slug"}),
            ("/approval/purge-requests/1/approve", "approve_purge_request", {"confirmation_phrase": "APPROVE PURGE demo-slug lifecycle"}, {"request_id": 1, "approver_user_id": 42, "confirmation_phrase": "APPROVE PURGE demo-slug lifecycle"}),
            ("/approval/purge-requests/1/reject", "reject_purge_request", {"reason": "Rejected"}, {"request_id": 1, "rejector_user_id": 42, "reason": "Rejected"}),
            ("/approval/purge-requests/1/cancel", "cancel_purge_request", {"reason": "Cancelled"}, {"request_id": 1, "requester_user_id": 42, "reason": "Cancelled"}),
        )
        service_names = ("create_purge_request", "approve_purge_request", "reject_purge_request", "cancel_purge_request")

        actor = SimpleNamespace(
            id=42, full_name="Approval Owner", role="APPROVAL_OWNER", is_active=True, deleted_at=None,
            approval_status="active", can_access_app=True,
        )

        # Phase A: authentication rejects before any workflow service call.
        with patch.multiple(
            "routes.approval.PurgeRequestService",
            create_purge_request=DEFAULT,
            approve_purge_request=DEFAULT,
            reject_purge_request=DEFAULT,
            cancel_purge_request=DEFAULT,
        ) as mocks:
            for path, _method, data, _expected in route_specs:
                with self.subTest(phase="unauthenticated", path=path):
                    response = app.test_client().post(path, data=data)
                    self.assertEqual(response.status_code, 302)
                    self.assertIn("/login", response.headers["Location"])
            for mock in mocks.values():
                mock.assert_not_called()

        # Phase B: an authenticated active Approval Owner is rejected by CSRF.
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch.multiple(
            "routes.approval.PurgeRequestService",
            create_purge_request=DEFAULT,
            approve_purge_request=DEFAULT,
            reject_purge_request=DEFAULT,
            cancel_purge_request=DEFAULT,
        ) as mocks:
            for path, _method, data, _expected in route_specs:
                with self.subTest(phase="missing_csrf", path=path):
                    response = self.client.post(path, data=data)
                    self.assertEqual(response.status_code, 400)
                    for mock in mocks.values():
                        mock.assert_not_called()
                for mock in mocks.values():
                    mock.reset_mock()
                with self.subTest(phase="invalid_csrf", path=path):
                    response = self.client.post(path, data={**data, "csrf_token": "invalid-token"})
                    self.assertEqual(response.status_code, 400)
                    for mock in mocks.values():
                        mock.assert_not_called()
                for mock in mocks.values():
                    mock.reset_mock()

        # Phase C: valid CSRF reaches exactly the corresponding service method.
        valid_client = app.test_client()
        valid_client.get("/login")
        with valid_client.session_transaction() as session_data:
            csrf_token = session_data.get("_csrf_token")
        self.assertTrue(csrf_token)
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch.multiple(
            "routes.approval.PurgeRequestService",
            create_purge_request=DEFAULT,
            approve_purge_request=DEFAULT,
            reject_purge_request=DEFAULT,
            cancel_purge_request=DEFAULT,
        ) as mocks:
            for mock in mocks.values():
                mock.return_value = SimpleNamespace(id=1)
            for path, method_name, data, expected_call in route_specs:
                with self.subTest(phase="valid_csrf", path=path):
                    for mock in mocks.values():
                        mock.reset_mock()
                    response = valid_client.post(path, data={**data, "csrf_token": csrf_token})
                    self.assertEqual(response.status_code, 302)
                    mocks[method_name].assert_called_once_with(**expected_call)
                    for name in service_names:
                        if name != method_name:
                            mocks[name].assert_not_called()

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

    def test_staged_templates_render_csrf_labels_and_no_execution_controls(self):
        with open("templates/approval/purge_requests.html", encoding="utf-8") as source:
            listing = source.read()
        with open("templates/approval/purge_request_detail.html", encoding="utf-8") as source:
            detail = source.read()
        for template in (listing, detail):
            self.assertIn("csrf_token()", template)
            self.assertIn("<label", template)
            self.assertNotIn("execute_workspace_purge", template)
            self.assertNotIn("url_for('approval.execute", template)
        self.assertIn('autocomplete="off"', listing)
        self.assertIn('autocomplete="off"', detail)
        self.assertIn("role=\"alert\"", detail)


if __name__ == "__main__":
    unittest.main()
