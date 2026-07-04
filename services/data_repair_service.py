from dataclasses import dataclass, field
from typing import Any

from extensions import db
from models.appointment import Appointment
from models.customer import Customer
from models.invoice import Invoice
from models.service import Service
from services.data_audit_service import run_data_consistency_audit


SAFE_REPAIR_CODES = {
    "CUSTOMER_TRIM_NAME",
    "CUSTOMER_TRIM_PHONE",
    "CUSTOMER_TRIM_EMAIL",
    "SERVICE_TRIM_NAME",
}


@dataclass
class DataRepairAction:
    code: str
    model: str
    record_id: Any
    field: str
    before: Any
    after: Any
    message: str
    safe: bool = True


@dataclass
class DataRepairSkippedIssue:
    code: str
    model: str
    record_id: Any
    field: str
    message: str
    reason: str


@dataclass
class DataRepairReport:
    mode: str
    dry_run: bool
    actions: list[DataRepairAction] = field(default_factory=list)
    skipped: list[DataRepairSkippedIssue] = field(default_factory=list)
    applied_count: int = 0

    @property
    def has_changes(self):
        return bool(self.actions)

    @property
    def repairable_actions(self):
        return len(self.actions)

    @property
    def skipped_count(self):
        return len(self.skipped)

    def to_text(self):
        lines = [
            "Data repair workflow",
            f"Mode: {self.mode}",
            f"Repairable actions: {self.repairable_actions}",
            f"Skipped issues: {self.skipped_count}",
            f"Applied: {self.applied_count}",
        ]

        for action in self.actions:
            prefix = "[DRY-RUN]" if self.dry_run else "[APPLIED]"
            lines.extend([
                "",
                f"{prefix} {action.code}",
                f"Model: {action.model}",
                f"Record: {action.record_id}",
                f"Field: {action.field}",
                f"Before: {action.before!r}",
                f"After: {action.after!r}",
            ])

        for skipped in self.skipped:
            lines.extend([
                "",
                f"[SKIPPED] {skipped.code}",
                f"Model: {skipped.model}",
                f"Record: {skipped.record_id}",
                f"Field: {skipped.field}",
                f"Reason: {skipped.reason}",
                f"Message: {skipped.message}",
            ])

        return "\n".join(lines).rstrip()


def _trimmed(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    return value.strip()


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _build_repair_report_from_audit(audit_report, db_session=None, only=None, actor="Hệ thống"):
    session = db_session or db.session
    only_filter = {item.strip().upper() for item in only or [] if item and str(item).strip()}
    report = DataRepairReport(mode="DRY-RUN", dry_run=True)

    def allowed(code):
        if not only_filter:
            return True
        upper_code = code.upper()
        for item in only_filter:
            if upper_code == item or upper_code.startswith(f"{item}_") or item in upper_code:
                return True
        return False

    for issue in audit_report.issues:
        code = issue.code
        if only_filter and code not in only_filter:
            continue

        if code == "CUSTOMER_TRIM_NAME" and allowed(code):
            customer = session.get(Customer, issue.record_id)
            if customer and isinstance(customer.name, str):
                after = customer.name.strip()
                if after != customer.name:
                    report.actions.append(DataRepairAction(code, "Customer", customer.id, "name", customer.name, after, issue.message))
            continue

        if code == "CUSTOMER_TRIM_PHONE" and allowed(code):
            customer = session.get(Customer, issue.record_id)
            if customer and isinstance(customer.phone, str):
                after = customer.phone.strip()
                if after != customer.phone:
                    report.actions.append(DataRepairAction(code, "Customer", customer.id, "phone", customer.phone, after, issue.message))
            continue

        if code == "CUSTOMER_TRIM_EMAIL" and allowed(code):
            customer = session.get(Customer, issue.record_id)
            if customer and isinstance(customer.email, str):
                after = customer.email.strip()
                if after != customer.email:
                    report.actions.append(DataRepairAction(code, "Customer", customer.id, "email", customer.email, after, issue.message))
            continue

        if code == "SERVICE_TRIM_NAME" and allowed(code):
            service = session.get(Service, issue.record_id)
            if service and isinstance(service.name, str):
                after = service.name.strip()
                if after != service.name:
                    report.actions.append(DataRepairAction(code, "Service", service.id, "name", service.name, after, issue.message))
            continue

        if code in {
            "CUSTOMER_DUPLICATE_PHONE",
            "CUSTOMER_DUPLICATE_EMAIL",
            "CUSTOMER_EMPTY_NAME",
            "SERVICE_EMPTY_NAME",
            "SERVICE_NEGATIVE_PRICE",
            "SERVICE_SOFT_DELETE_MISMATCH",
            "APPOINTMENT_MISSING_CUSTOMER",
            "APPOINTMENT_MISSING_SERVICE",
            "APPOINTMENT_EMPTY_TIME",
            "APPOINTMENT_INVALID_STATUS",
            "APPOINTMENT_SOFT_DELETE_MISMATCH",
            "APPOINTMENT_SOFT_DELETED_CUSTOMER",
            "APPOINTMENT_SOFT_DELETED_SERVICE",
            "INVOICE_MISSING_CUSTOMER",
            "INVOICE_EMPTY_DATE",
            "INVOICE_NEGATIVE_TOTAL",
            "INVOICE_INVALID_PAYMENT_METHOD",
            "INVOICE_SOFT_DELETE_MISMATCH",
            "INVOICE_SOFT_DELETED_CUSTOMER",
            "INVOICE_DETAIL_MISSING_INVOICE",
            "INVOICE_DETAIL_MISSING_SERVICE",
            "INVOICE_DETAIL_INVALID_QUANTITY",
            "INVOICE_DETAIL_NEGATIVE_PRICE",
            "INVOICE_DETAIL_NEGATIVE_AMOUNT",
            "INVOICE_DETAIL_SOFT_DELETED_SERVICE",
        }:
            report.skipped.append(
                DataRepairSkippedIssue(
                    code=code,
                    model=issue.model,
                    record_id=issue.record_id,
                    field=issue.field,
                    message=issue.message,
                    reason="Manual review required.",
                )
            )

    # One-way soft-delete repair: only fill deleted_by if deleted_at exists and deleted_by missing.
    for model, model_name in ((Customer, "Customer"), (Service, "Service"), (Appointment, "Appointment"), (Invoice, "Invoice")):
        for record in model.query.all():
            deleted_at = getattr(record, "deleted_at", None)
            deleted_by = getattr(record, "deleted_by", None)
            set_deleted_by_code = f"{model_name.upper()}_SET_DELETED_BY"
            soft_delete_mismatch_code = f"{model_name.upper()}_SOFT_DELETE_MISMATCH"
            if deleted_at and _is_blank(deleted_by) and allowed(set_deleted_by_code):
                after = actor
                if after != deleted_by:
                    report.actions.append(
                        DataRepairAction(
                            code=set_deleted_by_code,
                            model=model_name,
                            record_id=record.id,
                            field="deleted_by",
                            before=deleted_by,
                            after=after,
                            message="Bổ sung người xóa cho bản ghi soft delete hợp lệ.",
                        )
                    )
            elif deleted_by and not deleted_at and allowed(soft_delete_mismatch_code):
                report.skipped.append(
                    DataRepairSkippedIssue(
                        code=soft_delete_mismatch_code,
                        model=model_name,
                        record_id=record.id,
                        field="deleted_at/deleted_by",
                        message="Bản ghi có deleted_by nhưng thiếu deleted_at.",
                        reason="Manual review required.",
                    )
                )

    # Deduplicate in case the same record already appeared in audit warnings and direct scan.
    deduped = []
    seen = set()
    for action in report.actions:
        key = (action.code, action.model, action.record_id, action.field, action.before, action.after)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    report.actions = deduped
    return report


def plan_data_repairs(audit_report, db_session=None, only=None, actor="Hệ thống"):
    return _build_repair_report_from_audit(audit_report, db_session=db_session, only=only, actor=actor)


def apply_data_repairs(report, db_session=None):
    session = db_session or db.session
    if not report.actions:
        return report

    for action in report.actions:
        if not action.safe:
            continue
        if action.model == "Customer":
            record = session.get(Customer, action.record_id)
        elif action.model == "Service":
            record = session.get(Service, action.record_id)
        elif action.model == "Appointment":
            record = session.get(Appointment, action.record_id)
        elif action.model == "Invoice":
            record = session.get(Invoice, action.record_id)
        else:
            record = None

        if not record:
            continue

        setattr(record, action.field, action.after)
        report.applied_count += 1

    if report.applied_count:
        session.commit()
    report.dry_run = False
    report.mode = "APPLY"
    return report


def run_controlled_repair(dry_run=True, only=None, actor="Hệ thống", db_session=None):
    audit_report = run_data_consistency_audit(db_session=db_session)
    repair_report = plan_data_repairs(audit_report, db_session=db_session, only=only, actor=actor)
    repair_report.dry_run = dry_run
    repair_report.mode = "DRY-RUN" if dry_run else "APPLY"
    if dry_run:
        return repair_report
    return apply_data_repairs(repair_report, db_session=db_session)
