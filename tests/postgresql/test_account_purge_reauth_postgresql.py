"""Bounded PostgreSQL validation for durable account-purge reauthorization."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from threading import Barrier
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

pytestmark = pytest.mark.postgres_rehearsal


def _models():
    from models.account_purge import (
        AccountPurgeExecutionAuthorization,
        AccountPurgeLegalHold,
        AccountPurgeLifecycleEvent,
        AccountPurgeRequest,
        AccountPurgeAvatarCleanup,
        AccountIdentityReservation,
        UserCreationProvenance,
    )
    from models.user import User
    from models.workspace import Workspace, WorkspaceMember
    return locals()


def _services():
    from services.account_purge_approval_service import AccountPurgeApprovalService
    from services.account_purge_legal_hold_service import AccountPurgeLegalHoldService
    from services.account_purge_reauth_service import AccountPurgeReauthError, AccountPurgeReauthService
    from services.account_purge_service import AccountPurgeService
    return locals()


@pytest.fixture
def scenario(postgres_runtime):
    postgres_runtime.reset_database()
    models = _models()
    session = postgres_runtime.prepare_scoped_session()

    def user(username, role):
        value = models["User"](username=username, email=f"{username}@example.test", full_name=username,
                                role=role, is_active=True, approval_status="active")
        value.set_password("StrongPassword123!")
        session.add(value)
        session.flush()
        return value

    workspace = models["Workspace"](name="Reauth PostgreSQL", slug=f"reauth-{datetime.utcnow().timestamp():.0f}", status="active")
    session.add(workspace)
    session.flush()
    requester = user("reauth_requester", "OWNER")
    approver = user("reauth_approver", "APPROVAL_OWNER")
    executor = user("reauth_executor", "APPROVAL_OWNER")
    second_executor = user("reauth_executor_two", "APPROVAL_OWNER")
    unauthorized = user("reauth_staff", "STAFF")
    target = user("reauth_target", "STAFF")
    session.add_all([
        models["WorkspaceMember"](workspace_id=workspace.id, user_id=requester.id, role="owner", status="active"),
        models["WorkspaceMember"](workspace_id=workspace.id, user_id=target.id, role="staff", status="removed", removed_at=datetime(2026, 1, 1)),
        models["UserCreationProvenance"](user_id=target.id, created_by_user_id=requester.id, created_in_workspace_id=workspace.id,
                                          creation_source="WORKSPACE_OWNER", created_role="STAFF", provenance_version=1),
    ])
    session.commit()
    request = _services()["AccountPurgeService"].create_request(
        requester_id=requester.id, target_user_id=target.id, managing_workspace_id=workspace.id,
        reason="bounded PostgreSQL reauth", now=datetime(2026, 2, 1))
    _services()["AccountPurgeApprovalService"].approve_request(request_id=request.id, approver_user_id=approver.id, expected_version=1)
    result = {"runtime": postgres_runtime, "models": models, "requester": requester, "approver": approver,
              "executor": executor, "second_executor": second_executor, "target": target, "workspace": workspace,
              "unauthorized": unauthorized,
              "request_id": request.id}
    yield result
    postgres_runtime.reset_database()


def _issue(scenario, actor=None):
    actor = actor or scenario["executor"]
    return _services()["AccountPurgeReauthService"].reauthenticate_and_issue(
        scenario["request_id"], actor.id, "StrongPassword123!", expected_request_version=2)


def _stored(scenario):
    session = scenario["runtime"].prepare_scoped_session()
    try:
        return session.get(scenario["models"]["AccountPurgeExecutionAuthorization"], scenario["request_id"])
    finally:
        session.rollback()


def _thread(runtime, callback):
    with runtime.app.app_context():
        return callback()


def test_pg_reauth_01_valid_issue_persists_hash_and_event(scenario):
    issued = _issue(scenario)
    stored = _stored(scenario)
    assert issued.raw_nonce and stored.nonce_hash != issued.raw_nonce
    assert stored.state == "ACTIVE" and stored.generation == 1
    assert stored.expires_at - stored.authenticated_at == timedelta(minutes=5)
    assert scenario["models"]["AccountPurgeLifecycleEvent"].query.filter_by(request_id=scenario["request_id"], event_type="AUTHORIZATION_ISSUED").count() == 1


def test_pg_reauth_02_wrong_password_records_shared_throttle(scenario):
    error = _services()["AccountPurgeReauthError"]
    with pytest.raises(error) as raised:
        _services()["AccountPurgeReauthService"].reauthenticate_and_issue(scenario["request_id"], scenario["executor"].id, "wrong")
    assert raised.value.code == "REAUTH_FAILED"
    assert _stored(scenario) is None


def test_pg_reauth_03_requester_is_rejected(scenario):
    service = _services()["AccountPurgeReauthService"]
    error = _services()["AccountPurgeReauthError"]
    for actor, expected in ((scenario["requester"], "REQUESTER_EXECUTOR_CONFLICT"),
                            (scenario["approver"], "APPROVER_EXECUTOR_CONFLICT"),
                            (scenario["target"], "TARGET_EXECUTOR_CONFLICT")):
        with pytest.raises(error) as raised:
            service.reauthenticate_and_issue(scenario["request_id"], actor.id, "StrongPassword123!")
        assert raised.value.code == expected


def test_pg_reauth_04_target_is_rejected(scenario):
    with pytest.raises(_services()["AccountPurgeReauthError"]) as raised:
        _services()["AccountPurgeReauthService"].reauthenticate_and_issue(scenario["request_id"], scenario["target"].id, "StrongPassword123!")
    assert raised.value.code == "TARGET_EXECUTOR_CONFLICT"
    assert _stored(scenario) is None
    session = scenario["runtime"].prepare_scoped_session()
    try:
        request = session.get(scenario["models"]["AccountPurgeRequest"], scenario["request_id"])
        target = session.get(scenario["models"]["User"], scenario["target"].id)
        assert request.state == "APPROVED"
        assert target.account_purge_state == "NOT_PURGED"
        from services.purge_reauth_service import workspace_purge_reauth_actor_throttles_table
        assert session.execute(select(workspace_purge_reauth_actor_throttles_table).where(
            workspace_purge_reauth_actor_throttles_table.c.actor_user_id == scenario["target"].id
        )).first() is None
    finally:
        session.rollback()


def test_pg_reauth_05_non_approval_owner_is_rejected(scenario):
    actor = scenario["unauthorized"]
    assert actor.id not in {scenario["requester"].id, scenario["approver"].id, scenario["target"].id}
    session = scenario["runtime"].prepare_scoped_session()
    persisted_actor = session.get(scenario["models"]["User"], actor.id)
    assert persisted_actor.role != "APPROVAL_OWNER"
    assert persisted_actor.auth_provider == "local"
    session.rollback()
    with pytest.raises(_services()["AccountPurgeReauthError"]) as raised:
        _services()["AccountPurgeReauthService"].reauthenticate_and_issue(scenario["request_id"], actor.id, "StrongPassword123!")
    assert raised.value.code == "EXECUTOR_NOT_AUTHORIZED"
    assert _stored(scenario) is None
    session = scenario["runtime"].prepare_scoped_session()
    try:
        request = session.get(scenario["models"]["AccountPurgeRequest"], scenario["request_id"])
        target = session.get(scenario["models"]["User"], scenario["target"].id)
        assert request.state == "APPROVED"
        assert target.account_purge_state == "NOT_PURGED"
    finally:
        session.rollback()


def test_pg_reauth_06_active_hold_blocks_issue(scenario):
    _services()["AccountPurgeLegalHoldService"].place_hold(target_user_id=scenario["target"].id, actor_user_id=scenario["approver"].id,
                                                            managing_workspace_id=scenario["workspace"].id, reason="review")
    with pytest.raises(_services()["AccountPurgeReauthError"]) as raised:
        _issue(scenario)
    assert raised.value.code == "ACTIVE_LEGAL_HOLD"


def test_pg_reauth_07_unapproved_request_is_rejected(scenario):
    session = scenario["runtime"].prepare_scoped_session()
    request = session.get(scenario["models"]["AccountPurgeRequest"], scenario["request_id"])
    request.state = "REQUESTED"
    session.commit()
    with pytest.raises(_services()["AccountPurgeReauthError"]) as raised:
        _issue(scenario)
    assert raised.value.code == "INVALID_REQUEST_STATE"


def test_pg_reauth_08_duplicate_active_is_rejected(scenario):
    _issue(scenario)
    with pytest.raises(_services()["AccountPurgeReauthError"]) as raised:
        _issue(scenario)
    assert raised.value.code == "ACTIVE_AUTHORIZATION_EXISTS"


def test_pg_reauth_09_concurrent_issue_has_one_winner(scenario):
    barrier = Barrier(2)
    service = _services()["AccountPurgeReauthService"]
    def call(actor):
        return _thread(scenario["runtime"], lambda: (barrier.wait(timeout=5), service.reauthenticate_and_issue(scenario["request_id"], actor.id, "StrongPassword123!"))[1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call, actor) for actor in (scenario["executor"], scenario["second_executor"])]
        outcomes, errors = [], []
        for future in futures:
            try: outcomes.append(future.result(timeout=10))
            except Exception as exc: errors.append(exc)
    assert len(outcomes) == 1 and len(errors) == 1
    assert isinstance(errors[0], _services()["AccountPurgeReauthError"])


def test_pg_reauth_10_valid_claim_is_single_use(scenario):
    issued = _issue(scenario)
    claimed = _services()["AccountPurgeReauthService"].claim_authorization(scenario["request_id"], scenario["executor"].id, issued.raw_nonce, issued.generation)
    assert claimed.state == "CLAIMED" and claimed.generation == issued.generation + 1 and _stored(scenario).nonce_hash is None
    event = scenario["models"]["AccountPurgeLifecycleEvent"].query.filter_by(request_id=scenario["request_id"], event_type="AUTHORIZATION_CLAIMED").one()
    detail = json.loads(event.safe_detail)
    assert detail["previous_generation"] == issued.generation
    assert detail["generation"] == issued.generation + 1
    with pytest.raises(_services()["AccountPurgeReauthError"]) as raised:
        _services()["AccountPurgeReauthService"].claim_authorization(scenario["request_id"], scenario["executor"].id, issued.raw_nonce, issued.generation)
    assert raised.value.code == "AUTHORIZATION_VERSION_CONFLICT"
    with pytest.raises(_services()["AccountPurgeReauthError"]) as raised:
        _services()["AccountPurgeReauthService"].claim_authorization(scenario["request_id"], scenario["executor"].id, issued.raw_nonce, claimed.generation)
    assert raised.value.code == "AUTHORIZATION_ALREADY_CLAIMED"
    stored = _stored(scenario)
    assert stored.state == "CLAIMED" and stored.generation == claimed.generation
    assert scenario["models"]["AccountPurgeLifecycleEvent"].query.filter_by(
        request_id=scenario["request_id"], event_type="AUTHORIZATION_CLAIMED"
    ).count() == 1


def test_pg_reauth_11_concurrent_claim_has_one_winner(scenario):
    issued = _issue(scenario)
    barrier = Barrier(2)
    service = _services()["AccountPurgeReauthService"]
    def call(): return _thread(scenario["runtime"], lambda: (barrier.wait(timeout=5), service.claim_authorization(scenario["request_id"], scenario["executor"].id, issued.raw_nonce, issued.generation))[1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call) for _ in range(2)]
        outcomes, errors = [], []
        for future in futures:
            try: outcomes.append(future.result(timeout=10))
            except Exception as exc: errors.append(exc)
    assert len(outcomes) == 1 and len(errors) == 1


def test_pg_reauth_12_expired_claim_is_rejected(scenario):
    issued = _issue(scenario)
    session = scenario["runtime"].prepare_scoped_session()
    auth = session.get(scenario["models"]["AccountPurgeExecutionAuthorization"], scenario["request_id"])
    auth.expires_at = datetime.utcnow() - timedelta(seconds=1)
    session.commit()
    with pytest.raises(_services()["AccountPurgeReauthError"]) as raised:
        _services()["AccountPurgeReauthService"].claim_authorization(scenario["request_id"], scenario["executor"].id, issued.raw_nonce, issued.generation)
    assert raised.value.code == "AUTHORIZATION_EXPIRED"


def test_pg_reauth_13_expired_issue_reissues_generation(scenario):
    issued = _issue(scenario)
    session = scenario["runtime"].prepare_scoped_session()
    auth = session.get(scenario["models"]["AccountPurgeExecutionAuthorization"], scenario["request_id"])
    auth.expires_at = datetime.utcnow() - timedelta(seconds=1)
    session.commit()
    replacement = _issue(scenario)
    assert replacement.generation == issued.generation + 1


def test_pg_reauth_14_revoked_claim_is_rejected(scenario):
    issued = _issue(scenario)
    _services()["AccountPurgeReauthService"].revoke_authorization(scenario["request_id"], scenario["approver"].id, "policy changed", issued.generation)
    with pytest.raises(_services()["AccountPurgeReauthError"]) as raised:
        _services()["AccountPurgeReauthService"].claim_authorization(scenario["request_id"], scenario["executor"].id, issued.raw_nonce, issued.generation)
    assert raised.value.code in {"AUTHORIZATION_REVOKED", "AUTHORIZATION_VERSION_CONFLICT"}


def test_pg_reauth_15_claim_and_revoke_are_serialized(scenario):
    issued = _issue(scenario)
    barrier = Barrier(2)
    service = _services()["AccountPurgeReauthService"]
    def claim(): return _thread(scenario["runtime"], lambda: (barrier.wait(timeout=5), service.claim_authorization(scenario["request_id"], scenario["executor"].id, issued.raw_nonce, issued.generation))[1])
    def revoke(): return _thread(scenario["runtime"], lambda: (barrier.wait(timeout=5), service.revoke_authorization(scenario["request_id"], scenario["approver"].id, "race", issued.generation))[1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim), pool.submit(revoke)]
        results = [future.result(timeout=10) for future in futures if not future.exception()]
    assert len(results) == 1


def test_pg_reauth_16_hold_after_issue_blocks_claim(scenario):
    issued = _issue(scenario)
    _services()["AccountPurgeLegalHoldService"].place_hold(target_user_id=scenario["target"].id, actor_user_id=scenario["approver"].id,
                                                            managing_workspace_id=scenario["workspace"].id, reason="late hold")
    with pytest.raises(_services()["AccountPurgeReauthError"]) as raised:
        _services()["AccountPurgeReauthService"].claim_authorization(scenario["request_id"], scenario["executor"].id, issued.raw_nonce, issued.generation)
    assert raised.value.code == "ACTIVE_LEGAL_HOLD"


def test_pg_reauth_17_event_failure_rolls_back_authorization(scenario):
    service = _services()["AccountPurgeReauthService"]
    with patch.object(service, "_add_event", side_effect=SQLAlchemyError("injected")):
        with pytest.raises(_services()["AccountPurgeReauthError"]) as raised:
            _issue(scenario)
    assert raised.value.code == "PERSISTENCE_FAILURE"
    assert _stored(scenario) is None


def test_pg_reauth_18_no_execution_or_identity_side_effects(scenario):
    _issue(scenario)
    session = scenario["runtime"].prepare_scoped_session()
    try:
        target = session.get(scenario["models"]["User"], scenario["target"].id)
        assert target.account_purge_state == "NOT_PURGED"
        assert target.account_purged_at is None
        assert target.session_revocation_version == 0
        assert session.query(scenario["models"]["AccountIdentityReservation"]).count() == 0
        assert session.query(scenario["models"]["AccountPurgeAvatarCleanup"]).count() == 0
    finally:
        session.rollback()
