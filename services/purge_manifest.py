import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from models.appointment import Appointment
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from models.purge import WorkspacePurgeRequest
from models.service import Service
from models.setting import Setting
from models.workspace import WorkspaceMember


MANIFEST_VERSION = "purge-manifest-v1"
EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()

DESTRUCTIVE_SCOPES = (
    ("invoice_details", "DELETE", "invoice_details_via_invoices.workspace_id"),
    ("appointments", "DELETE", "appointments.workspace_id"),
    ("invoices", "DELETE", "invoices.workspace_id"),
    ("customers", "DELETE", "customers.workspace_id"),
    ("services", "DELETE", "services.workspace_id"),
    ("settings", "DELETE", "settings.workspace_id"),
    ("workspace_members", "DELETE", "workspace_members.workspace_id"),
)

PRESERVED_DISPOSITIONS = (
    ("users", "PRESERVE"),
    ("activity_logs", "PRESERVE"),
    ("workspace_purge_requests", "PRESERVE"),
    ("purge_legal_holds", "PRESERVE"),
    ("purge_lifecycle_events", "PRESERVE"),
    ("workspaces", "PRESERVE_TERMINAL_TOMBSTONE"),
)


class PurgeManifestError(ValueError):
    """Raised when a purge manifest cannot be trusted or rebuilt."""


@dataclass(frozen=True)
class PurgePlan:
    invoice_detail_ids: tuple[int, ...]
    appointment_ids: tuple[int, ...]
    invoice_ids: tuple[int, ...]
    customer_ids: tuple[int, ...]
    service_ids: tuple[int, ...]
    setting_ids: tuple[int, ...]
    workspace_member_ids: tuple[int, ...]
    user_count: int
    activity_log_count: int


def normalize_utc_timestamp(value):
    if not isinstance(value, datetime):
        raise PurgeManifestError("Purge timestamp is not a datetime.")
    if value.tzinfo is None:
        normalized = value.replace(tzinfo=timezone.utc)
    else:
        normalized = value.astimezone(timezone.utc)
    return normalized.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _positive_integer_ids(ids):
    values = list(ids)
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
        raise PurgeManifestError("Purge row IDs must be positive integers.")
    if len(values) != len(set(values)):
        raise PurgeManifestError("Purge row IDs must not contain duplicates.")
    return sorted(values)


def row_set_sha256(ids):
    canonical_ids = _positive_integer_ids(ids)
    canonical_text = "\n".join(str(value) for value in canonical_ids)
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


def _locked_rows(query, lock):
    query = query.order_by(query.column_descriptions[0]["expr"].id)
    if lock:
        query = query.with_for_update()
    return query.all()


def build_purge_plan(session, workspace, *, lock=False):
    """Capture every target ID after the caller has acquired its workspace lock."""
    invoice_rows = _locked_rows(session.query(Invoice).filter(Invoice.workspace_id == workspace.id), lock)
    invoice_ids = tuple(row.id for row in invoice_rows)
    invoice_detail_rows = []
    if invoice_ids:
        invoice_detail_query = session.query(InvoiceDetail).filter(InvoiceDetail.invoice_id.in_(invoice_ids))
        invoice_detail_rows = _locked_rows(invoice_detail_query, lock)
    appointment_rows = _locked_rows(session.query(Appointment).filter(Appointment.workspace_id == workspace.id), lock)
    customer_rows = _locked_rows(session.query(Customer).filter(Customer.workspace_id == workspace.id), lock)
    service_rows = _locked_rows(session.query(Service).filter(Service.workspace_id == workspace.id), lock)
    setting_rows = _locked_rows(session.query(Setting).filter(Setting.workspace_id == workspace.id), lock)
    member_rows = _locked_rows(session.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace.id), lock)
    from models.activity_log import ActivityLog
    from models.user import User
    return PurgePlan(
        invoice_detail_ids=tuple(row.id for row in invoice_detail_rows),
        appointment_ids=tuple(row.id for row in appointment_rows),
        invoice_ids=invoice_ids,
        customer_ids=tuple(row.id for row in customer_rows),
        service_ids=tuple(row.id for row in service_rows),
        setting_ids=tuple(row.id for row in setting_rows),
        workspace_member_ids=tuple(row.id for row in member_rows),
        user_count=session.query(User).count(),
        activity_log_count=session.query(ActivityLog).count(),
    )


def _row_set_item(table, action, scope, ids):
    canonical_ids = _positive_integer_ids(ids)
    return {
        "table": table,
        "action": action,
        "scope": scope,
        "count": len(canonical_ids),
        "row_set_sha256": row_set_sha256(canonical_ids),
    }


def _external_assets(session, workspace_id):
    logo_rows = session.query(Setting).filter(
        Setting.workspace_id == workspace_id,
        Setting.key == "spa_logo",
    ).all()
    present_logo_rows = [
        row for row in logo_rows
        if row.value is not None and (not isinstance(row.value, str) or row.value != "")
    ]
    if present_logo_rows:
        logo_state = {
            "inventory_status": "BLOCKED_PRESENT",
            "count": len(present_logo_rows),
            "row_set_sha256": row_set_sha256([row.id for row in present_logo_rows]),
        }
    else:
        logo_state = {
            "inventory_status": "RESOLVED",
            "count": 0,
            "row_set_sha256": EMPTY_DIGEST,
        }

    return [
        {"category": "workspace_logo", "ownership": "WORKSPACE", "disposition": "REQUIRE_ABSENT", **logo_state},
        {"category": "user_avatar", "ownership": "USER", "disposition": "PRESERVE", "inventory_status": "NOT_IN_PURGE_SCOPE", "count": None, "row_set_sha256": None},
        {"category": "global_backup", "ownership": "GLOBAL", "disposition": "GLOBAL_PRESERVE", "inventory_status": "NOT_IN_PURGE_SCOPE", "count": None, "row_set_sha256": None},
        {"category": "operational_log", "ownership": "GLOBAL", "disposition": "GLOBAL_PRESERVE", "inventory_status": "NOT_IN_PURGE_SCOPE", "count": None, "row_set_sha256": None},
        {"category": "transient_export_import", "ownership": "REQUEST_SCOPED", "disposition": "NOT_PERSISTENT", "inventory_status": "NOT_IN_PURGE_SCOPE", "count": None, "row_set_sha256": None},
    ]


def build_manifest_payload(session, request, workspace, purge_plan):
    if not isinstance(request, WorkspacePurgeRequest):
        raise PurgeManifestError("Invalid purge request.")
    if not isinstance(purge_plan, PurgePlan):
        raise PurgeManifestError("Locked purge plan is required.")
    if request.workspace_id != workspace.id or request.lifecycle_id is None:
        raise PurgeManifestError("Purge request and workspace do not match.")
    return {
        "manifest_version": MANIFEST_VERSION,
        "lifecycle_id": request.lifecycle_id,
        "workspace_id": workspace.id,
        "target_deleted_at": normalize_utc_timestamp(request.target_deleted_at),
        "target_deleted_by_id": request.target_deleted_by_id,
        "retention": {
            "eligible_at": normalize_utc_timestamp(request.eligible_at),
            "policy_version": request.retention_policy_version,
        },
        "destructive": [
            _row_set_item("invoice_details", "DELETE", "invoice_details_via_invoices.workspace_id", purge_plan.invoice_detail_ids),
            _row_set_item("appointments", "DELETE", "appointments.workspace_id", purge_plan.appointment_ids),
            _row_set_item("invoices", "DELETE", "invoices.workspace_id", purge_plan.invoice_ids),
            _row_set_item("customers", "DELETE", "customers.workspace_id", purge_plan.customer_ids),
            _row_set_item("services", "DELETE", "services.workspace_id", purge_plan.service_ids),
            _row_set_item("settings", "DELETE", "settings.workspace_id", purge_plan.setting_ids),
            _row_set_item("workspace_members", "DELETE", "workspace_members.workspace_id", purge_plan.workspace_member_ids),
        ],
        "preserved": [{"table": table, "disposition": disposition} for table, disposition in PRESERVED_DISPOSITIONS],
        "external_assets": _external_assets(session, workspace.id),
    }


def canonicalize_manifest(payload):
    if not isinstance(payload, dict):
        raise PurgeManifestError("Manifest payload must be an object.")
    return json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=False)


def manifest_hash(canonical_text):
    if not isinstance(canonical_text, str):
        raise PurgeManifestError("Manifest canonical text must be text.")
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


def build_manifest(session, request, workspace, purge_plan):
    canonical_text = canonicalize_manifest(build_manifest_payload(session, request, workspace, purge_plan))
    return canonical_text, manifest_hash(canonical_text)


def validate_stored_manifest(session, request, workspace, purge_plan):
    if not isinstance(request.manifest_canonical_text, str):
        raise PurgeManifestError("Stored manifest text is not valid text.")
    if request.manifest_version != MANIFEST_VERSION:
        raise PurgeManifestError("Unsupported manifest version.")
    if manifest_hash(request.manifest_canonical_text) != request.manifest_hash:
        raise PurgeManifestError("Stored manifest hash mismatch.")
    try:
        stored_payload = json.loads(request.manifest_canonical_text)
    except (TypeError, ValueError) as exc:
        raise PurgeManifestError("Stored manifest is malformed.") from exc
    if not isinstance(stored_payload, dict):
        raise PurgeManifestError("Stored manifest must be a JSON object.")
    if "request_id" in stored_payload:
        raise PurgeManifestError("request_id must not be present in manifest payload.")
    if stored_payload.get("manifest_version") != MANIFEST_VERSION:
        raise PurgeManifestError("Unsupported manifest version.")
    rebuilt_text, rebuilt_hash = build_manifest(session, request, workspace, purge_plan)
    if rebuilt_text != request.manifest_canonical_text:
        raise PurgeManifestError("Manifest scope or provenance drift detected.")
    if rebuilt_hash != request.manifest_hash:
        raise PurgeManifestError("Rebuilt manifest hash mismatch.")
    return stored_payload
