from unittest.mock import patch

import pytest
from tests.session_helpers import set_authenticated_session
from flask import session
from sqlalchemy.exc import SQLAlchemyError

pytestmark = pytest.mark.postgres_rehearsal


@pytest.fixture
def provenance_case(postgres_runtime):
    postgres_runtime.reset_database()
    try:
        yield postgres_runtime
    finally:
        postgres_runtime.reset_database()


def _user(models, username, role):
    user = models.User(
        username=username,
        email=f"{username}@invalid.test",
        full_name=username.replace("_", " ").title(),
        role=role,
        is_active=True,
        approval_status="active",
    )
    user.set_password("StrongPassword123!")
    return user


def _seed(runtime, marker):
    runtime.prepare_scoped_session()
    models = runtime.models
    workspace = models.Workspace(name=f"Provenance {marker}", slug=f"prov-{marker}", status="active")
    owner = _user(models, f"owner_{marker}", "OWNER")
    admin = _user(models, f"admin_{marker}", "ADMIN")
    staff = _user(models, f"staff_{marker}", "STAFF")
    runtime.db.session.add_all([workspace, owner, admin, staff])
    runtime.db.session.flush()
    runtime.db.session.add_all([
        models.WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner", status="active"),
        models.WorkspaceMember(workspace_id=workspace.id, user_id=admin.id, role="admin", status="active"),
        models.WorkspaceMember(workspace_id=workspace.id, user_id=staff.id, role="staff", status="active"),
    ])
    runtime.db.session.commit()
    return workspace, owner, admin, staff


def _request_context(workspace, actor):
    context = session
    context["current_workspace_id"] = workspace.id
    context["_enable_workspace_isolation"] = True
    set_authenticated_session(context, actor)
    context["user_id"] = actor.id


def _create(runtime, workspace, actor, username, role, *, email=None):
    with runtime.app.test_request_context():
        _request_context(workspace, actor)
        return runtime.services.UserService.create_user(
            actor=actor,
            username=username,
            full_name=username.replace("_", " ").title(),
            password="StrongPassword123!",
            email=email or f"{username}@invalid.test",
            role=role,
        )


def _soft_delete(runtime, workspace, actor, target):
    with runtime.app.test_request_context():
        _request_context(workspace, actor)
        runtime.services.UserService.soft_delete_user(actor, target.id, reason="rehearsal")


def test_pg_owner_creates_staff_exact_authoritative_provenance(provenance_case):
    from models.account_purge import UserCreationProvenance

    runtime = provenance_case
    workspace, owner, _, _ = _seed(runtime, "owner-staff")
    target = _create(runtime, workspace, owner, "created_staff_owner", "STAFF")
    record = UserCreationProvenance.query.filter_by(user_id=target.id).one()
    assert (record.created_by_user_id, record.created_in_workspace_id) == (owner.id, workspace.id)
    assert (record.creation_source, record.created_role, record.provenance_version) == ("WORKSPACE_OWNER", "STAFF", 1)


def test_pg_owner_creates_admin_exact_authoritative_provenance(provenance_case):
    from models.account_purge import UserCreationProvenance

    runtime = provenance_case
    workspace, owner, _, _ = _seed(runtime, "owner-admin")
    target = _create(runtime, workspace, owner, "created_admin_owner", "ADMIN")
    record = UserCreationProvenance.query.filter_by(user_id=target.id).one()
    assert (record.created_by_user_id, record.created_in_workspace_id) == (owner.id, workspace.id)
    assert (record.creation_source, record.created_role) == ("WORKSPACE_OWNER", "ADMIN")


def test_pg_unauthorized_actor_creates_no_partial_rows(provenance_case):
    from core.exceptions import PermissionDeniedException
    from models.account_purge import UserCreationProvenance

    runtime = provenance_case
    workspace, _, _, staff = _seed(runtime, "unauthorized")
    with pytest.raises(PermissionDeniedException):
        _create(runtime, workspace, staff, "unauthorized_target", "STAFF")
    assert runtime.models.User.query.filter_by(username="unauthorized_target").count() == 0
    assert UserCreationProvenance.query.count() == 0


def test_pg_provenance_failure_rolls_back_full_transaction(provenance_case):
    from core.exceptions import BusinessException
    from models.account_purge import UserCreationProvenance

    runtime = provenance_case
    workspace, owner, _, _ = _seed(runtime, "rollback")
    original_flush = runtime.db.session.flush
    calls = {"count": 0}

    def fail_on_provenance_flush(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 3:
            raise SQLAlchemyError("simulated provenance failure")
        return original_flush(*args, **kwargs)

    with patch.object(runtime.db.session, "flush", side_effect=fail_on_provenance_flush):
        with pytest.raises(BusinessException) as raised:
            _create(runtime, workspace, owner, "rollback_target", "STAFF")
    assert raised.value.code == "PROVENANCE_PERSISTENCE_ERROR"
    assert runtime.models.User.query.filter_by(username="rollback_target").count() == 0
    assert UserCreationProvenance.query.count() == 0


def test_pg_duplicate_username_email_create_no_orphan_provenance(provenance_case):
    from core.exceptions import ValidationException
    from models.account_purge import UserCreationProvenance

    runtime = provenance_case
    workspace, owner, _, _ = _seed(runtime, "duplicates")
    _create(runtime, workspace, owner, "duplicate_target", "STAFF")
    with pytest.raises(ValidationException):
        _create(runtime, workspace, owner, "duplicate_target", "STAFF")
    with pytest.raises(ValidationException):
        _create(
            runtime, workspace, owner, "duplicate_email_target", "STAFF",
            email="duplicate_target@invalid.test",
        )
    assert UserCreationProvenance.query.count() == 1


def test_pg_legacy_user_remains_without_provenance(provenance_case):
    from models.account_purge import UserCreationProvenance

    runtime = provenance_case
    workspace, _, _, _ = _seed(runtime, "legacy")
    legacy = _user(runtime.models, "legacy_user", "STAFF")
    runtime.db.session.add(legacy)
    runtime.db.session.flush()
    runtime.db.session.add(runtime.models.WorkspaceMember(
        workspace_id=workspace.id, user_id=legacy.id, role="staff", status="active"
    ))
    runtime.db.session.commit()
    assert UserCreationProvenance.query.filter_by(user_id=legacy.id).count() == 0


def test_pg_existing_user_added_elsewhere_gets_no_fake_provenance(provenance_case):
    from models.account_purge import UserCreationProvenance

    runtime = provenance_case
    workspace, _, _, _ = _seed(runtime, "existing")
    other = runtime.models.Workspace(name="Other", slug="other-existing", status="active")
    existing = _user(runtime.models, "existing_elsewhere", "STAFF")
    runtime.db.session.add_all([other, existing])
    runtime.db.session.flush()
    runtime.db.session.add_all([
        runtime.models.WorkspaceMember(workspace_id=other.id, user_id=existing.id, role="staff", status="active"),
        runtime.models.WorkspaceMember(workspace_id=workspace.id, user_id=existing.id, role="staff", status="active"),
    ])
    runtime.db.session.commit()
    assert UserCreationProvenance.query.filter_by(user_id=existing.id).count() == 0


def test_pg_owner_created_soft_delete_matches_deleted_list(provenance_case):
    runtime = provenance_case
    workspace, owner, _, _ = _seed(runtime, "deleted-list")
    target = _create(runtime, workspace, owner, "deleted_list_target", "STAFF")
    _soft_delete(runtime, workspace, owner, target)
    with runtime.app.test_request_context():
        _request_context(workspace, owner)
        removed = runtime.services.UserService.search_removed_paginated(page=1, per_page=25)
    assert target.id in {user.id for user in removed.items}


def test_pg_owner_created_soft_delete_is_account_purge_eligible(provenance_case):
    from services.account_purge_service import AccountPurgeService

    runtime = provenance_case
    workspace, owner, _, _ = _seed(runtime, "eligible")
    target = _create(runtime, workspace, owner, "eligible_target", "STAFF")
    _soft_delete(runtime, workspace, owner, target)
    result = AccountPurgeService.inspect_eligibility(
        requester_id=owner.id, target_user_id=target.id, managing_workspace_id=workspace.id,
    )
    assert result.eligible is True
    assert result.reason_code == "ELIGIBLE"


def test_pg_account_purge_request_is_requested_with_lifecycle_event(provenance_case):
    from models.account_purge import AccountPurgeLifecycleEvent
    from services.account_purge_service import AccountPurgeService

    runtime = provenance_case
    workspace, owner, _, _ = _seed(runtime, "request")
    target = _create(runtime, workspace, owner, "request_target", "STAFF")
    _soft_delete(runtime, workspace, owner, target)
    request = AccountPurgeService.create_request(
        requester_id=owner.id, target_user_id=target.id,
        managing_workspace_id=workspace.id, reason="rehearsal request",
    )
    event = AccountPurgeLifecycleEvent.query.filter_by(request_id=request.id).one()
    assert request.state == "REQUESTED"
    assert (event.event_type, event.to_state) == ("REQUESTED", "REQUESTED")


def test_pg_provenance_survives_soft_delete_and_restore(provenance_case):
    from models.account_purge import UserCreationProvenance

    runtime = provenance_case
    workspace, owner, _, _ = _seed(runtime, "restore")
    target = _create(runtime, workspace, owner, "restore_target", "STAFF")
    before = UserCreationProvenance.query.filter_by(user_id=target.id).one()
    _soft_delete(runtime, workspace, owner, target)
    with runtime.app.test_request_context():
        _request_context(workspace, owner)
        runtime.services.UserService.restore_user(owner, target.id)
    after = UserCreationProvenance.query.filter_by(user_id=target.id).one()
    assert after.id == before.id
    assert after.creation_source == "WORKSPACE_OWNER"


def test_pg_request_does_not_approve_execute_anonymize_or_delete_avatar(provenance_case):
    from models.account_purge import (
        AccountIdentityReservation,
        AccountPurgeAvatarCleanup,
        AccountPurgeExecutionAuthorization,
    )
    from services.account_purge_service import AccountPurgeService

    runtime = provenance_case
    workspace, owner, _, _ = _seed(runtime, "no-execution")
    target = _create(runtime, workspace, owner, "no_execution_target", "STAFF")
    _soft_delete(runtime, workspace, owner, target)
    request = AccountPurgeService.create_request(
        requester_id=owner.id, target_user_id=target.id,
        managing_workspace_id=workspace.id, reason="request only",
    )
    stored = runtime.models.User.query.get(target.id)
    assert request.state == "REQUESTED"
    assert stored.username == "no_execution_target"
    assert stored.email == "no_execution_target@invalid.test"
    assert stored.account_purge_state == "NOT_PURGED"
    assert stored.session_revocation_version == 0
    assert AccountPurgeExecutionAuthorization.query.count() == 0
    assert AccountIdentityReservation.query.count() == 0
    assert AccountPurgeAvatarCleanup.query.count() == 0
