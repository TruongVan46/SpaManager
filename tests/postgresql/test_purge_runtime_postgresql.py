from datetime import datetime
import inspect
from pathlib import Path
import uuid

import pytest


pytestmark = pytest.mark.postgres_rehearsal


def _marker():
    return uuid.uuid4().hex[:12]


def _base_fixture(runtime, *, include_business=True, logo=None):
    models = runtime.models
    services = runtime.services
    db = runtime.db
    runtime.prepare_scoped_session()
    marker = _marker()
    actor = models.User(
        username=f"pg_actor_{marker}", email=f"pg_actor_{marker}@invalid.test",
        full_name="Synthetic Approval Owner", role="APPROVAL_OWNER",
        approval_status="active", is_active=True,
    )
    executor = models.User(
        username=f"pg_executor_{marker}", email=f"pg_executor_{marker}@invalid.test",
        full_name="Synthetic Approval Executor", role="APPROVAL_OWNER",
        approval_status="active", is_active=True,
    )
    owner = models.User(
        username=f"pg_owner_{marker}", email=f"pg_owner_{marker}@invalid.test",
        full_name="Synthetic Target Owner", role="OWNER",
        approval_status="active", is_active=False,
        deleted_at=datetime(2026, 1, 1), deleted_by_id=None,
    )
    actor.set_password(f"synthetic-{marker}")
    executor.set_password(f"synthetic-{marker}")
    owner.set_password(f"synthetic-{marker}")
    db.session.add_all([actor, executor, owner])
    db.session.flush()
    owner.deleted_by_id = actor.id
    workspace = models.Workspace(
        name=f"Synthetic Workspace {marker}", slug=f"pg-{marker}", status="active",
        deleted_at=datetime(2026, 1, 1), deleted_by_id=actor.id,
    )
    db.session.add(workspace)
    db.session.flush()
    member = models.WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner", status="active")
    db.session.add(member)
    customer = service = invoice = setting = None
    if include_business:
        customer = models.Customer(name=f"Synthetic Customer {marker}", workspace_id=workspace.id)
        service = models.Service(name=f"Synthetic Service {marker}", price=100, workspace_id=workspace.id)
        db.session.add_all([customer, service])
        db.session.flush()
        invoice = models.Invoice(customer_id=customer.id, total_amount=100, workspace_id=workspace.id)
        db.session.add(invoice)
        db.session.flush()
        db.session.add(models.InvoiceDetail(invoice_id=invoice.id, service_id=service.id, price=100, quantity=1))
        db.session.add(models.Appointment(
            customer_id=customer.id, service_id=service.id,
            appointment_time=datetime(2026, 1, 2), workspace_id=workspace.id,
        ))
        setting = models.Setting(key=f"spa_name_{marker}", value=f"Benign Spa {marker}", workspace_id=workspace.id)
        db.session.add(setting)
    if logo is not None:
        db.session.add(models.Setting(key="spa_logo", value=logo, workspace_id=workspace.id))
    db.session.add(models.ActivityLog(
        module="PostgreSQL rehearsal", action="CREATE",
        description=f"Synthetic audit {marker}", workspace_id=workspace.id,
    ))
    db.session.flush()
    actor_id = actor.id
    executor_id = executor.id
    owner_id = owner.id
    workspace_id = workspace.id
    workspace_slug = workspace.slug
    member_id = member.id
    customer_id = customer.id if customer else None
    service_id = service.id if service else None
    invoice_id = invoice.id if invoice else None
    setting_id = setting.id if setting else None
    deletion_timestamp = workspace.deleted_at
    actor_username = actor.username
    audit_description = f"Synthetic audit {marker}"
    db.session.commit()
    return {
        "marker": marker, "actor": actor, "executor": executor, "owner": owner, "workspace": workspace,
        "customer": customer, "service": service, "invoice": invoice, "member": member, "setting": setting,
        "actor_id": actor_id, "executor_id": executor_id, "owner_id": owner_id, "workspace_id": workspace_id,
        "workspace_slug": workspace_slug, "member_id": member_id, "customer_id": customer_id,
        "service_id": service_id, "invoice_id": invoice_id, "setting_id": setting_id,
        "deletion_timestamp": deletion_timestamp, "actor_username": actor_username,
        "audit_description": audit_description,
        "db": db, "models": models, "services": services,
    }


def _distinct_execution_actor(fixture):
    models = fixture["models"]
    db = fixture["db"]
    marker = fixture["marker"]
    password = f"execution-{marker}"
    executor = models.User(
        username=f"pg_execution_executor_{marker}",
        email=f"pg_execution_executor_{marker}@invalid.test",
        full_name="Synthetic Distinct Execution Executor",
        role="APPROVAL_OWNER",
        approval_status="active",
        is_active=True,
    )
    executor.set_password(password)
    db.session.add(executor)
    db.session.flush()
    db.session.commit()
    return executor.id, password


@pytest.fixture
def postgres_case(postgres_service_session_timeouts, postgres_runtime):
    postgres_runtime.reset_database()
    try:
        yield postgres_runtime
    finally:
        postgres_runtime.reset_database()


def test_schema_and_runtime_identity(postgres_runtime):
    identity = postgres_runtime.identity()
    assert identity["database"] == "spamanager_purge_rehearsal_test"
    assert identity["revision"] == "0008_durable_purge_reauth_state"
    assert identity["server_port"] == "5432"
    assert identity["workflow_tables"] == (
        "purge_legal_holds", "purge_lifecycle_events", "workspace_purge_requests"
    )
    assert identity["terminal_columns"] == ("purge_request_id", "purged_at")


def test_request_creation_manifest_and_duplicate(postgres_case):
    fixture = _base_fixture(postgres_case)
    service = fixture["services"].PurgeRequestService
    request = service.create_purge_request(
        workspace_id=fixture["workspace_id"],
        requester_user_id=fixture["actor_id"],
        confirmation_phrase=f"REQUEST PURGE {fixture['workspace_slug']}",
        now=datetime(2026, 2, 1),
    )
    request_id = request.id
    lifecycle_id = request.lifecycle_id
    manifest_hash = request.manifest_hash

    # Call db.session.remove() and open an independent session for initial verification
    fixture["db"].session.remove()
    verification = postgres_case.new_session()
    try:
        stored = verification.get(fixture["models"].WorkspacePurgeRequest, request_id)
        assert stored.lifecycle_id == lifecycle_id
        assert stored.manifest_canonical_text
        assert len(stored.manifest_hash) == 64
        assert stored.manifest_hash == manifest_hash
        assert stored.target_deleted_at == datetime(2026, 1, 1)

        event_count = verification.query(fixture["models"].PurgeLifecycleEvent).filter_by(
            request_id=request_id, event_type="request_created"
        ).count()
        assert event_count == 1

        # Snapshot details from database model
        target_deleted_at = stored.target_deleted_at
        target_deleted_by_id = stored.target_deleted_by_id
    finally:
        verification.close()

    # Duplicate call with no active read transaction
    with pytest.raises(fixture["services"].PurgeRequestConflictError) as error:
        service.create_purge_request(
            workspace_id=fixture["workspace_id"],
            requester_user_id=fixture["actor_id"],
            confirmation_phrase=f"REQUEST PURGE {fixture['workspace_slug']}",
            now=datetime(2026, 2, 1),
        )
    assert getattr(error.value, "code", None) == "DUPLICATE_LIFECYCLE"

    # Open a new verification session to check final state
    verification = postgres_case.new_session()
    try:
        requests = verification.query(fixture["models"].WorkspacePurgeRequest).filter_by(workspace_id=fixture["workspace_id"]).all()
        assert len(requests) == 1
        req = requests[0]
        assert req.id == request_id
        assert req.lifecycle_id == lifecycle_id
        assert req.target_deleted_at == target_deleted_at
        assert req.target_deleted_by_id == target_deleted_by_id
        events = verification.query(fixture["models"].PurgeLifecycleEvent).filter_by(request_id=request_id).all()
        created_events = [e for e in events if e.event_type == "request_created"]
        assert len(created_events) == 1
    finally:
        verification.close()


def test_approval_event_ordering_and_manifest_immutability(postgres_case):
    from sqlalchemy import select
    from models.purge import workspace_terminal_state_table

    fixture = _base_fixture(postgres_case, include_business=False)
    service = fixture["services"].PurgeRequestService
    request = service.create_purge_request(
        workspace_id=fixture["workspace_id"], requester_user_id=fixture["actor_id"],
        confirmation_phrase=f"REQUEST PURGE {fixture['workspace_slug']}", now=datetime(2026, 2, 1),
    )
    request_id = request.id
    lifecycle_id = request.lifecycle_id

    # Load canonical text and hash from database in a bounded independent session
    fixture["db"].session.remove()
    verification = postgres_case.new_session()
    try:
        stored = verification.get(fixture["models"].WorkspacePurgeRequest, request_id)
        manifest_hash = stored.manifest_hash
        manifest_canonical_text = stored.manifest_canonical_text
    finally:
        verification.close()

    service.approve_purge_request(
        request_id=request_id, approver_user_id=fixture["executor_id"],
        confirmation_phrase=f"APPROVE PURGE {fixture['workspace_slug']} {lifecycle_id}",
        now=datetime(2026, 2, 1),
    )

    verification = postgres_case.new_session()
    try:
        stored_req = verification.get(fixture["models"].WorkspacePurgeRequest, request_id)
        assert stored_req.status == "APPROVED"
        assert stored_req.manifest_hash == manifest_hash
        assert stored_req.manifest_canonical_text == manifest_canonical_text
        events = verification.query(fixture["models"].PurgeLifecycleEvent).filter_by(
            request_id=request_id
        ).order_by(fixture["models"].PurgeLifecycleEvent.event_sequence).all()
        assert [event.event_sequence for event in events] == list(range(1, len(events) + 1))
        assert len([e for e in events if e.event_type == "request_approved"]) == 1
        assert len([e for e in events if e.event_type == "completed"]) == 0
        terminal = verification.execute(
            select(workspace_terminal_state_table).where(workspace_terminal_state_table.c.id == fixture["workspace_id"])
        ).mappings().one()
        assert terminal["purged_at"] is None
        assert terminal["purge_request_id"] is None
    finally:
        verification.close()


def test_active_legal_hold_blocks_approval(postgres_case):
    from sqlalchemy import select
    from models.purge import workspace_terminal_state_table

    fixture = _base_fixture(postgres_case)
    service = fixture["services"].PurgeRequestService
    request = service.create_purge_request(
        workspace_id=fixture["workspace_id"], requester_user_id=fixture["actor_id"],
        confirmation_phrase=f"REQUEST PURGE {fixture['workspace_slug']}", now=datetime(2026, 2, 1),
    )
    request_id = request.id
    lifecycle_id = request.lifecycle_id

    postgres_case.prepare_scoped_session()
    fixture["db"].session.add(fixture["models"].PurgeLegalHold(
        hold_id=str(uuid.uuid4()), workspace_id=fixture["workspace_id"],
        hold_type="LEGAL", source="synthetic", reason="Synthetic active hold",
        placed_by_id=fixture["actor_id"], placed_by_snapshot=fixture["actor_username"],
        status="ACTIVE", placed_at=datetime(2026, 2, 1),
    ))
    fixture["db"].session.commit()
    with pytest.raises(fixture["services"].PurgeRequestConflictError) as error:
        service.approve_purge_request(
            request_id=request_id, approver_user_id=fixture["executor_id"],
            confirmation_phrase=f"APPROVE PURGE {fixture['workspace_slug']} {lifecycle_id}",
            now=datetime(2026, 2, 1),
        )
    assert getattr(error.value, "code", None) == "LEGAL_HOLD_UNRESOLVED"
    fixture["db"].session.remove()
    verification = postgres_case.new_session()
    try:
        stored = verification.get(fixture["models"].WorkspacePurgeRequest, request_id)
        assert stored.status != "APPROVED"
        terminal = verification.execute(
            select(workspace_terminal_state_table).where(
                workspace_terminal_state_table.c.id == fixture["workspace_id"]
            )
        ).mappings().one()
        assert terminal["purged_at"] is None
        assert terminal["purge_request_id"] is None
        assert verification.query(fixture["models"].Customer).filter_by(workspace_id=fixture["workspace_id"]).count() == 1
        assert verification.query(fixture["models"].Service).filter_by(workspace_id=fixture["workspace_id"]).count() == 1
        assert verification.query(fixture["models"].Appointment).filter_by(workspace_id=fixture["workspace_id"]).count() == 1
        assert verification.query(fixture["models"].Invoice).filter_by(workspace_id=fixture["workspace_id"]).count() == 1
        assert verification.query(fixture["models"].InvoiceDetail).filter_by(invoice_id=fixture["invoice_id"]).count() == 1
        assert verification.get(fixture["models"].Setting, fixture["setting_id"]) is not None
        assert verification.get(fixture["models"].WorkspaceMember, fixture["member_id"]) is not None
        assert verification.query(fixture["models"].PurgeLifecycleEvent).filter_by(
            request_id=request_id, event_type="completed"
        ).count() == 0
        assert verification.query(fixture["models"].PurgeLegalHold).filter_by(
            workspace_id=fixture["workspace_id"], status="ACTIVE"
        ).count() == 1
    finally:
        verification.close()


def test_manifest_drift_fails_closed(postgres_case):
    from sqlalchemy import select
    from models.purge import workspace_terminal_state_table

    fixture = _base_fixture(postgres_case)
    service = fixture["services"].PurgeRequestService
    request = service.create_purge_request(
        workspace_id=fixture["workspace_id"], requester_user_id=fixture["actor_id"],
        confirmation_phrase=f"REQUEST PURGE {fixture['workspace_slug']}", now=datetime(2026, 2, 1),
    )
    request_id = request.id
    lifecycle_id = request.lifecycle_id
    manifest_hash = request.manifest_hash

    # Fetch manifest_canonical_text using an independent session
    fixture["db"].session.remove()
    verification = postgres_case.new_session()
    try:
        stored = verification.get(fixture["models"].WorkspacePurgeRequest, request_id)
        manifest_canonical_text = stored.manifest_canonical_text
    finally:
        verification.close()

    session = postgres_case.new_session()
    try:
        new_customer = fixture["models"].Customer(
            name=f"Synthetic Drift {fixture['marker']}", workspace_id=fixture["workspace_id"]
        )
        session.add(new_customer)
        session.commit()
        new_customer_id = new_customer.id
    finally:
        session.close()
    with pytest.raises(fixture["services"].PurgeRequestConflictError) as error:
        service.approve_purge_request(
            request_id=request_id, approver_user_id=fixture["executor_id"],
            confirmation_phrase=f"APPROVE PURGE {fixture['workspace_slug']} {lifecycle_id}",
            now=datetime(2026, 2, 1),
        )
    assert getattr(error.value, "code", None) == "MANIFEST_MISMATCH"
    fixture["db"].session.remove()
    verification = postgres_case.new_session()
    try:
        stored = verification.get(fixture["models"].WorkspacePurgeRequest, request_id)
        assert stored.status != "APPROVED"
        assert stored.manifest_hash == manifest_hash
        assert stored.manifest_canonical_text == manifest_canonical_text
        assert verification.query(fixture["models"].Customer).filter_by(id=new_customer_id).count() == 1
        terminal = verification.execute(
            select(workspace_terminal_state_table).where(workspace_terminal_state_table.c.id == fixture["workspace_id"])
        ).mappings().one()
        assert terminal["purged_at"] is None
        assert terminal["purge_request_id"] is None
    finally:
        verification.close()


def test_restore_invalidates_request(postgres_case):
    from sqlalchemy import select
    from models.purge import workspace_terminal_state_table

    fixture = _base_fixture(postgres_case, include_business=False)
    request_service = fixture["services"].PurgeRequestService
    request = request_service.create_purge_request(
        workspace_id=fixture["workspace_id"], requester_user_id=fixture["actor_id"],
        confirmation_phrase=f"REQUEST PURGE {fixture['workspace_slug']}", now=datetime(2026, 2, 1),
    )
    request_id = request.id
    postgres_case.prepare_scoped_session()
    fixture["services"].UserService.restore_owner_workspace(fixture["actor"], fixture["owner_id"])
    fixture["db"].session.remove()
    verification = postgres_case.new_session()
    try:
        restored_workspace = verification.get(fixture["models"].Workspace, fixture["workspace_id"])
        stored = verification.get(fixture["models"].WorkspacePurgeRequest, request_id)
        assert restored_workspace.deleted_at is None
        assert restored_workspace.deleted_by_id is None
        assert stored.status == "PENDING_APPROVAL"
        assert stored.invalidated_by_restore is True
        assert stored.invalidated_at is not None
        terminal = verification.execute(
            select(workspace_terminal_state_table).where(workspace_terminal_state_table.c.id == fixture["workspace_id"])
        ).mappings().one()
        assert terminal["purged_at"] is None
        assert terminal["purge_request_id"] is None

        # Verify the original synthetic audit row survives by exact workspace_id and unique description/marker
        original_audits = verification.query(fixture["models"].ActivityLog).filter_by(
            workspace_id=fixture["workspace_id"],
            description=fixture["audit_description"]
        ).all()
        assert len(original_audits) == 1

        # Assert restore activity log entry separately using exact action/module contract
        restore_logs = verification.query(fixture["models"].ActivityLog).filter_by(
            module="Users",
            action="RESTORE_OWNER_WORKSPACE",
            reference_id=fixture["owner_id"]
        ).all()
        assert len(restore_logs) == 1

        events = verification.query(fixture["models"].PurgeLifecycleEvent).filter_by(
            request_id=request_id
        ).order_by(fixture["models"].PurgeLifecycleEvent.event_sequence).all()
        assert len(events) == 2
        assert events[0].event_type == "request_created"
        assert events[1].event_type == "manifest_invalidated"
        assert events[1].status_before == "PENDING_APPROVAL"
        assert events[1].status_after == "PENDING_APPROVAL"
    finally:
        verification.close()


def test_execution_success_preserves_audit_and_terminal_tombstone(postgres_case):
    from sqlalchemy import select
    from models.purge import workspace_terminal_state_table

    fixture = _base_fixture(postgres_case)
    request_service = fixture["services"].PurgeRequestService
    purge_service = fixture["services"].PurgeService
    approver_user_id = fixture["executor_id"]
    executor_user_id, executor_password = _distinct_execution_actor(fixture)
    request = request_service.create_purge_request(
        workspace_id=fixture["workspace_id"], requester_user_id=fixture["actor_id"],
        confirmation_phrase=f"REQUEST PURGE {fixture['workspace_slug']}", now=datetime(2026, 2, 1),
    )
    request_id = request.id
    lifecycle_id = request.lifecycle_id

    request_service.approve_purge_request(
        request_id=request_id, approver_user_id=approver_user_id,
        confirmation_phrase=f"APPROVE PURGE {fixture['workspace_slug']} {lifecycle_id}", now=datetime(2026, 2, 1),
    )
    issuance = fixture["services"].PurgeReauthService.issue_local_authorization(
        purge_request_id=request_id,
        actor_user_id=executor_user_id,
        current_password=executor_password,
    )
    execution_time = datetime(2026, 2, 2)
    fixture_ids = {
        "users": {
            fixture["actor_id"], approver_user_id, fixture["owner_id"], executor_user_id
        },
        "customer": fixture["customer_id"],
        "service": fixture["service_id"],
        "invoice": fixture["invoice_id"],
        "setting": fixture["setting_id"],
        "member": fixture["member_id"],
    }
    result = purge_service.execute_workspace_purge(
        request_id=request_id, workspace_id=fixture["workspace_id"],
        executor_user_id=executor_user_id,
        authorization_generation=issuance.generation,
        authorization_nonce=issuance.raw_nonce,
        now=execution_time,
    )
    assert result.status == "COMPLETED"
    fixture["db"].session.remove()
    verification = postgres_case.new_session()
    try:
        assert verification.query(fixture["models"].User).filter(fixture["models"].User.id.in_(fixture_ids["users"])).count() == 4
        assert verification.query(fixture["models"].User).count() == 4
        assert verification.query(fixture["models"].ActivityLog).filter_by(description=fixture["audit_description"]).count() == 1
        assert verification.query(fixture["models"].Customer).filter_by(workspace_id=fixture["workspace_id"]).count() == 0
        assert verification.query(fixture["models"].Service).filter_by(workspace_id=fixture["workspace_id"]).count() == 0
        assert verification.query(fixture["models"].Appointment).filter_by(workspace_id=fixture["workspace_id"]).count() == 0
        assert verification.query(fixture["models"].Invoice).filter_by(workspace_id=fixture["workspace_id"]).count() == 0
        assert verification.query(fixture["models"].InvoiceDetail).filter_by(invoice_id=fixture_ids["invoice"]).count() == 0
        assert verification.get(fixture["models"].Setting, fixture_ids["setting"]) is None
        assert verification.get(fixture["models"].WorkspaceMember, fixture_ids["member"]) is None
        stored = verification.get(fixture["models"].WorkspacePurgeRequest, request_id)
        workspace = verification.get(fixture["models"].Workspace, fixture["workspace_id"])
        assert stored.status == "COMPLETED"
        assert stored.completed_at == execution_time
        assert workspace.deleted_at == datetime(2026, 1, 1)
        assert workspace.deleted_by_id == fixture["actor_id"]
        terminal = verification.execute(
            select(workspace_terminal_state_table).where(
                workspace_terminal_state_table.c.id == fixture["workspace_id"]
            )
        ).mappings().one()
        assert terminal["purged_at"] == execution_time
        assert terminal["purge_request_id"] == request_id
        assert verification.query(fixture["models"].PurgeLifecycleEvent).filter_by(
            request_id=request_id, event_type="completed"
        ).count() == 1
        events = verification.query(fixture["models"].PurgeLifecycleEvent).filter_by(request_id=request_id).order_by(
            fixture["models"].PurgeLifecycleEvent.event_sequence
        ).all()
        assert [event.event_sequence for event in events] == list(range(1, len(events) + 1))
    finally:
        verification.close()


def test_execute_route_runs_real_workspace_purge_end_to_end(postgres_case):
    from sqlalchemy import select
    from models.purge import workspace_terminal_state_table
    from tests.postgresql.rehearsal_runtime import login_test_client_with_csrf

    runtime = postgres_case
    fixture = _base_fixture(runtime)
    models = fixture["models"]
    services = fixture["services"]
    application = runtime.app
    previous_ui_flag = application.config.get("PERMANENT_PURGE_UI_ENABLED")
    previous_execution_flag = application.config.get("PERMANENT_PURGE_EXECUTION_ENABLED")

    unrelated_workspace = models.Workspace(
        name=f"Unrelated Workspace {fixture['marker']}",
        slug=f"unrelated-{fixture['marker']}",
        status="active",
    )
    runtime.db.session.add(unrelated_workspace)
    runtime.db.session.flush()
    unrelated_customer = models.Customer(
        name=f"Unrelated Customer {fixture['marker']}",
        workspace_id=unrelated_workspace.id,
    )
    unrelated_service = models.Service(
        name=f"Unrelated Service {fixture['marker']}",
        price=200,
        workspace_id=unrelated_workspace.id,
    )
    runtime.db.session.add_all([unrelated_customer, unrelated_service])
    runtime.db.session.flush()
    unrelated_workspace_id = unrelated_workspace.id
    unrelated_customer_id = unrelated_customer.id
    unrelated_service_id = unrelated_service.id
    runtime.db.session.commit()

    request_service = services.PurgeRequestService
    request = request_service.create_purge_request(
        workspace_id=fixture["workspace_id"],
        requester_user_id=fixture["actor_id"],
        confirmation_phrase=f"REQUEST PURGE {fixture['workspace_slug']}",
        now=datetime(2026, 2, 1),
    )
    request_service.approve_purge_request(
        request_id=request.id,
        approver_user_id=fixture["actor_id"],
        confirmation_phrase=f"APPROVE PURGE {fixture['workspace_slug']} {request.lifecycle_id}",
        now=datetime(2026, 2, 1),
    )

    application.config["PERMANENT_PURGE_UI_ENABLED"] = True
    application.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
    client = application.test_client()
    try:
        login_response, csrf_token = login_test_client_with_csrf(
            client,
            fixture["actor"].username,
            f"synthetic-{fixture['marker']}",
        )
        assert login_response.status_code == 200
        assert login_response.get_json()["success"] is True
        assert csrf_token

        reauth_response = client.post(
            f"/approval/purge-requests/{request.id}/reauth",
            data={"csrf_token": csrf_token, "current_password": f"synthetic-{fixture['marker']}"},
        )
        assert reauth_response.status_code == 302

        with client.session_transaction() as session_data:
            execute_csrf_token = session_data.get("_csrf_token")
        assert execute_csrf_token

        execute_response = client.post(
            f"/approval/purge-requests/{request.id}/execute",
            data={
                "csrf_token": execute_csrf_token,
                "confirmation_phrase": f"PURGE WORKSPACE {fixture['workspace_id']} REQUEST {request.id}",
            },
            follow_redirects=True,
        )
        assert execute_response.status_code == 200
        assert f"Purge request {request.id} completed." in execute_response.get_data(as_text=True)
        assert "Purge execution failed" not in execute_response.get_data(as_text=True)
    finally:
        runtime.db.session.remove()
        application.config["PERMANENT_PURGE_UI_ENABLED"] = previous_ui_flag
        application.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = previous_execution_flag

    verification = runtime.new_session()
    try:
        stored_request = verification.get(models.WorkspacePurgeRequest, request.id)
        target_workspace = verification.get(models.Workspace, fixture["workspace_id"])
        terminal = verification.execute(
            select(workspace_terminal_state_table).where(
                workspace_terminal_state_table.c.id == fixture["workspace_id"]
            )
        ).mappings().one()
        assert stored_request.status == "COMPLETED"
        assert stored_request.completed_at is not None
        assert terminal["purged_at"] is not None
        assert terminal["purge_request_id"] == request.id
        assert target_workspace is not None
        assert verification.query(models.Customer).filter_by(workspace_id=fixture["workspace_id"]).count() == 0
        assert verification.query(models.Service).filter_by(workspace_id=fixture["workspace_id"]).count() == 0
        assert verification.query(models.Appointment).filter_by(workspace_id=fixture["workspace_id"]).count() == 0
        assert verification.query(models.Invoice).filter_by(workspace_id=fixture["workspace_id"]).count() == 0
        assert verification.query(models.InvoiceDetail).join(
            models.Invoice, models.InvoiceDetail.invoice_id == models.Invoice.id
        ).filter(models.Invoice.workspace_id == fixture["workspace_id"]).count() == 0
        assert verification.query(models.WorkspaceMember).filter_by(workspace_id=fixture["workspace_id"]).count() == 0
        assert verification.query(models.Setting).filter_by(workspace_id=fixture["workspace_id"]).count() == 0
        assert verification.query(models.Workspace).filter_by(id=fixture["workspace_id"]).count() == 1
        assert verification.query(models.WorkspacePurgeRequest).filter_by(id=request.id).count() == 1
        assert verification.query(models.PurgeLifecycleEvent).filter_by(request_id=request.id).count() >= 1
        assert verification.get(models.Customer, unrelated_customer_id) is not None
        assert verification.get(models.Service, unrelated_service_id) is not None
        assert verification.get(models.Workspace, unrelated_workspace_id) is not None
    finally:
        verification.close()


def test_route_e2e_cross_workspace_verification_uses_stable_scalar_ids():
    source = inspect.getsource(test_execute_route_runs_real_workspace_purge_end_to_end)
    after_session_remove = source.split("runtime.db.session.remove()", 1)[1]

    assert "unrelated_workspace_id = unrelated_workspace.id" in source
    assert "unrelated_customer_id = unrelated_customer.id" in source
    assert "unrelated_service_id = unrelated_service.id" in source
    assert "verification.get(models.Customer, unrelated_customer_id)" in after_session_remove
    assert "verification.get(models.Service, unrelated_service_id)" in after_session_remove
    assert "verification.get(models.Workspace, unrelated_workspace_id)" in after_session_remove
    assert "unrelated_workspace." not in after_session_remove
    assert "unrelated_customer." not in after_session_remove
    assert "unrelated_service." not in after_session_remove
    assert "login_test_client_with_csrf" in source
    assert "execute_purge_request" not in source
    assert "PurgeService.execute_workspace_purge" not in source


def test_direct_execution_reauth_uses_current_production_api_signature():
    success_source = inspect.getsource(
        test_execution_success_preserves_audit_and_terminal_tombstone
    )
    rollback_source = inspect.getsource(test_execution_rolls_back_after_mutation)
    for source in (success_source, rollback_source):
        assert "purge_request_id=request_id" in source
        assert "issue_local_authorization(\n        request_id=" not in source
        assert "issue_local_authorization(\n            request_id=" not in source
        assert "authorization_generation=issuance.generation" in source
        assert "authorization_nonce=issuance.raw_nonce" in source

    signature_source = (
        Path(__file__).parents[2] / "services" / "purge_reauth_service.py"
    ).read_text(encoding="utf-8")
    assert "def issue_local_authorization(purge_request_id, actor_user_id, current_password)" in signature_source


def test_direct_execution_tests_support_single_and_distinct_eligible_actors():
    helper_source = inspect.getsource(_distinct_execution_actor)
    assert 'role="APPROVAL_OWNER"' in helper_source
    assert 'approval_status="active"' in helper_source
    assert "is_active=True" in helper_source
    assert "executor.set_password(password)" in helper_source
    assert "db.session.commit()" in helper_source
    assert "return executor.id, password" in helper_source
    assert "db.session.flush()\n    return executor.id" not in helper_source

    service_source = (Path(__file__).parents[2] / "services" / "purge_service.py").read_text(encoding="utf-8")
    reauth_source = (Path(__file__).parents[2] / "services" / "purge_reauth_service.py").read_text(encoding="utf-8")
    assert "PurgeActorSeparationError" in service_source
    assert "is_approval_owner(actor)" in service_source
    assert "len(set(ids)) != 3" not in reauth_source
    assert "request.requested_by_id == request.approved_by_id" not in reauth_source

    for function in (
        test_execution_success_preserves_audit_and_terminal_tombstone,
        test_execution_rolls_back_after_mutation,
    ):
        source = inspect.getsource(function)
        assert "approver_user_id = fixture[\"executor_id\"]" in source
        assert "executor_user_id, executor_password = _distinct_execution_actor(fixture)" in source
        assert "approver_user_id=approver_user_id" in source
        assert "actor_user_id=executor_user_id" in source
        assert "executor_user_id=executor_user_id" in source
        assert "executor_user_id=fixture[\"executor_id\"]" not in source
        assert "executor_user_id != fixture[\"actor_id\"]" not in source

    rollback_source = inspect.getsource(test_execution_rolls_back_after_mutation)
    assert "baseline_user_ids =" in rollback_source
    assert "post_rollback_user_ids =" in rollback_source
    assert "post_rollback_user_ids == baseline_user_ids" in rollback_source
    assert "verification.get(fixture[\"models\"].User, executor_user_id) is not None" in rollback_source
    assert "verification.query(fixture[\"models\"].User).count() == 3" not in rollback_source


def test_execution_rolls_back_after_mutation(postgres_case, monkeypatch):
    from sqlalchemy import select, text
    from models.purge import workspace_terminal_state_table

    fixture = _base_fixture(postgres_case)
    request_service = fixture["services"].PurgeRequestService
    purge_service = fixture["services"].PurgeService
    approver_user_id = fixture["executor_id"]
    executor_user_id, executor_password = _distinct_execution_actor(fixture)
    baseline_user_ids = {
        user_id
        for (user_id,) in fixture["db"].session.query(fixture["models"].User.id).all()
    }
    request = request_service.create_purge_request(
        workspace_id=fixture["workspace_id"], requester_user_id=fixture["actor_id"],
        confirmation_phrase=f"REQUEST PURGE {fixture['workspace_slug']}", now=datetime(2026, 2, 1),
    )
    request_id = request.id
    lifecycle_id = request.lifecycle_id

    request_service.approve_purge_request(
        request_id=request_id, approver_user_id=approver_user_id,
        confirmation_phrase=f"APPROVE PURGE {fixture['workspace_slug']} {lifecycle_id}", now=datetime(2026, 2, 1),
    )
    issuance = fixture["services"].PurgeReauthService.issue_local_authorization(
        purge_request_id=request_id,
        actor_user_id=executor_user_id,
        current_password=executor_password,
    )
    original_delete = purge_service._delete_exact_rows

    def delete_then_fail(*args, **kwargs):
        original_delete(*args, **kwargs)
        raise RuntimeError("synthetic rollback after mutation")

    monkeypatch.setattr(purge_service, "_delete_exact_rows", delete_then_fail)
    with pytest.raises(fixture["services"].PurgeExecutionError):
        purge_service.execute_workspace_purge(
            request_id=request_id, workspace_id=fixture["workspace_id"],
            executor_user_id=executor_user_id,
            authorization_generation=issuance.generation,
            authorization_nonce=issuance.raw_nonce,
            now=datetime(2026, 2, 2),
        )
    fixture["db"].session.remove()
    verification = postgres_case.new_session()
    try:
        assert verification.query(fixture["models"].Customer).filter_by(workspace_id=fixture["workspace_id"]).count() == 1
        assert verification.query(fixture["models"].Service).filter_by(workspace_id=fixture["workspace_id"]).count() == 1
        assert verification.query(fixture["models"].Appointment).filter_by(workspace_id=fixture["workspace_id"]).count() == 1
        assert verification.query(fixture["models"].Invoice).filter_by(workspace_id=fixture["workspace_id"]).count() == 1
        assert verification.query(fixture["models"].InvoiceDetail).filter_by(invoice_id=fixture["invoice_id"]).count() == 1
        assert verification.get(fixture["models"].Setting, fixture["setting_id"]) is not None
        assert verification.get(fixture["models"].WorkspaceMember, fixture["member_id"]) is not None
        post_rollback_user_ids = {
            user_id
            for (user_id,) in verification.query(fixture["models"].User.id).all()
        }
        assert post_rollback_user_ids == baseline_user_ids
        assert verification.get(fixture["models"].User, executor_user_id) is not None
        # Verify the original synthetic audit row survives using exact workspace_id and unique description
        original_audits = verification.query(fixture["models"].ActivityLog).filter_by(
            workspace_id=fixture["workspace_id"],
            description=fixture["audit_description"]
        ).all()
        assert len(original_audits) == 1
        stored = verification.get(fixture["models"].WorkspacePurgeRequest, request_id)
        assert stored.status == "FAILED"
        terminal = verification.execute(
            select(workspace_terminal_state_table).where(
                workspace_terminal_state_table.c.id == fixture["workspace_id"]
            )
        ).mappings().one()
        assert terminal["purged_at"] is None
        assert terminal["purge_request_id"] is None
        assert verification.query(fixture["models"].PurgeLifecycleEvent).filter_by(
            request_id=request_id, event_type="completed"
        ).count() == 0
        assert verification.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        verification.close()


def test_logo_reference_blocks_without_filesystem_operation(postgres_case):
    fixture = _base_fixture(postgres_case, include_business=False, logo="logos/synthetic.png")
    with pytest.raises(fixture["services"].PurgeRequestConflictError) as error:
        fixture["services"].PurgeRequestService.create_purge_request(
            workspace_id=fixture["workspace_id"], requester_user_id=fixture["actor_id"],
            confirmation_phrase=f"REQUEST PURGE {fixture['workspace_slug']}", now=datetime(2026, 2, 1),
        )
    assert getattr(error.value, "code", None) == "WORKSPACE_LOGO_PRESENT"
