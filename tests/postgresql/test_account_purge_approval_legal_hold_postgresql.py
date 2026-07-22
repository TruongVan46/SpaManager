"""Bounded PostgreSQL validation for account purge approval and legal holds.

This module is intentionally opt-in through the canonical PostgreSQL rehearsal
fixtures.  It never creates a database, changes schema, or prints credentials.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from unittest.mock import patch

import pytest
from sqlalchemy.exc import SQLAlchemyError


pytestmark = pytest.mark.postgres_rehearsal


def _models():
    from models.account_purge import (
        AccountIdentityReservation,
        AccountPurgeAvatarCleanup,
        AccountPurgeExecutionAuthorization,
        AccountPurgeLegalHold,
        AccountPurgeLifecycleEvent,
        AccountPurgeRequest,
        UserCreationProvenance,
    )
    from models.user import User
    from models.workspace import Workspace, WorkspaceMember

    return {
        "AccountIdentityReservation": AccountIdentityReservation,
        "AccountPurgeAvatarCleanup": AccountPurgeAvatarCleanup,
        "AccountPurgeExecutionAuthorization": AccountPurgeExecutionAuthorization,
        "AccountPurgeLegalHold": AccountPurgeLegalHold,
        "AccountPurgeLifecycleEvent": AccountPurgeLifecycleEvent,
        "AccountPurgeRequest": AccountPurgeRequest,
        "User": User,
        "UserCreationProvenance": UserCreationProvenance,
        "Workspace": Workspace,
        "WorkspaceMember": WorkspaceMember,
    }


def _services():
    from services.account_purge_approval_service import (
        AccountPurgeApprovalService,
        AccountPurgeApprovalServiceError,
    )
    from services.account_purge_legal_hold_service import (
        AccountPurgeLegalHoldService,
        AccountPurgeLegalHoldServiceError,
    )
    from services.account_purge_service import AccountPurgeService

    return {
        "AccountPurgeApprovalService": AccountPurgeApprovalService,
        "AccountPurgeApprovalServiceError": AccountPurgeApprovalServiceError,
        "AccountPurgeLegalHoldService": AccountPurgeLegalHoldService,
        "AccountPurgeLegalHoldServiceError": AccountPurgeLegalHoldServiceError,
        "AccountPurgeService": AccountPurgeService,
    }


@pytest.fixture
def scenario(postgres_runtime):
    """Reset before and after every scenario, preserving the canonical schema."""
    postgres_runtime.reset_database()
    try:
        yield _seed(postgres_runtime)
    finally:
        postgres_runtime.reset_database()


def _seed(runtime):
    models = _models()
    session = runtime.prepare_scoped_session()

    def user(username, role, *, active=True):
        value = models["User"](
            username=username,
            email=f"{username}@example.test",
            full_name=username.title(),
            role=role,
            is_active=active,
            approval_status="active",
        )
        value.set_password("StrongPassword123!")
        session.add(value)
        session.flush()
        return value

    workspace = models["Workspace"](
        name="B1 PostgreSQL Workspace",
        slug=f"b1-postgres-{datetime.utcnow().timestamp():.0f}",
        status="active",
    )
    session.add(workspace)
    session.flush()
    requester = user("b1_requester", "OWNER")
    approver = user("b1_approver", "APPROVAL_OWNER")
    second_approver = user("b1_second_approver", "APPROVAL_OWNER")
    target = user("b1_target", "STAFF")
    session.add_all(
        [
            models["WorkspaceMember"](
                workspace_id=workspace.id,
                user_id=requester.id,
                role="owner",
                status="active",
            ),
            models["WorkspaceMember"](
                workspace_id=workspace.id,
                user_id=target.id,
                role="staff",
                status="removed",
                removed_at=datetime(2026, 1, 1),
            ),
            models["UserCreationProvenance"](
                user_id=target.id,
                created_by_user_id=requester.id,
                created_in_workspace_id=workspace.id,
                creation_source="WORKSPACE_OWNER",
                created_role="STAFF",
                provenance_version=1,
            ),
        ]
    )
    session.commit()
    return {
        "runtime": runtime,
        "models": models,
        "requester": requester,
        "approver": approver,
        "second_approver": second_approver,
        "target": target,
        "workspace": workspace,
    }


def _request(scenario):
    service = _services()["AccountPurgeService"]
    request = service.create_request(
        requester_id=scenario["requester"].id,
        target_user_id=scenario["target"].id,
        managing_workspace_id=scenario["workspace"].id,
        reason="bounded PostgreSQL validation",
        now=datetime(2026, 2, 1),
    )
    return request


def _stored(scenario, request_id):
    session = scenario["runtime"].prepare_scoped_session()
    try:
        return session.get(scenario["models"]["AccountPurgeRequest"], request_id)
    finally:
        session.rollback()


def _assert_no_residue(scenario):
    session = scenario["runtime"].prepare_scoped_session()
    try:
        assert session.query(scenario["models"]["AccountPurgeExecutionAuthorization"]).count() == 0
        assert session.query(scenario["models"]["AccountIdentityReservation"]).count() == 0
        assert session.query(scenario["models"]["AccountPurgeAvatarCleanup"]).count() == 0
    finally:
        session.rollback()


def test_pg_01_valid_requested_to_approved(scenario):
    request = _request(scenario)
    approval = _services()["AccountPurgeApprovalService"].approve_request(
        request_id=request.id, approver_user_id=scenario["approver"].id, expected_version=1
    )
    stored = _stored(scenario, request.id)
    assert approval.state == "APPROVED"
    assert stored.state == "APPROVED"
    assert stored.version == 2
    assert stored.approver_id == scenario["approver"].id
    assert scenario["models"]["AccountPurgeLifecycleEvent"].query.filter_by(
        request_id=request.id, event_type="APPROVED"
    ).count() == 1
    _assert_no_residue(scenario)


def test_pg_02_requester_cannot_approve(scenario):
    request = _request(scenario)
    error = _services()["AccountPurgeApprovalServiceError"]
    with pytest.raises(error) as raised:
        _services()["AccountPurgeApprovalService"].approve_request(
            request_id=request.id, approver_user_id=scenario["requester"].id
        )
    assert raised.value.code == "APPROVER_NOT_AUTHORIZED"
    assert _stored(scenario, request.id).state == "REQUESTED"


def test_pg_03_target_cannot_approve(scenario):
    request = _request(scenario)
    error = _services()["AccountPurgeApprovalServiceError"]
    with pytest.raises(error) as raised:
        _services()["AccountPurgeApprovalService"].approve_request(
            request_id=request.id, approver_user_id=scenario["target"].id
        )
    assert raised.value.code == "APPROVER_NOT_AUTHORIZED"
    assert _stored(scenario, request.id).state == "REQUESTED"


def test_pg_04_active_legal_hold_blocks_approval(scenario):
    request = _request(scenario)
    hold_service = _services()["AccountPurgeLegalHoldService"]
    hold_service.place_hold(
        target_user_id=scenario["target"].id,
        actor_user_id=scenario["approver"].id,
        managing_workspace_id=scenario["workspace"].id,
        reason="active legal review",
    )
    error = _services()["AccountPurgeApprovalServiceError"]
    with pytest.raises(error) as raised:
        _services()["AccountPurgeApprovalService"].approve_request(
            request_id=request.id, approver_user_id=scenario["approver"].id
        )
    assert raised.value.code == "ACTIVE_LEGAL_HOLD"
    assert _stored(scenario, request.id).state == "REQUESTED"


def test_pg_05_released_legal_hold_permits_approval(scenario):
    request = _request(scenario)
    hold_service = _services()["AccountPurgeLegalHoldService"]
    hold = hold_service.place_hold(
        target_user_id=scenario["target"].id,
        actor_user_id=scenario["approver"].id,
        request_id=request.id,
        reason="temporary legal review",
    )
    hold_service.release_hold(
        hold_id=hold.id,
        actor_user_id=scenario["approver"].id,
        release_reason="review completed",
        expected_version=1,
    )
    result = _services()["AccountPurgeApprovalService"].approve_request(
        request_id=request.id, approver_user_id=scenario["approver"].id
    )
    assert result.state == "APPROVED"


def test_pg_06_rejection_is_atomic(scenario):
    request = _request(scenario)
    result = _services()["AccountPurgeApprovalService"].reject_request(
        request_id=request.id,
        approver_user_id=scenario["approver"].id,
        rejection_reason="  policy review  ",
        expected_version=1,
    )
    stored = _stored(scenario, request.id)
    assert result.state == "REJECTED"
    assert stored.version == 2
    assert stored.rejection_reason == "policy review"
    assert scenario["models"]["AccountPurgeLifecycleEvent"].query.filter_by(
        request_id=request.id, event_type="REJECTED"
    ).count() == 1


def test_pg_07_original_requester_cancels_atomically(scenario):
    request = _request(scenario)
    result = _services()["AccountPurgeApprovalService"].cancel_request(
        request_id=request.id,
        requester_user_id=scenario["requester"].id,
        cancellation_reason=" no longer needed ",
        expected_version=1,
    )
    stored = _stored(scenario, request.id)
    assert result.state == "CANCELLED"
    assert stored.version == 2
    assert stored.cancellation_reason == "no longer needed"


def test_pg_08_lifecycle_failure_rolls_back_approval(scenario):
    request = _request(scenario)
    approval_service = _services()["AccountPurgeApprovalService"]
    approval_error = _services()["AccountPurgeApprovalServiceError"]
    with patch.object(approval_service, "_add_lifecycle_event", side_effect=SQLAlchemyError("injected")):
        with pytest.raises(approval_error) as raised:
            approval_service.approve_request(
                request_id=request.id, approver_user_id=scenario["approver"].id
            )
    assert raised.value.code == "PERSISTENCE_FAILURE"
    stored = _stored(scenario, request.id)
    assert stored.state == "REQUESTED"
    assert stored.version == 1
    assert stored.approved_at is None
    assert scenario["models"]["AccountPurgeLifecycleEvent"].query.filter_by(request_id=request.id).count() == 1


def _thread_call(runtime, callback):
    with runtime.app.app_context():
        return callback()


def test_pg_09_concurrent_approve_has_one_winner(scenario):
    request = _request(scenario)
    barrier = Barrier(2)
    service = _services()["AccountPurgeApprovalService"]

    def worker(actor_id):
        def action():
            barrier.wait(timeout=5)
            return service.approve_request(request_id=request.id, approver_user_id=actor_id)

        return _thread_call(scenario["runtime"], action)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, actor) for actor in (scenario["approver"].id, scenario["second_approver"].id)]
        results = []
        errors = []
        for future in futures:
            try:
                results.append(future.result(timeout=10))
            except Exception as exc:  # surfaced and counted below
                errors.append(exc)
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], _services()["AccountPurgeApprovalServiceError"])
    assert errors[0].code in {"INVALID_REQUEST_STATE", "REQUEST_VERSION_CONFLICT"}
    stored = _stored(scenario, request.id)
    assert stored.state == "APPROVED"
    assert stored.version == 2
    assert stored.approver_id in {scenario["approver"].id, scenario["second_approver"].id}
    assert scenario["models"]["AccountPurgeLifecycleEvent"].query.filter_by(
        request_id=request.id, event_type="APPROVED"
    ).count() == 1


def test_pg_10_concurrent_approve_reject_has_one_outcome(scenario):
    request = _request(scenario)
    barrier = Barrier(2)
    approval_service = _services()["AccountPurgeApprovalService"]

    def approve():
        with scenario["runtime"].app.app_context():
            barrier.wait(timeout=5)
            return approval_service.approve_request(request_id=request.id, approver_user_id=scenario["approver"].id)

    def reject():
        with scenario["runtime"].app.app_context():
            barrier.wait(timeout=5)
            return approval_service.reject_request(
                request_id=request.id,
                approver_user_id=scenario["second_approver"].id,
                rejection_reason="concurrent review",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(approve), pool.submit(reject)]
        outcomes = []
        errors = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10).state)
            except Exception as exc:
                errors.append(exc)
    assert len(outcomes) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], _services()["AccountPurgeApprovalServiceError"])
    assert errors[0].code in {"INVALID_REQUEST_STATE", "REQUEST_VERSION_CONFLICT"}
    stored = _stored(scenario, request.id)
    assert stored.state == outcomes[0]
    assert stored.version == 2
    terminal_events = scenario["models"]["AccountPurgeLifecycleEvent"].query.filter(
        scenario["models"]["AccountPurgeLifecycleEvent"].request_id == request.id,
        scenario["models"]["AccountPurgeLifecycleEvent"].event_type.in_(("APPROVED", "REJECTED")),
    ).all()
    assert len(terminal_events) == 1
    assert terminal_events[0].event_type == outcomes[0]


def test_pg_11_duplicate_active_equivalent_hold_is_prevented(scenario):
    service = _services()["AccountPurgeLegalHoldService"]
    service.place_hold(
        target_user_id=scenario["target"].id,
        actor_user_id=scenario["approver"].id,
        managing_workspace_id=scenario["workspace"].id,
        reason="duplicate guard",
    )
    error = _services()["AccountPurgeLegalHoldServiceError"]
    with pytest.raises(error) as raised:
        service.place_hold(
            target_user_id=scenario["target"].id,
            actor_user_id=scenario["approver"].id,
            managing_workspace_id=scenario["workspace"].id,
            reason="duplicate guard",
        )
    assert raised.value.code == "DUPLICATE_ACTIVE_HOLD"


def test_pg_12_concurrent_hold_release_is_consistent(scenario):
    service = _services()["AccountPurgeLegalHoldService"]
    hold = service.place_hold(
        target_user_id=scenario["target"].id,
        actor_user_id=scenario["approver"].id,
        managing_workspace_id=scenario["workspace"].id,
        reason="release race",
    )
    barrier = Barrier(2)

    def release():
        with scenario["runtime"].app.app_context():
            barrier.wait(timeout=5)
            return service.release_hold(
                hold_id=hold.id,
                actor_user_id=scenario["approver"].id,
                release_reason="release race resolved",
                expected_version=1,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(release), pool.submit(release)]
        outcomes = []
        errors = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10).state)
            except Exception as exc:
                errors.append(exc)
    assert outcomes == ["RELEASED"]
    assert len(errors) == 1
    session = scenario["runtime"].prepare_scoped_session()
    try:
        stored = session.get(scenario["models"]["AccountPurgeLegalHold"], hold.id)
        assert stored.state == "RELEASED"
        assert stored.version == 2
    finally:
        session.rollback()


def test_pg_13_approval_creates_no_account_purge_authorization(scenario):
    request = _request(scenario)
    _services()["AccountPurgeApprovalService"].approve_request(
        request_id=request.id, approver_user_id=scenario["approver"].id
    )
    _assert_no_residue(scenario)


def test_pg_14_approval_does_not_execute_or_anonymize(scenario):
    request = _request(scenario)
    _services()["AccountPurgeApprovalService"].approve_request(
        request_id=request.id, approver_user_id=scenario["approver"].id
    )
    session = scenario["runtime"].prepare_scoped_session()
    try:
        target = session.get(scenario["models"]["User"], scenario["target"].id)
        assert target.account_purge_state == "NOT_PURGED"
        assert target.account_purged_at is None
        assert target.session_revocation_version == 0
        assert session.query(scenario["models"]["AccountPurgeAvatarCleanup"]).count() == 0
    finally:
        session.rollback()
    _assert_no_residue(scenario)
