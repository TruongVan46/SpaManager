from tests.session_helpers import set_authenticated_session
from datetime import datetime
from pathlib import Path
import re
import uuid

import pytest

from core.auth.constants import AUTH_SESSION_KEY


pytestmark = pytest.mark.postgres_rehearsal


def _activity_log_service():
    from services.activity_log_service import ActivityLogService

    return ActivityLogService


def _recycle_bin_service():
    from services.recycle_bin_service import RecycleBinService

    return RecycleBinService


@pytest.fixture
def recycle_case(postgres_service_session_timeouts, postgres_runtime):
    postgres_runtime.reset_database()
    try:
        yield postgres_runtime
    finally:
        postgres_runtime.reset_database()


def _seed(runtime, *, with_dependencies=True):
    models = runtime.models
    db = runtime.db
    runtime.prepare_scoped_session()
    marker = uuid.uuid4().hex[:12]

    owner = models.User(
        username=f"recycle_owner_{marker}",
        email=f"recycle_owner_{marker}@invalid.test",
        full_name="Recycle Owner",
        role="OWNER",
        approval_status="active",
        is_active=True,
    )
    admin = models.User(
        username=f"recycle_admin_{marker}",
        email=f"recycle_admin_{marker}@invalid.test",
        full_name="Recycle Admin",
        role="ADMIN",
        approval_status="active",
        is_active=True,
    )
    staff = models.User(
        username=f"recycle_staff_{marker}",
        email=f"recycle_staff_{marker}@invalid.test",
        full_name="Recycle Staff",
        role="STAFF",
        approval_status="active",
        is_active=True,
    )
    for user in (owner, admin, staff):
        user.set_password(f"recycle-{marker}")

    workspace = models.Workspace(
        name=f"Recycle Workspace {marker}",
        slug=f"recycle-{marker}",
        status="active",
    )
    other_workspace = models.Workspace(
        name=f"Other Recycle Workspace {marker}",
        slug=f"other-recycle-{marker}",
        status="active",
    )
    db.session.add_all([owner, admin, staff, workspace, other_workspace])
    db.session.flush()
    db.session.add_all([
        models.WorkspaceMember(
            workspace_id=workspace.id, user_id=owner.id, role="owner", status="active"
        ),
        models.WorkspaceMember(
            workspace_id=workspace.id, user_id=admin.id, role="admin", status="active"
        ),
        models.WorkspaceMember(
            workspace_id=workspace.id, user_id=staff.id, role="staff", status="active"
        ),
        models.WorkspaceMember(
            workspace_id=other_workspace.id, user_id=owner.id, role="owner", status="active"
        ),
    ])

    customer = models.Customer(
        name=f"Recycle Customer {marker}", workspace_id=workspace.id
    )
    service = models.Service(
        name=f"Recycle Service {marker}", price=100, workspace_id=workspace.id
    )
    other_customer = models.Customer(
        name=f"Other Customer {marker}", workspace_id=other_workspace.id
    )
    other_service = models.Service(
        name=f"Other Service {marker}", price=100, workspace_id=other_workspace.id
    )
    db.session.add_all([customer, service, other_customer, other_service])
    db.session.flush()

    invoice = detail = appointment = None
    other_invoice = models.Invoice(
        customer_id=other_customer.id, total_amount=100, workspace_id=other_workspace.id
    )
    db.session.add(other_invoice)
    if with_dependencies:
        invoice = models.Invoice(
            customer_id=customer.id, total_amount=100, workspace_id=workspace.id
        )
        db.session.add(invoice)
        db.session.flush()
        detail = models.InvoiceDetail(
            invoice_id=invoice.id, service_id=service.id, price=100, quantity=1
        )
        appointment = models.Appointment(
            customer_id=customer.id,
            service_id=service.id,
            appointment_time=datetime(2026, 7, 15, 9, 0),
            workspace_id=workspace.id,
        )
        db.session.add_all([detail, appointment])
    db.session.commit()
    return {
        "marker": marker,
        "owner_id": owner.id,
        "admin_id": admin.id,
        "staff_id": staff.id,
        "workspace_id": workspace.id,
        "other_workspace_id": other_workspace.id,
        "customer_id": customer.id,
        "service_id": service.id,
        "other_customer_id": other_customer.id,
        "other_service_id": other_service.id,
        "invoice_id": invoice.id if invoice else None,
        "other_invoice_id": other_invoice.id,
        "detail_id": detail.id if detail else None,
        "appointment_id": appointment.id if appointment else None,
        "with_dependencies": with_dependencies,
    }


def _soft_delete(runtime, model, item_id, actor="recycle-owner"):
    runtime.prepare_scoped_session()
    record = runtime.db.session.get(model, item_id)
    record.deleted_at = datetime(2026, 7, 15, 10, 0)
    record.deleted_by = actor
    runtime.db.session.commit()


def _workspace_session(client, fixture, user_id):
    with client.session_transaction() as session:
        set_authenticated_session(session, user_id)
        session["current_workspace_id"] = fixture["workspace_id"]
        session["_enable_workspace_isolation"] = True


def _csrf_token(client):
    response = client.get("/recycle-bin")
    match = re.search(r'name="csrf-token" content="([^"]+)"', response.get_data(as_text=True))
    assert match is not None
    return match.group(1)


def _post(client, item_type, item_id, csrf=True):
    headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    if csrf:
        headers["X-CSRFToken"] = _csrf_token(client)
    return client.post(
        f"/recycle-bin/delete/{item_type}/{item_id}",
        headers=headers,
    )


def _service_call(runtime, fixture, item_type, item_id, workspace_id=None):
    with runtime.app.test_request_context():
        from flask import session
        set_authenticated_session(session, fixture["owner_id"])
        session["current_workspace_id"] = workspace_id or fixture["workspace_id"]
        session["_enable_workspace_isolation"] = True
        runtime.prepare_scoped_session()
        return _recycle_bin_service().permanent_delete(
            item_type, item_id, actor="recycle-owner"
        )


def _assert_audit(runtime, item_type, item_id):
    session = runtime.new_session()
    try:
        audit = session.query(runtime.models.ActivityLog).filter_by(
            action=_activity_log_service().ACTION_PERMANENT_DELETE,
            module=item_type,
            reference_id=item_id,
        ).one()
        assert str(item_id) in audit.description
    finally:
        session.close()


def test_appointment_active_record_is_rejected_before_mutation(recycle_case):
    fixture = _seed(recycle_case)
    with pytest.raises(Exception):
        _service_call(recycle_case, fixture, "Appointment", fixture["appointment_id"])
    assert recycle_case.db.session.get(recycle_case.models.Appointment, fixture["appointment_id"]) is not None


def test_appointment_soft_deleted_record_is_hard_deleted_and_related_rows_remain(recycle_case):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Appointment, fixture["appointment_id"])
    with recycle_case.app.test_request_context():
        with recycle_case.app.test_client().session_transaction() as session:
            set_authenticated_session(session, fixture["owner_id"])
            session["current_workspace_id"] = fixture["workspace_id"]
            session["_enable_workspace_isolation"] = True
        recycle_case.prepare_scoped_session()
        result = _service_call(recycle_case, fixture, "Appointment", fixture["appointment_id"])
    assert result["item_type"] == "Appointment"
    verification = recycle_case.new_session()
    try:
        assert verification.get(recycle_case.models.Appointment, fixture["appointment_id"]) is None
        assert verification.get(recycle_case.models.Customer, fixture["customer_id"]) is not None
        assert verification.get(recycle_case.models.Service, fixture["service_id"]) is not None
    finally:
        verification.close()
    _assert_audit(recycle_case, "Appointment", fixture["appointment_id"])


def test_appointment_audit_failure_rolls_back(recycle_case, monkeypatch):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Appointment, fixture["appointment_id"])
    monkeypatch.setattr(
        _activity_log_service(),
        "write_log",
        lambda *args, **kwargs: False,
    )
    recycle_case.prepare_scoped_session()
    with pytest.raises(Exception):
        _service_call(recycle_case, fixture, "Appointment", fixture["appointment_id"])
    assert recycle_case.db.session.get(recycle_case.models.Appointment, fixture["appointment_id"]) is not None


def test_appointment_cross_workspace_id_fails_closed(recycle_case):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Appointment, fixture["appointment_id"])
    recycle_case.prepare_scoped_session()
    with pytest.raises(Exception):
        _service_call(
            recycle_case, fixture, "Appointment", fixture["appointment_id"],
            workspace_id=fixture["other_workspace_id"],
        )


def test_invoice_active_record_is_rejected(recycle_case):
    fixture = _seed(recycle_case)
    with pytest.raises(Exception):
        _service_call(recycle_case, fixture, "Invoice", fixture["invoice_id"])


def test_invoice_success_deletes_details_atomically_and_preserves_related_rows(recycle_case):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Invoice, fixture["invoice_id"])
    recycle_case.prepare_scoped_session()
    with recycle_case.app.test_request_context():
        from flask import session
        set_authenticated_session(session, fixture["owner_id"])
        session["current_workspace_id"] = fixture["workspace_id"]
        session["_enable_workspace_isolation"] = True
        result = _service_call(recycle_case, fixture, "Invoice", fixture["invoice_id"])
    verification = recycle_case.new_session()
    try:
        assert verification.get(recycle_case.models.Invoice, fixture["invoice_id"]) is None
        assert verification.get(recycle_case.models.InvoiceDetail, fixture["detail_id"]) is None
        assert verification.get(recycle_case.models.Customer, fixture["customer_id"]) is not None
        assert verification.get(recycle_case.models.Service, fixture["service_id"]) is not None
    finally:
        verification.close()
    assert result["item_type"] == "Invoice"
    _assert_audit(recycle_case, "Invoice", fixture["invoice_id"])


def test_invoice_audit_failure_rolls_back_invoice_and_details(recycle_case, monkeypatch):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Invoice, fixture["invoice_id"])
    monkeypatch.setattr(
        _activity_log_service(),
        "write_log",
        lambda *args, **kwargs: False,
    )
    recycle_case.prepare_scoped_session()
    with pytest.raises(Exception):
        _service_call(recycle_case, fixture, "Invoice", fixture["invoice_id"])
    assert recycle_case.db.session.get(recycle_case.models.Invoice, fixture["invoice_id"]) is not None
    assert recycle_case.db.session.get(recycle_case.models.InvoiceDetail, fixture["detail_id"]) is not None


def test_invoice_cross_workspace_id_fails_closed(recycle_case):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Invoice, fixture["invoice_id"])
    recycle_case.prepare_scoped_session()
    with pytest.raises(Exception):
        _service_call(
            recycle_case, fixture, "Invoice", fixture["invoice_id"],
            workspace_id=fixture["other_workspace_id"],
        )


def test_customer_without_dependencies_is_deleted_and_audited(recycle_case):
    fixture = _seed(recycle_case, with_dependencies=False)
    customer = recycle_case.db.session.get(recycle_case.models.Customer, fixture["customer_id"])
    customer.deleted_at = datetime(2026, 7, 15, 10, 0)
    customer.deleted_by = "recycle-owner"
    recycle_case.db.session.commit()
    _service_call(recycle_case, fixture, "Customer", fixture["customer_id"])
    verification = recycle_case.new_session()
    try:
        assert verification.get(recycle_case.models.Customer, fixture["customer_id"]) is None
    finally:
        verification.close()
    _assert_audit(recycle_case, "Customer", fixture["customer_id"])


def test_customer_appointment_dependency_blocks_before_mutation(recycle_case):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Customer, fixture["customer_id"])
    status = _recycle_bin_service().get_permanent_delete_status(
        "Customer", fixture["customer_id"], fixture["workspace_id"]
    )
    assert status["can_delete"] is False
    assert status["appointment_count"] == 1
    assert "1" in status["reason"]


def test_customer_invoice_dependency_blocks_before_mutation(recycle_case):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Customer, fixture["customer_id"])
    status = _recycle_bin_service().get_permanent_delete_status(
        "Customer", fixture["customer_id"], fixture["workspace_id"]
    )
    assert status["invoice_count"] == 1
    assert status["can_delete"] is False


def test_customer_audit_failure_rolls_back(recycle_case, monkeypatch):
    fixture = _seed(recycle_case, with_dependencies=False)
    _soft_delete(recycle_case, recycle_case.models.Customer, fixture["customer_id"])
    monkeypatch.setattr(
        _activity_log_service(),
        "write_log",
        lambda *args, **kwargs: False,
    )
    with pytest.raises(Exception):
        _service_call(recycle_case, fixture, "Customer", fixture["customer_id"])
    assert recycle_case.db.session.get(recycle_case.models.Customer, fixture["customer_id"]) is not None


def test_customer_cross_workspace_id_fails_closed(recycle_case):
    fixture = _seed(recycle_case, with_dependencies=False)
    _soft_delete(recycle_case, recycle_case.models.Customer, fixture["customer_id"])
    recycle_case.prepare_scoped_session()
    with pytest.raises(Exception):
        _service_call(
            recycle_case, fixture, "Customer", fixture["customer_id"],
            workspace_id=fixture["other_workspace_id"],
        )


def test_service_without_dependencies_is_deleted_and_audited(recycle_case):
    fixture = _seed(recycle_case, with_dependencies=False)
    _soft_delete(recycle_case, recycle_case.models.Service, fixture["service_id"])
    _service_call(recycle_case, fixture, "Service", fixture["service_id"])
    verification = recycle_case.new_session()
    try:
        assert verification.get(recycle_case.models.Service, fixture["service_id"]) is None
    finally:
        verification.close()
    _assert_audit(recycle_case, "Service", fixture["service_id"])


def test_service_appointment_dependency_blocks_before_mutation(recycle_case):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Service, fixture["service_id"])
    status = _recycle_bin_service().get_permanent_delete_status(
        "Service", fixture["service_id"], fixture["workspace_id"]
    )
    assert status["appointment_count"] == 1
    assert status["can_delete"] is False


def test_service_invoice_detail_dependency_blocks_before_mutation(recycle_case):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Service, fixture["service_id"])
    status = _recycle_bin_service().get_permanent_delete_status(
        "Service", fixture["service_id"], fixture["workspace_id"]
    )
    assert status["invoice_detail_count"] == 1
    assert status["can_delete"] is False


def test_service_audit_failure_rolls_back(recycle_case, monkeypatch):
    fixture = _seed(recycle_case, with_dependencies=False)
    _soft_delete(recycle_case, recycle_case.models.Service, fixture["service_id"])
    monkeypatch.setattr(
        _activity_log_service(),
        "write_log",
        lambda *args, **kwargs: False,
    )
    with pytest.raises(Exception):
        _service_call(recycle_case, fixture, "Service", fixture["service_id"])
    assert recycle_case.db.session.get(recycle_case.models.Service, fixture["service_id"]) is not None


def test_service_cross_workspace_id_fails_closed(recycle_case):
    fixture = _seed(recycle_case, with_dependencies=False)
    _soft_delete(recycle_case, recycle_case.models.Service, fixture["service_id"])
    recycle_case.prepare_scoped_session()
    with pytest.raises(Exception):
        _service_call(
            recycle_case, fixture, "Service", fixture["service_id"],
            workspace_id=fixture["other_workspace_id"],
        )


def test_route_csrf_and_authorization_contract(recycle_case):
    fixture = _seed(recycle_case, with_dependencies=False)
    _soft_delete(recycle_case, recycle_case.models.Customer, fixture["customer_id"])
    client = recycle_case.app.test_client()
    assert _post(client, "Customer", fixture["customer_id"], csrf=False).status_code != 200
    _workspace_session(client, fixture, fixture["staff_id"])
    assert _post(client, "Customer", fixture["customer_id"]).status_code == 403


def test_route_owner_json_success_and_audit(recycle_case):
    fixture = _seed(recycle_case, with_dependencies=False)
    _soft_delete(recycle_case, recycle_case.models.Customer, fixture["customer_id"])
    client = recycle_case.app.test_client()
    _workspace_session(client, fixture, fixture["owner_id"])
    response = _post(client, "Customer", fixture["customer_id"])
    assert response.status_code == 200
    assert response.is_json
    assert response.get_json() == {
        "success": True,
        "message": "Đã xóa vĩnh viễn bản ghi.",
        "item_type": "Customer",
        "item_id": fixture["customer_id"],
    }
    _assert_audit(recycle_case, "Customer", fixture["customer_id"])


def test_route_admin_json_success(recycle_case):
    fixture = _seed(recycle_case, with_dependencies=False)
    _soft_delete(recycle_case, recycle_case.models.Service, fixture["service_id"])
    client = recycle_case.app.test_client()
    _workspace_session(client, fixture, fixture["admin_id"])
    response = _post(client, "Service", fixture["service_id"])
    assert response.status_code == 200
    assert response.is_json
    assert response.get_json()["success"] is True


def test_route_rejects_unsupported_missing_and_active_records(recycle_case):
    fixture = _seed(recycle_case, with_dependencies=False)
    client = recycle_case.app.test_client()
    _workspace_session(client, fixture, fixture["owner_id"])
    assert _post(client, "Workspace", fixture["workspace_id"]).status_code == 404
    assert _post(client, "Customer", 999999).status_code == 404
    assert _post(client, "Customer", fixture["customer_id"]).status_code == 400


def test_route_cross_workspace_dependency_error_is_json_and_fail_closed(recycle_case):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Customer, fixture["other_customer_id"])
    client = recycle_case.app.test_client()
    _workspace_session(client, fixture, fixture["owner_id"])
    response = _post(client, "Customer", fixture["other_customer_id"])
    assert response.status_code == 404
    assert response.is_json


def test_route_dependency_error_json_preserves_target_and_dependencies(recycle_case):
    fixture = _seed(recycle_case)
    _soft_delete(recycle_case, recycle_case.models.Customer, fixture["customer_id"])
    client = recycle_case.app.test_client()
    _workspace_session(client, fixture, fixture["owner_id"])
    response = _post(client, "Customer", fixture["customer_id"])
    assert response.status_code == 400
    assert response.is_json
    payload = response.get_json()
    assert payload["success"] is False
    assert "1" in payload["message"]
    verification = recycle_case.new_session()
    try:
        assert verification.get(recycle_case.models.Customer, fixture["customer_id"]) is not None
        assert verification.get(recycle_case.models.Appointment, fixture["appointment_id"]) is not None
        assert verification.get(recycle_case.models.Invoice, fixture["invoice_id"]) is not None
    finally:
        verification.close()


def test_client_toast_contract_is_static_and_csrf_aware():
    source = Path("templates/recycle_bin/index.html").read_text(encoding="utf-8")
    assert "/recycle-bin/delete/${itemToDelete.type}/${itemToDelete.id}" in source
    assert "csrfFetch" in source
    assert "JSON.stringify({confirmation_phrase" not in source
    assert "permanent-delete-confirmation" not in source
    assert "permanent-delete-phrase" not in source
    assert ".then(response => response.json())" in source
    assert "if (!data.success)" in source
    assert "showToast(data.message" in source
    assert "Notification.success(message)" in source
    assert "Notification.error(message)" in source
    assert "flash(" not in source
