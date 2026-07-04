from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any

from extensions import db
from models.appointment import Appointment
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from models.service import Service


APPOINTMENT_ALLOWED_STATUSES = {
    "pending",
    "confirmed",
    "completed",
    "cancelled",
    "canceled",
    "no_show",
    "noshow",
}

INVOICE_ALLOWED_PAYMENT_METHODS = {
    "cash",
    "card",
    "transfer",
    "bank_transfer",
    "momo",
    "vnpay",
    "paid",
    "unpaid",
    "partial",
    "pending",
    "cancelled",
    "canceled",
    "refunded",
    "unknown",
}


@dataclass
class DataAuditIssue:
    severity: str
    code: str
    model: str
    record_id: Any
    field: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def format_line(self):
        return f"[{self.severity}] {self.code}"


@dataclass
class DataAuditReport:
    issues: list[DataAuditIssue] = field(default_factory=list)
    total_errors: int = 0
    total_warnings: int = 0

    @property
    def passed(self):
        return self.total_errors == 0

    @property
    def status(self):
        if self.total_errors > 0:
            return "FAIL"
        if self.total_warnings > 0:
            return "WARN"
        return "PASS"

    def add_issue(self, severity, code, model, record_id, field, message, **details):
        issue = DataAuditIssue(
            severity=severity,
            code=code,
            model=model,
            record_id=record_id,
            field=field,
            message=message,
            details=details,
        )
        self.issues.append(issue)
        if severity == "ERROR":
            self.total_errors += 1
        else:
            self.total_warnings += 1
        return issue

    def add_error(self, code, model, record_id, field, message, **details):
        return self.add_issue("ERROR", code, model, record_id, field, message, **details)

    def add_warning(self, code, model, record_id, field, message, **details):
        return self.add_issue("WARNING", code, model, record_id, field, message, **details)

    def _section_name_for_issue(self, issue):
        if issue.code.endswith("SOFT_DELETE_MISMATCH") or "SOFT_DELETED" in issue.code:
            return "Soft delete"
        if issue.code.startswith("CUSTOMER_"):
            return "Customers"
        if issue.code.startswith("SERVICE_"):
            return "Services"
        if issue.code.startswith("APPOINTMENT_"):
            return "Appointments"
        if issue.code.startswith("INVOICE_DETAIL_"):
            return "Invoice details"
        if issue.code.startswith("INVOICE_"):
            return "Invoices"
        return "Totals"

    def _format_issue(self, issue):
        details_bits = []
        if issue.model:
            details_bits.append(f"Model: {issue.model}")
        if issue.record_id is not None:
            details_bits.append(f"Record: {issue.record_id}")
        if issue.field:
            details_bits.append(f"Field: {issue.field}")
        if issue.details:
            extra_parts = []
            for key, value in issue.details.items():
                extra_parts.append(f"{key}={value}")
            if extra_parts:
                details_bits.append(f"Details: {'; '.join(extra_parts)}")
        details_text = "\n".join(details_bits)
        if details_text:
            return f"{issue.format_line()}\n{details_text}\nMessage: {issue.message}"
        return f"{issue.format_line()}\nMessage: {issue.message}"

    def to_text(self):
        lines = [
            "Data consistency audit",
            f"Status: {self.status}",
            f"Errors: {self.total_errors}",
            f"Warnings: {self.total_warnings}",
        ]

        section_order = ["Customers", "Services", "Appointments", "Invoices", "Invoice details", "Soft delete", "Totals"]
        grouped = {section: [] for section in section_order}
        for issue in self.issues:
            section = self._section_name_for_issue(issue)
            grouped.setdefault(section, []).append(issue)

        for section in section_order:
            section_issues = grouped.get(section, [])
            if not section_issues:
                continue
            lines.append("")
            lines.append(section)
            for issue in section_issues:
                lines.append(self._format_issue(issue))
                lines.append("")

        return "\n".join(line for line in lines if line is not None).rstrip()

    format_cli_report = to_text


def _normalize_phone(phone):
    if phone is None:
        return None
    cleaned = "".join(character for character in str(phone) if character.isdigit())
    return cleaned or None


def _normalize_email(email):
    if email is None:
        return None
    cleaned = str(email).strip().lower()
    return cleaned or None


def _normalize_status(status):
    return (status or "").strip().lower()


def _normalize_payment_method(payment_method):
    return (payment_method or "").strip().lower()


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _has_outer_whitespace(value):
    return isinstance(value, str) and value != value.strip()


def _is_missing_datetime_value(value):
    if value is None:
        return True
    if isinstance(value, datetime):
        return False
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return True
        try:
            datetime.fromisoformat(text_value.replace("Z", "+00:00"))
            return False
        except ValueError:
            return True
    return True


def _is_missing_date_value(value):
    if value is None:
        return True
    if isinstance(value, date):
        return False
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return True
        try:
            date.fromisoformat(text_value)
            return False
        except ValueError:
            return True
    return True


def _loaded_map(records):
    return {record.id: record for record in records if getattr(record, "id", None) is not None}


def run_data_consistency_audit(db_session=None):
    session = db_session or db.session
    report = DataAuditReport()

    with session.no_autoflush:
        customers = session.query(Customer).all()
        services = session.query(Service).all()
        appointments = session.query(Appointment).all()
        invoices = session.query(Invoice).all()
        invoice_details = session.query(InvoiceDetail).all()

    customer_by_id = _loaded_map(customers)
    service_by_id = _loaded_map(services)
    invoice_by_id = _loaded_map(invoices)

    phone_groups = {}
    email_groups = {}

    for customer in customers:
        if _is_blank(customer.name):
            report.add_error(
                code="CUSTOMER_EMPTY_NAME",
                model="Customer",
                record_id=customer.id,
                field="name",
                message="Tên khách hàng không được để trống.",
            )
        elif _has_outer_whitespace(customer.name):
            report.add_warning(
                code="CUSTOMER_TRIM_NAME",
                model="Customer",
                record_id=customer.id,
                field="name",
                message="Tên khách hàng có khoảng trắng thừa ở đầu hoặc cuối.",
                before=customer.name,
                after=customer.name.strip(),
            )

        normalized_phone = _normalize_phone(customer.phone)
        if normalized_phone:
            phone_groups.setdefault(normalized_phone, []).append(customer)
        if _has_outer_whitespace(customer.phone):
            report.add_warning(
                code="CUSTOMER_TRIM_PHONE",
                model="Customer",
                record_id=customer.id,
                field="phone",
                message="Số điện thoại có khoảng trắng thừa ở đầu hoặc cuối.",
                before=customer.phone,
                after=customer.phone.strip(),
            )

        normalized_email = _normalize_email(customer.email)
        if normalized_email:
            email_groups.setdefault(normalized_email, []).append(customer)
        if _has_outer_whitespace(customer.email):
            report.add_warning(
                code="CUSTOMER_TRIM_EMAIL",
                model="Customer",
                record_id=customer.id,
                field="email",
                message="Email có khoảng trắng thừa ở đầu hoặc cuối.",
                before=customer.email,
                after=customer.email.strip(),
            )

        if hasattr(customer, "deleted_at") and hasattr(customer, "deleted_by"):
            deleted_at = getattr(customer, "deleted_at", None)
            deleted_by = getattr(customer, "deleted_by", None)
            if bool(deleted_at) != bool(deleted_by and str(deleted_by).strip()):
                report.add_warning(
                    code="CUSTOMER_SOFT_DELETE_MISMATCH",
                    model="Customer",
                    record_id=customer.id,
                    field="deleted_at/deleted_by",
                    message="Trạng thái soft delete của khách hàng không nhất quán.",
                )

    for normalized_phone, grouped_customers in phone_groups.items():
        if len(grouped_customers) > 1:
            representative = grouped_customers[0]
            duplicate_ids = [customer.id for customer in grouped_customers[1:]]
            report.add_warning(
                code="CUSTOMER_DUPLICATE_PHONE",
                model="Customer",
                record_id=representative.id,
                field="phone",
                message=f"Số điện thoại bị trùng với khách hàng #{duplicate_ids[0]}.",
                duplicate_record_ids=duplicate_ids,
                normalized_value=normalized_phone,
            )

    for normalized_email, grouped_customers in email_groups.items():
        if len(grouped_customers) > 1:
            representative = grouped_customers[0]
            duplicate_ids = [customer.id for customer in grouped_customers[1:]]
            report.add_warning(
                code="CUSTOMER_DUPLICATE_EMAIL",
                model="Customer",
                record_id=representative.id,
                field="email",
                message=f"Email bị trùng với khách hàng #{duplicate_ids[0]}.",
                duplicate_record_ids=duplicate_ids,
                normalized_value=normalized_email,
            )

    for service in services:
        if _is_blank(service.name):
            report.add_error(
                code="SERVICE_EMPTY_NAME",
                model="Service",
                record_id=service.id,
                field="name",
                message="Tên dịch vụ không được để trống.",
            )
        elif _has_outer_whitespace(service.name):
            report.add_warning(
                code="SERVICE_TRIM_NAME",
                model="Service",
                record_id=service.id,
                field="name",
                message="Tên dịch vụ có khoảng trắng thừa ở đầu hoặc cuối.",
                before=service.name,
                after=service.name.strip(),
            )

        if getattr(service, "price", None) is not None and service.price < 0:
            report.add_error(
                code="SERVICE_NEGATIVE_PRICE",
                model="Service",
                record_id=service.id,
                field="price",
                message="Giá dịch vụ không được âm.",
                price=service.price,
            )

        deleted_at = getattr(service, "deleted_at", None)
        deleted_by = getattr(service, "deleted_by", None)
        if bool(deleted_at) != bool(deleted_by and str(deleted_by).strip()):
            report.add_warning(
                code="SERVICE_SOFT_DELETE_MISMATCH",
                model="Service",
                record_id=service.id,
                field="deleted_at/deleted_by",
                message="Trạng thái soft delete của dịch vụ không nhất quán.",
            )

    for appointment in appointments:
        if getattr(appointment, "customer_id", None) is not None:
            customer = customer_by_id.get(appointment.customer_id)
            if customer is None:
                report.add_error(
                    code="APPOINTMENT_MISSING_CUSTOMER",
                    model="Appointment",
                    record_id=appointment.id,
                    field="customer_id",
                    message="Lịch hẹn tham chiếu khách hàng không tồn tại.",
                    customer_id=appointment.customer_id,
                )
            elif getattr(customer, "deleted_at", None) is not None:
                report.add_warning(
                    code="APPOINTMENT_SOFT_DELETED_CUSTOMER",
                    model="Appointment",
                    record_id=appointment.id,
                    field="customer_id",
                    message="Lịch hẹn đang liên kết khách hàng đã bị soft delete.",
                    customer_id=appointment.customer_id,
                )
        else:
            report.add_error(
                code="APPOINTMENT_MISSING_CUSTOMER",
                model="Appointment",
                record_id=appointment.id,
                field="customer_id",
                message="Lịch hẹn thiếu liên kết khách hàng.",
            )

        if getattr(appointment, "service_id", None) is not None:
            service = service_by_id.get(appointment.service_id)
            if service is None:
                report.add_error(
                    code="APPOINTMENT_MISSING_SERVICE",
                    model="Appointment",
                    record_id=appointment.id,
                    field="service_id",
                    message="Lịch hẹn tham chiếu dịch vụ không tồn tại.",
                    service_id=appointment.service_id,
                )
            elif getattr(service, "deleted_at", None) is not None:
                report.add_warning(
                    code="APPOINTMENT_SOFT_DELETED_SERVICE",
                    model="Appointment",
                    record_id=appointment.id,
                    field="service_id",
                    message="Lịch hẹn đang liên kết dịch vụ đã bị soft delete.",
                    service_id=appointment.service_id,
                )
        else:
            report.add_error(
                code="APPOINTMENT_MISSING_SERVICE",
                model="Appointment",
                record_id=appointment.id,
                field="service_id",
                message="Lịch hẹn thiếu liên kết dịch vụ.",
            )

        if _is_missing_datetime_value(getattr(appointment, "appointment_time", None)):
            report.add_error(
                code="APPOINTMENT_EMPTY_TIME",
                model="Appointment",
                record_id=appointment.id,
                field="appointment_time",
                message="Lịch hẹn thiếu thời gian hẹn.",
            )

        normalized_status = _normalize_status(getattr(appointment, "status", None))
        if normalized_status and normalized_status not in APPOINTMENT_ALLOWED_STATUSES:
            report.add_error(
                code="APPOINTMENT_INVALID_STATUS",
                model="Appointment",
                record_id=appointment.id,
                field="status",
                message="Trạng thái lịch hẹn không hợp lệ.",
                status=appointment.status,
            )

        deleted_at = getattr(appointment, "deleted_at", None)
        deleted_by = getattr(appointment, "deleted_by", None)
        if bool(deleted_at) != bool(deleted_by and str(deleted_by).strip()):
            report.add_warning(
                code="APPOINTMENT_SOFT_DELETE_MISMATCH",
                model="Appointment",
                record_id=appointment.id,
                field="deleted_at/deleted_by",
                message="Trạng thái soft delete của lịch hẹn không nhất quán.",
            )

    for invoice in invoices:
        if getattr(invoice, "customer_id", None) is not None:
            customer = customer_by_id.get(invoice.customer_id)
            if customer is None:
                report.add_error(
                    code="INVOICE_MISSING_CUSTOMER",
                    model="Invoice",
                    record_id=invoice.id,
                    field="customer_id",
                    message="Hóa đơn tham chiếu khách hàng không tồn tại.",
                    customer_id=invoice.customer_id,
                )
            elif getattr(customer, "deleted_at", None) is not None:
                report.add_warning(
                    code="INVOICE_SOFT_DELETED_CUSTOMER",
                    model="Invoice",
                    record_id=invoice.id,
                    field="customer_id",
                    message="Hóa đơn đang liên kết khách hàng đã bị soft delete.",
                    customer_id=invoice.customer_id,
                )
        else:
            report.add_error(
                code="INVOICE_MISSING_CUSTOMER",
                model="Invoice",
                record_id=invoice.id,
                field="customer_id",
                message="Hóa đơn thiếu liên kết khách hàng.",
            )

        if _is_missing_date_value(getattr(invoice, "invoice_date", None)):
            report.add_error(
                code="INVOICE_EMPTY_DATE",
                model="Invoice",
                record_id=invoice.id,
                field="invoice_date",
                message="Hóa đơn thiếu ngày lập.",
            )

        if getattr(invoice, "total_amount", None) is not None and invoice.total_amount < 0:
            report.add_error(
                code="INVOICE_NEGATIVE_TOTAL",
                model="Invoice",
                record_id=invoice.id,
                field="total_amount",
                message="Tổng tiền hóa đơn không được âm.",
                total_amount=invoice.total_amount,
            )

        normalized_payment_method = _normalize_payment_method(getattr(invoice, "payment_method", None))
        if normalized_payment_method and normalized_payment_method not in INVOICE_ALLOWED_PAYMENT_METHODS:
            report.add_warning(
                code="INVOICE_INVALID_PAYMENT_METHOD",
                model="Invoice",
                record_id=invoice.id,
                field="payment_method",
                message="Phương thức thanh toán không hợp lệ.",
                payment_method=invoice.payment_method,
            )

        deleted_at = getattr(invoice, "deleted_at", None)
        deleted_by = getattr(invoice, "deleted_by", None)
        if bool(deleted_at) != bool(deleted_by and str(deleted_by).strip()):
            report.add_warning(
                code="INVOICE_SOFT_DELETE_MISMATCH",
                model="Invoice",
                record_id=invoice.id,
                field="deleted_at/deleted_by",
                message="Trạng thái soft delete của hóa đơn không nhất quán.",
            )

    for detail in invoice_details:
        if getattr(detail, "invoice_id", None) is not None:
            invoice = invoice_by_id.get(detail.invoice_id)
            if invoice is None:
                report.add_error(
                    code="INVOICE_DETAIL_MISSING_INVOICE",
                    model="InvoiceDetail",
                    record_id=detail.id,
                    field="invoice_id",
                    message="Chi tiết hóa đơn tham chiếu hóa đơn không tồn tại.",
                    invoice_id=detail.invoice_id,
                )
        else:
            report.add_error(
                code="INVOICE_DETAIL_MISSING_INVOICE",
                model="InvoiceDetail",
                record_id=detail.id,
                field="invoice_id",
                message="Chi tiết hóa đơn thiếu liên kết hóa đơn.",
            )

        if getattr(detail, "service_id", None) is not None:
            service = service_by_id.get(detail.service_id)
            if service is None:
                report.add_error(
                    code="INVOICE_DETAIL_MISSING_SERVICE",
                    model="InvoiceDetail",
                    record_id=detail.id,
                    field="service_id",
                    message="Chi tiết hóa đơn tham chiếu dịch vụ không tồn tại.",
                    service_id=detail.service_id,
                )
            elif getattr(service, "deleted_at", None) is not None:
                report.add_warning(
                    code="INVOICE_DETAIL_SOFT_DELETED_SERVICE",
                    model="InvoiceDetail",
                    record_id=detail.id,
                    field="service_id",
                    message="Chi tiết hóa đơn đang liên kết dịch vụ đã bị soft delete.",
                    service_id=detail.service_id,
                )
        else:
            report.add_error(
                code="INVOICE_DETAIL_MISSING_SERVICE",
                model="InvoiceDetail",
                record_id=detail.id,
                field="service_id",
                message="Chi tiết hóa đơn thiếu liên kết dịch vụ.",
            )

        if getattr(detail, "quantity", None) is not None and detail.quantity <= 0:
            report.add_error(
                code="INVOICE_DETAIL_INVALID_QUANTITY",
                model="InvoiceDetail",
                record_id=detail.id,
                field="quantity",
                message="Số lượng chi tiết hóa đơn phải lớn hơn 0.",
                quantity=detail.quantity,
            )

        if getattr(detail, "price", None) is not None and detail.price < 0:
            report.add_error(
                code="INVOICE_DETAIL_NEGATIVE_PRICE",
                model="InvoiceDetail",
                record_id=detail.id,
                field="price",
                message="Đơn giá chi tiết hóa đơn không được âm.",
                price=detail.price,
            )

        if hasattr(detail, "amount") and getattr(detail, "amount", None) is not None and detail.amount < 0:
            report.add_error(
                code="INVOICE_DETAIL_NEGATIVE_AMOUNT",
                model="InvoiceDetail",
                record_id=detail.id,
                field="amount",
                message="Thành tiền chi tiết hóa đơn không được âm.",
                amount=detail.amount,
            )
        if hasattr(detail, "subtotal") and getattr(detail, "subtotal", None) is not None and detail.subtotal < 0:
            report.add_error(
                code="INVOICE_DETAIL_NEGATIVE_AMOUNT",
                model="InvoiceDetail",
                record_id=detail.id,
                field="subtotal",
                message="Thành tiền chi tiết hóa đơn không được âm.",
                subtotal=detail.subtotal,
            )

    return report
