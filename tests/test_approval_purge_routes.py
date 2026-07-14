import os
import time
import unittest
from datetime import datetime, timedelta
import inspect
from types import SimpleNamespace
from unittest.mock import DEFAULT, patch

os.environ["APP_ENV"] = "testing"
os.environ.setdefault("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ["SPAMANAGER_TEST_PROCESS"] = "1"

from app import app
from config import _parse_bool_env, is_permanent_purge_ui_enabled
from services.purge_reauth_service import PurgeReauthIssuance, PurgeReauthRateLimitedError


class ApprovalPurgeRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.previous_flag = app.config.get("PERMANENT_PURGE_UI_ENABLED")
        self.previous_execution_flag = app.config.get("PERMANENT_PURGE_EXECUTION_ENABLED")
        self.previous_csrf = app.config.get("CSRF_ENABLED")
        app.config["CSRF_ENABLED"] = True

    def tearDown(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = self.previous_flag
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = self.previous_execution_flag
        app.config["CSRF_ENABLED"] = self.previous_csrf

    @staticmethod
    def _execution_summary():
        return SimpleNamespace(
            id=45,
            lifecycle_id="lifecycle-45",
            workspace_id=12,
            workspace_name="Target Workspace",
            workspace_slug="target-workspace",
            status="APPROVED",
            requested_by_snapshot="requester",
            requested_by_id=7,
            approved_by_snapshot="approver",
            approved_by_id=8,
            requested_at=None,
            eligible_at=None,
            approved_at=None,
            rejected_at=None,
            cancelled_at=None,
            invalidated_at=None,
            outcome_unknown=False,
            manifest_hash="a" * 64,
            destructive_counts={"customers": 1},
            preserved=["users", "activity_logs"],
            external_assets=[],
            hold_check_status="CLEAR",
            failure_code=None,
            failure_summary=None,
            manifest_valid=True,
            manifest_error=None,
            retention_reached=True,
        )

    @staticmethod
    def _actor(actor_id=9, auth_provider="local"):
        return SimpleNamespace(
            id=actor_id, full_name="Approval Owner", role="APPROVAL_OWNER", is_active=True,
            deleted_at=None, approval_status="active", auth_provider=auth_provider,
            can_access_app=True,
        )

    @staticmethod
    def _set_transport(client, request_id=45, workspace_id=12, actor_id=9, generation=1, nonce="test-nonce"):
        now = datetime.utcnow()
        with client.session_transaction() as session_data:
            session_data["purge_reauth_transport_v1"] = {
                "version": 1,
                "authorization_id": 99,
                "purge_request_id": request_id,
                "workspace_id": workspace_id,
                "actor_user_id": actor_id,
                "generation": generation,
                "raw_nonce": nonce,
                "authenticated_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=4)).isoformat(),
            }

    def test_flag_disabled_returns_not_found_before_auth_or_query(self):
        for value in (None, False, "", "false", "malformed"):
            with self.subTest(value=value):
                if value is None:
                    app.config.pop("PERMANENT_PURGE_UI_ENABLED", None)
                else:
                    app.config["PERMANENT_PURGE_UI_ENABLED"] = value
                self.assertEqual(self.client.get("/approval/purge-requests").status_code, 404)
                self.assertEqual(self.client.post("/approval/workspaces/1/purge-request").status_code, 404)

    def test_legal_hold_routes_are_flagged_and_csrf_protected(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = False
        for path in (
            "/approval/purge-requests/1/legal-holds",
            "/approval/purge-requests/1/legal-holds/hold-1/release",
            "/approval/legal-holds/hold-1/release",
        ):
            with self.subTest(phase="disabled", path=path):
                self.assertEqual(self.client.post(path).status_code, 404)
        self.assertEqual(self.client.get("/approval/workspaces/1/legal-holds").status_code, 404)

        actor = SimpleNamespace(
            id=7, full_name="Approval Owner", role="APPROVAL_OWNER", is_active=True,
            deleted_at=None, approval_status="active", can_access_app=True,
        )
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        with patch("services.auth_service.AuthService.get_current_user", return_value=actor), \
             patch("services.auth_service.AuthService.get_current_active_user", return_value=actor):
            for path in (
                "/approval/purge-requests/1/legal-holds",
                "/approval/purge-requests/1/legal-holds/hold-1/release",
                "/approval/legal-holds/hold-1/release",
            ):
                with self.subTest(phase="csrf", path=path):
                    self.assertEqual(self.client.post(path).status_code, 400)

        with self.client.session_transaction() as session_data:
            session_data["_csrf_token"] = "csrf"
            session_data["_csrf_issued_at"] = int(time.time())
        summary = SimpleNamespace(workspace_id=12)
        with patch("services.auth_service.AuthService.get_current_user", return_value=actor), \
             patch("services.auth_service.AuthService.get_current_active_user", return_value=actor), \
             patch("routes.approval.PurgeRequestService.get_summary", return_value=summary), \
             patch("routes.approval.PurgeLegalHoldService.get_workspace_target", return_value={"id": 12, "name": "Target Workspace", "slug": "target-workspace", "deleted_at": datetime(2026, 1, 1), "purged": False}) as target, \
             patch("routes.approval.PurgeLegalHoldService.list_legal_holds", return_value=[]) as listing, \
             patch("routes.approval.PurgeLegalHoldService.create_legal_hold", return_value=SimpleNamespace(hold_id="hold-created")) as create, \
             patch("routes.approval.PurgeLegalHoldService.release_legal_hold", return_value=SimpleNamespace(hold_id="hold-created", workspace_id=12)) as release:
            response = self.client.get("/approval/workspaces/1/legal-holds")
            self.assertEqual(response.status_code, 200)
            target.assert_called_once_with(workspace_id=1, actor_user_id=7)
            listing.assert_called_once_with(workspace_id=1, actor_user_id=7)
            create.assert_not_called()
            release.assert_not_called()

            response = self.client.post(
                "/approval/workspaces/1/legal-holds",
                data={"csrf_token": "csrf", "hold_type": "LEGAL", "reason": "Preserve", "confirmation_phrase": "HOLD target-workspace"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(create.call_args.kwargs["workspace_id"], 1)
            self.assertNotIn("request_id", create.call_args.kwargs)

            response = self.client.post(
                "/approval/purge-requests/1/legal-holds",
                data={"csrf_token": "csrf", "hold_type": "LEGAL", "reason": "Preserve", "confirmation_phrase": "HOLD target"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(create.call_args.kwargs["workspace_id"], 12)
            response = self.client.post(
                "/approval/legal-holds/hold-created/release",
                data={"csrf_token": "csrf", "release_reason": "Resolved", "confirmation_phrase": "RELEASE hold-created"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertNotIn("expected_workspace_id", release.call_args.kwargs)

            response = self.client.post(
                "/approval/purge-requests/1/legal-holds/hold-created/release",
                data={"csrf_token": "csrf", "release_reason": "Resolved", "confirmation_phrase": "RELEASE hold-created"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(release.call_args.kwargs["expected_workspace_id"], 12)

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

    def test_url_map_has_separate_confirmation_get_and_execution_post_routes(self):
        route_methods = {
            rule.rule: rule.methods
            for rule in app.url_map.iter_rules()
            if "purge-requests" in rule.rule and ("execute" in rule.rule or "confirm" in rule.rule)
        }
        self.assertEqual(route_methods["/approval/purge-requests/<int:request_id>/execute/confirm"] & {"GET"}, {"GET"})
        self.assertEqual(route_methods["/approval/purge-requests/<int:request_id>/execute"] & {"POST"}, {"POST"})

    def test_approval_execution_route_calls_internal_execution_service(self):
        with open("routes/approval.py", encoding="utf-8") as source:
            self.assertIn("PurgeService.execute_workspace_purge", source.read())

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

    def test_execution_route_requires_both_feature_flags(self):
        actor = self._actor()
        for ui_enabled, execution_enabled in ((False, False), (True, False), (False, True)):
            with self.subTest(ui_enabled=ui_enabled, execution_enabled=execution_enabled):
                app.config["PERMANENT_PURGE_UI_ENABLED"] = ui_enabled
                app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = execution_enabled
                with patch("app.AuthService.get_current_user", return_value=actor), patch(
                    "routes.approval.AuthService.get_current_active_user", return_value=actor
                ), patch(
                    "routes.approval.PurgeRequestService.get_summary"
                ) as get_summary:
                    response = self.client.get("/approval/purge-requests/45/execute/confirm")
                self.assertEqual(response.status_code, 404)
                get_summary.assert_not_called()

        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch(
            "routes.approval.PurgeRequestService.get_summary", return_value=self._execution_summary()
        ), patch(
            "routes.approval.PurgeRequestService.get_workspace_target", return_value={"purged": False}
        ):
            response = self.client.get("/approval/purge-requests/45/execute/confirm")
        self.assertEqual(response.status_code, 200)
        self.assertIn("current_password", response.get_data(as_text=True))
        self.assertNotIn("PURGE WORKSPACE 12 REQUEST 45", response.get_data(as_text=True))

    def test_execution_flag_disabled_blocks_reauth_and_execute_before_services(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = False
        actor = self._actor()
        client = app.test_client()
        client.get("/login")
        with client.session_transaction() as session_data:
            csrf_token = session_data.get("_csrf_token")
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch("routes.approval.PurgeRequestService.get_summary") as get_summary, patch(
            "routes.approval.PurgeReauthService.issue_local_authorization"
        ) as issue, patch("routes.approval.PurgeService.execute_workspace_purge") as execute:
            reauth = client.post(
                "/approval/purge-requests/45/reauth",
                data={"csrf_token": csrf_token, "current_password": "Password123!"},
            )
            destructive = client.post(
                "/approval/purge-requests/45/execute",
                data={"csrf_token": csrf_token, "confirmation_phrase": "PURGE WORKSPACE 12 REQUEST 45"},
            )
        self.assertEqual(reauth.status_code, 404)
        self.assertEqual(destructive.status_code, 404)
        get_summary.assert_not_called()
        issue.assert_not_called()
        execute.assert_not_called()

    def test_execution_methods_are_strictly_confirmation_get_and_execution_post(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        self.assertEqual(self.client.post("/approval/purge-requests/45/execute/confirm").status_code, 405)
        self.assertEqual(self.client.get("/approval/purge-requests/45/execute").status_code, 405)

    def test_confirmation_get_requires_approval_owner_and_never_calls_execution_service(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        actor = self._actor()
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=None
        ), patch(
            "routes.approval.PurgeService.execute_workspace_purge"
        ) as execute:
            response = self.client.get("/approval/purge-requests/45/execute/confirm")
        self.assertEqual(response.status_code, 302)
        execute.assert_not_called()

    def test_requester_can_open_execution_flow_when_otherwise_eligible(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        actor = self._actor(actor_id=7)
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch(
            "routes.approval.PurgeRequestService.get_summary", return_value=self._execution_summary()
        ), patch(
            "routes.approval.PurgeRequestService.get_workspace_target", return_value={"purged": False}
        ):
            self.assertEqual(self.client.get("/approval/purge-requests/45/execute/confirm").status_code, 200)

    def test_approver_can_open_execution_flow_when_otherwise_eligible(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        actor = self._actor(actor_id=8)
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch(
            "routes.approval.PurgeRequestService.get_summary", return_value=self._execution_summary()
        ), patch(
            "routes.approval.PurgeRequestService.get_workspace_target", return_value={"purged": False}
        ), patch("routes.approval.PurgeService.execute_workspace_purge") as execute:
            self.assertEqual(self.client.get("/approval/purge-requests/45/execute/confirm").status_code, 200)
            execute.assert_not_called()

    def test_google_only_executor_cannot_open_or_submit_execution_flow(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        actor = self._actor(auth_provider="google")
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch(
            "routes.approval.PurgeRequestService.get_summary", return_value=self._execution_summary()
        ), patch(
            "routes.approval.PurgeRequestService.get_workspace_target", return_value={"purged": False}
        ), patch("routes.approval.PurgeService.execute_workspace_purge") as execute:
            self.assertEqual(self.client.get("/approval/purge-requests/45/execute/confirm").status_code, 403)
            execute.assert_not_called()

    def test_execution_post_requires_csrf_before_service_call(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        actor = self._actor()
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch(
            "routes.approval.PurgeRequestService.get_summary", return_value=self._execution_summary()
        ), patch(
            "routes.approval.PurgeRequestService.get_workspace_target", return_value={"purged": False}
        ), patch("routes.approval.PurgeService.execute_workspace_purge") as execute:
            response = self.client.post(
                "/approval/purge-requests/45/execute",
                data={"confirmation_phrase": "PURGE WORKSPACE 12 REQUEST 45"},
            )
        self.assertEqual(response.status_code, 400)
        execute.assert_not_called()

    def test_execution_post_validates_server_generated_typed_confirmation(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        actor = self._actor()
        valid_client = app.test_client()
        valid_client.get("/login")
        with valid_client.session_transaction() as session_data:
            csrf_token = session_data.get("_csrf_token")
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch(
            "routes.approval.PurgeRequestService.get_summary", return_value=self._execution_summary()
        ), patch(
            "routes.approval.PurgeRequestService.get_workspace_target", return_value={"purged": False}
        ), patch("routes.approval.PurgeService.execute_workspace_purge") as execute:
            execute.return_value = SimpleNamespace(request_id=45)
            self._set_transport(valid_client)
            for phrase in ("", "purge workspace 12 request 45", "PURGE WORKSPACE 12"):
                with self.subTest(phrase=phrase):
                    response = valid_client.post(
                        "/approval/purge-requests/45/execute",
                        data={"csrf_token": csrf_token, "confirmation_phrase": phrase},
                    )
                    self.assertEqual(response.status_code, 302)
            self.assertEqual(execute.call_count, 0)

            response = valid_client.post(
                "/approval/purge-requests/45/execute",
                data={
                    "csrf_token": csrf_token,
                    "confirmation_phrase": "PURGE WORKSPACE 12 REQUEST 45",
                    "actor_id": "8",
                    "auth_provider": "google",
                },
            )
        self.assertEqual(response.status_code, 302)
        execute.assert_called_once_with(
            request_id=45, workspace_id=12, executor_user_id=9,
            authorization_generation=1, authorization_nonce="test-nonce",
        )

    def test_execution_post_maps_outcome_unknown_without_retry_or_success(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        actor = self._actor()
        valid_client = app.test_client()
        valid_client.get("/login")
        with valid_client.session_transaction() as session_data:
            csrf_token = session_data.get("_csrf_token")
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch(
            "routes.approval.PurgeRequestService.get_summary", return_value=self._execution_summary()
        ), patch(
            "routes.approval.PurgeRequestService.get_workspace_target", return_value={"purged": False}
        ), patch(
            "routes.approval.PurgeService.execute_workspace_purge",
            side_effect=__import__("services.purge_service", fromlist=["PurgeCommitOutcomeUnknownError"]).PurgeCommitOutcomeUnknownError(),
        ) as execute:
            self._set_transport(valid_client)
            response = valid_client.post(
                "/approval/purge-requests/45/execute",
                data={"csrf_token": csrf_token, "confirmation_phrase": "PURGE WORKSPACE 12 REQUEST 45"},
            )
        self.assertEqual(response.status_code, 302)
        execute.assert_called_once()

    def test_confirmation_template_documents_gate_and_boundary(self):
        with open("templates/approval/purge_request_execute.html", encoding="utf-8") as source:
            template = source.read()
        self.assertIn("csrf_token()", template)
        self.assertIn("confirmation_phrase", template)
        self.assertIn("Filesystem files are not deleted", template)
        self.assertIn("production authorization remains separate", template)
        self.assertNotIn("DATABASE_URL", template)
        self.assertNotIn("execute_workspace_purge", template)
        self.assertNotIn("raw_nonce", template)
        self.assertNotIn("nonce_hash", template)
        self.assertNotIn("authorization_id", template)
        self.assertNotIn("generation", template)

    def test_postgres_route_login_helper_preserves_real_csrf_flow(self):
        from tests.postgresql.rehearsal_runtime import login_test_client_with_csrf

        helper_source = inspect.getsource(login_test_client_with_csrf)
        with open("tests/postgresql/test_purge_runtime_postgresql.py", encoding="utf-8") as source_file:
            route_test_source = source_file.read()
        self.assertIn('client.get("/login")', helper_source)
        self.assertIn('headers={"X-CSRFToken": login_csrf_token}', helper_source)
        self.assertIn('session_data.get("_csrf_token")', helper_source)
        self.assertIn("login_test_client_with_csrf", route_test_source)
        self.assertIn('execute_csrf_token = session_data.get("_csrf_token")', route_test_source)
        self.assertIn('"csrf_token": execute_csrf_token', route_test_source)
        self.assertNotIn("AUTH_SESSION_KEY", helper_source)
        self.assertNotIn("login_user", helper_source)
        self.assertNotIn("print(", helper_source)
        self.assertNotIn("TEST_DATABASE_URL", helper_source)

    def test_login_rejects_missing_or_invalid_csrf_before_authentication(self):
        client = app.test_client()
        self.assertEqual(client.get("/login").status_code, 200)
        with client.session_transaction() as session_data:
            valid_token = session_data.get("_csrf_token")
        self.assertTrue(valid_token)

        missing = client.post(
            "/login",
            json={"username": "not-used", "password": "not-used"},
        )
        invalid = client.post(
            "/login",
            json={"username": "not-used", "password": "not-used"},
            headers={"X-CSRFToken": "invalid-token"},
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(invalid.status_code, 400)
        with client.session_transaction() as session_data:
            self.assertNotIn("auth_user_id", session_data)

    def test_reauth_post_requires_csrf_and_stores_only_durable_issuance_transport(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        actor = self._actor()
        issuance = PurgeReauthIssuance(
            authorization_id=99, purge_request_id=45, actor_user_id=9, generation=1,
            authenticated_at=datetime.utcnow(), expires_at=datetime.utcnow() + timedelta(minutes=4),
            raw_nonce="recognizable-test-nonce",
        )
        client = app.test_client()
        client.get("/login")
        with client.session_transaction() as session_data:
            csrf_token = session_data.get("_csrf_token")
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch(
            "routes.approval.PurgeRequestService.get_summary", return_value=self._execution_summary()
        ), patch(
            "routes.approval.PurgeRequestService.get_workspace_target", return_value={"purged": False}
        ), patch(
            "routes.approval.PurgeReauthService.issue_local_authorization", return_value=issuance
        ) as issue:
            response = self.client.post(
                "/approval/purge-requests/45/reauth",
                data={"current_password": "Password123!"},
            )
            self.assertEqual(response.status_code, 400)
            issue.assert_not_called()

            response = client.post(
                "/approval/purge-requests/45/reauth",
                data={"csrf_token": csrf_token, "current_password": "Password123!"},
            )
            self.assertEqual(response.status_code, 302)
            issue.assert_called_once_with(45, 9, "Password123!")
            self.assertNotIn("recognizable-test-nonce", response.get_data(as_text=True))
            with client.session_transaction() as session_data:
                transport = session_data["purge_reauth_transport_v1"]
                self.assertEqual(transport["raw_nonce"], "recognizable-test-nonce")
                self.assertNotIn("current_password", session_data)
                self.assertNotIn("nonce_hash", session_data)

    def test_reauth_post_maps_rate_limit_without_issuing_transport(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        actor = self._actor()
        client = app.test_client()
        client.get("/login")
        with client.session_transaction() as session_data:
            csrf_token = session_data.get("_csrf_token")
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch(
            "routes.approval.PurgeRequestService.get_summary", return_value=self._execution_summary()
        ), patch(
            "routes.approval.PurgeRequestService.get_workspace_target", return_value={"purged": False}
        ), patch(
            "routes.approval.PurgeReauthService.issue_local_authorization",
            side_effect=PurgeReauthRateLimitedError(),
        ):
            response = client.post(
                "/approval/purge-requests/45/reauth",
                data={"csrf_token": csrf_token, "current_password": "Password123!"},
            )
        self.assertEqual(response.status_code, 302)
        with client.session_transaction() as session_data:
            self.assertNotIn("purge_reauth_transport_v1", session_data)

    def test_execute_transport_is_cleared_before_single_public_service_call_and_replay_fails(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        actor = self._actor()
        client = app.test_client()
        client.get("/login")
        with client.session_transaction() as session_data:
            csrf_token = session_data.get("_csrf_token")
        self._set_transport(client)
        observed = []

        def execute_once(**_kwargs):
            from flask import session
            observed.append("purge_reauth_transport_v1" not in session)
            return SimpleNamespace(request_id=45)

        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch(
            "routes.approval.PurgeRequestService.get_summary", return_value=self._execution_summary()
        ), patch(
            "routes.approval.PurgeRequestService.get_workspace_target", return_value={"purged": False}
        ), patch(
            "routes.approval.PurgeService.execute_workspace_purge", side_effect=execute_once
        ) as execute:
            response = client.post(
                "/approval/purge-requests/45/execute",
                data={"csrf_token": csrf_token, "confirmation_phrase": "PURGE WORKSPACE 12 REQUEST 45"},
            )
            self.assertEqual(response.status_code, 302)
            replay = client.post(
                "/approval/purge-requests/45/execute",
                data={"csrf_token": csrf_token, "confirmation_phrase": "PURGE WORKSPACE 12 REQUEST 45"},
            )
        self.assertEqual(replay.status_code, 302)
        self.assertEqual(observed, [True])
        execute.assert_called_once()

    def test_execute_rejects_expired_or_mismatched_session_transport_before_service(self):
        app.config["PERMANENT_PURGE_UI_ENABLED"] = True
        app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
        actor = self._actor()
        client = app.test_client()
        client.get("/login")
        with client.session_transaction() as session_data:
            csrf_token = session_data.get("_csrf_token")
        with patch("app.AuthService.get_current_user", return_value=actor), patch(
            "routes.approval.AuthService.get_current_active_user", return_value=actor
        ), patch(
            "routes.approval.PurgeRequestService.get_summary", return_value=self._execution_summary()
        ), patch(
            "routes.approval.PurgeRequestService.get_workspace_target", return_value={"purged": False}
        ), patch("routes.approval.PurgeService.execute_workspace_purge") as execute:
            for overrides in (
                {"expires_at": (datetime.utcnow() - timedelta(minutes=1)).isoformat()},
                {"purge_request_id": 46},
                {"workspace_id": 13},
                {"actor_user_id": 10},
            ):
                self._set_transport(client)
                with client.session_transaction() as session_data:
                    transport = dict(session_data["purge_reauth_transport_v1"])
                    transport.update(overrides)
                    session_data["purge_reauth_transport_v1"] = transport
                response = client.post(
                    "/approval/purge-requests/45/execute",
                    data={"csrf_token": csrf_token, "confirmation_phrase": "PURGE WORKSPACE 12 REQUEST 45"},
                )
                self.assertEqual(response.status_code, 302)
                with client.session_transaction() as session_data:
                    self.assertNotIn("purge_reauth_transport_v1", session_data)
        execute.assert_not_called()

    def test_logout_clears_transport_and_best_effort_revoke_does_not_block_logout(self):
        actor = self._actor()
        client = app.test_client()
        client.get("/login")
        with client.session_transaction() as session_data:
            session_data["purge_reauth_transport_v1"] = {"raw_nonce": "logout-test-nonce"}
            csrf_token = session_data.get("_csrf_token")
        with patch("routes.auth.AuthService.get_current_user", return_value=actor), patch(
            "routes.auth.AuthService.on_logout"
        ), patch(
            "services.purge_reauth_service.PurgeReauthService.revoke_active_authorizations_for_actor",
            side_effect=RuntimeError("synthetic revoke failure"),
        ) as revoke:
            response = client.post("/logout", data={"csrf_token": csrf_token})
        self.assertEqual(response.status_code, 302)
        revoke.assert_called_once_with(9, "LOGOUT")
        self.assertNotIn("logout-test-nonce", response.get_data(as_text=True))
        with client.session_transaction() as session_data:
            self.assertNotIn("purge_reauth_transport_v1", session_data)


if __name__ == "__main__":
    unittest.main()
