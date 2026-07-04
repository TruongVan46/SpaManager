from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any, Callable

from sqlalchemy import event

from extensions import db
from models.appointment import Appointment
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from models.service import Service
from core.cache import dashboard_cache
from services.appointment_service import AppointmentService
from services.customer_service import CustomerService
from services.dashboard_statistics_service import DashboardStatisticsService
from services.invoice_service import InvoiceService
from services.recycle_bin_service import RecycleBinService
from services.statistics_service import StatisticsService
from utils.timezone_utils import local_now


@dataclass(frozen=True)
class PerformanceProfileMetric:
    name: str
    duration_ms: float
    query_count: int
    rows_estimate: int | None = None
    status: str = "OK"
    notes: tuple[str, ...] = ()


@dataclass
class PerformanceProfileReport:
    generated_at: datetime
    metrics: list[PerformanceProfileMetric] = field(default_factory=list)
    total_duration_ms: float = 0.0
    total_query_count: int = 0
    warnings: list[str] = field(default_factory=list)
    dataset: dict[str, int] = field(default_factory=dict)

    @property
    def status(self):
        if self.warnings or any(metric.status != "OK" for metric in self.metrics):
            return "WARN"
        return "OK"

    def to_text(self):
        lines = [
            "Performance profile",
            f"Status: {self.status}",
            f"Generated at: {self.generated_at.strftime('%d/%m/%Y %H:%M:%S')}",
            f"Total duration: {self.total_duration_ms:.2f} ms",
            f"Total queries: {self.total_query_count}",
            "",
            "Dataset:",
        ]

        for label, value in self.dataset.items():
            lines.append(f"- {label}: {value}")

        lines.extend(["", "Metrics:"])
        for metric in self.metrics:
            lines.append(f"[{metric.status}] {metric.name}")
            lines.append(f"Duration: {metric.duration_ms:.2f} ms")
            lines.append(f"Queries: {metric.query_count}")
            if metric.rows_estimate is not None:
                lines.append(f"Rows: {metric.rows_estimate}")
            for note in metric.notes:
                lines.append(f"Note: {note}")
            lines.append("")

        slow_metrics = sorted(self.metrics, key=lambda metric: metric.duration_ms, reverse=True)[:5]
        if slow_metrics:
            lines.append("Top slow blocks:")
            for metric in slow_metrics:
                lines.append(f"- {metric.name}: {metric.duration_ms:.2f} ms / {metric.query_count} queries")
            lines.append("")

        if self.warnings:
            lines.append("Warnings:")
            for warning in self.warnings:
                lines.append(f"- {warning}")
            lines.append("")

        return "\n".join(line for line in lines if line is not None).rstrip()


class _QueryCounter:
    def __init__(self, engine):
        self.engine = engine
        self.query_count = 0
        self._listener_before = None
        self._listener_after = None

    def _before_cursor_execute(self, conn, cursor, statement, parameters, context, executemany):
        self.query_count += 1
        stack = conn.info.setdefault("_perf_profile_query_starts", [])
        stack.append(perf_counter())

    def _after_cursor_execute(self, conn, cursor, statement, parameters, context, executemany):
        stack = conn.info.get("_perf_profile_query_starts")
        if stack:
            stack.pop()

    def __enter__(self):
        self._listener_before = self._before_cursor_execute
        self._listener_after = self._after_cursor_execute
        event.listen(self.engine, "before_cursor_execute", self._listener_before)
        event.listen(self.engine, "after_cursor_execute", self._listener_after)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._listener_before is not None:
            event.remove(self.engine, "before_cursor_execute", self._listener_before)
        if self._listener_after is not None:
            event.remove(self.engine, "after_cursor_execute", self._listener_after)
        self._listener_before = None
        self._listener_after = None


def _coerce_rows_estimate(result: Any) -> int | None:
    if result is None:
        return None
    if hasattr(result, "items") and hasattr(result, "total"):
        try:
            return len(result.items)
        except TypeError:
            return None
    if isinstance(result, (list, tuple, set)):
        return len(result)
    if isinstance(result, dict):
        total = 0
        found = False
        for value in result.values():
            if isinstance(value, (list, tuple, set)):
                total += len(value)
                found = True
        return total if found else None
    return None


def _classify_metric(duration_ms: float, query_count: int, rows_estimate: int | None, name: str):
    notes: list[str] = []
    status = "OK"

    if duration_ms > 500 or query_count > 50:
        status = "SLOW"
    elif duration_ms > 200 or query_count > 20:
        status = "WARN"

    if query_count > 20:
        notes.append("Query count is higher than expected.")
    if duration_ms > 200:
        notes.append("Block duration is above the local warning threshold.")
    if rows_estimate is not None and rows_estimate >= 100 and "statistics" in name:
        notes.append("Large result set may need pagination/caching review.")
    if query_count >= 8 and ("detail" in name or "history" in name or "statistics" in name):
        notes.append("Possible N+1 pattern or overly chatty block.")

    return status, tuple(notes)


def _dataset_summary():
    return {
        "Customers": Customer.query.count(),
        "Services": Service.query.count(),
        "Appointments": Appointment.query.count(),
        "Invoices": Invoice.query.count(),
        "Invoice details": InvoiceDetail.query.count(),
        "Soft deleted customers": Customer.query.filter(Customer.deleted_at.isnot(None)).count(),
        "Soft deleted services": Service.query.filter(Service.deleted_at.isnot(None)).count(),
        "Soft deleted appointments": Appointment.query.filter(Appointment.deleted_at.isnot(None)).count(),
        "Soft deleted invoices": Invoice.query.filter(Invoice.deleted_at.isnot(None)).count(),
    }


def _first_active_customer():
    return Customer.query.filter(Customer.deleted_at.is_(None)).order_by(Customer.id.asc()).first()


def _first_active_invoice():
    return Invoice.query.filter(Invoice.deleted_at.is_(None)).order_by(Invoice.id.asc()).first()


def _first_active_service():
    return Service.query.filter(Service.deleted_at.is_(None)).order_by(Service.id.asc()).first()


def _load_appointment_calendar_snapshot(search: str, status: str):
    query = AppointmentService._build_filtered_query(
        search=search or None,
        status=status or None,
        from_date=None,
        to_date=None,
        period=None,
    )
    return query.order_by(Appointment.appointment_time.asc()).all()


def _load_invoice_detail_snapshot(invoice_id: int):
    invoice = InvoiceService.get_by_id(invoice_id)
    if not invoice:
        return None
    customer_name = invoice.customer.name if invoice.customer else None
    detail_count = len(invoice.details) if invoice.details is not None else 0
    return {
        "invoice_id": invoice.id,
        "customer_name": customer_name,
        "detail_count": detail_count,
    }


def _profile_event_block(name: str, func: Callable[[], Any], report_warnings: list[str]):
    start = perf_counter()
    result = None
    error_note = None
    with _QueryCounter(db.engine) as counter:
        try:
            result = func()
        except Exception as exc:  # pragma: no cover - defensive CLI guard
            error_note = f"{type(exc).__name__}: {exc}"
    duration_ms = (perf_counter() - start) * 1000.0
    rows_estimate = _coerce_rows_estimate(result)
    status, notes = _classify_metric(duration_ms, counter.query_count, rows_estimate, name)
    if error_note:
        status = "WARN" if status == "OK" else status
        notes = tuple(list(notes) + [f"Execution failed: {error_note}"])
        report_warnings.append(f"{name} failed: {error_note}")
    else:
        if status != "OK":
            report_warnings.append(f"{name} -> {status}")
        for note in notes:
            if "Possible N+1" in note:
                report_warnings.append(f"POSSIBLE_N_PLUS_ONE in {name}")
            elif "Large result set" in note:
                report_warnings.append(f"LARGE_TABLE_NO_PAGINATION_RISK in {name}")
            elif "above the local warning threshold" in note:
                report_warnings.append(f"SLOW_BLOCK {name}")

    return PerformanceProfileMetric(
        name=name,
        duration_ms=duration_ms,
        query_count=counter.query_count,
        rows_estimate=rows_estimate,
        status=status,
        notes=notes,
    )


def profile_block(name: str, func: Callable[[], Any]):
    report_warnings: list[str] = []
    return _profile_event_block(name, func, report_warnings)


def run_performance_profile():
    saved_dashboard_data = dashboard_cache.get("dashboard_data")
    dashboard_cache.invalidate("dashboard_data")
    try:
        report_warnings: list[str] = []
        generated_at = local_now()
        total_started = perf_counter()

        sample_customer = _first_active_customer()
        sample_invoice = _first_active_invoice()
        sample_service = _first_active_service()

        customer_query = sample_customer.name[:3] if sample_customer and sample_customer.name else ""
        service_query = sample_service.name[:3] if sample_service and sample_service.name else ""
        invoice_query = f"HD{sample_invoice.id}" if sample_invoice else ""
        appointment_search = customer_query
        appointment_status = "pending" if sample_customer else ""

        metrics = [
            _profile_event_block("dashboard.summary", lambda: DashboardStatisticsService.get_dashboard_data(), report_warnings),
            _profile_event_block("customer.list", lambda: CustomerService.search_paginated(customer_query, page=1, per_page=25), report_warnings),
        ]

        if sample_customer:
            metrics.append(
                _profile_event_block(
                    "customer.detail.history",
                    lambda: CustomerService.get_customer_history(sample_customer.id),
                    report_warnings,
                )
            )
        else:
            metrics.append(
                PerformanceProfileMetric(
                    name="customer.detail.history",
                    duration_ms=0.0,
                    query_count=0,
                    rows_estimate=0,
                    status="OK",
                    notes=("No active customer records found.",),
                )
            )

        metrics.extend([
            _profile_event_block(
                "appointment.list",
                lambda: AppointmentService.get_filtered(
                    search=appointment_search,
                    status=appointment_status,
                    from_date=None,
                    to_date=None,
                    sort_by="date",
                    order="desc",
                    page=1,
                    per_page=10,
                    period=None,
                ),
                report_warnings,
            ),
            _profile_event_block(
                "appointment.calendar",
                lambda: _load_appointment_calendar_snapshot(appointment_search, appointment_status),
                report_warnings,
            ),
            _profile_event_block(
                "invoice.list",
                lambda: InvoiceService.search_invoices(invoice_query, page=1, per_page=10),
                report_warnings,
            ),
        ])

        if sample_invoice:
            metrics.append(
                _profile_event_block(
                    "invoice.detail",
                    lambda: _load_invoice_detail_snapshot(sample_invoice.id),
                    report_warnings,
                )
            )
        else:
            metrics.append(
                PerformanceProfileMetric(
                    name="invoice.detail",
                    duration_ms=0.0,
                    query_count=0,
                    rows_estimate=0,
                    status="OK",
                    notes=("No active invoice records found.",),
                )
            )

        metrics.extend([
            _profile_event_block("statistics.summary", lambda: StatisticsService.get_summary(), report_warnings),
            _profile_event_block("statistics.top_customers", lambda: StatisticsService.get_customer_statistics_paginated(page=1, per_page=25), report_warnings),
            _profile_event_block("statistics.top_services", lambda: StatisticsService.get_service_statistics_paginated(page=1, per_page=25), report_warnings),
            _profile_event_block(
                "statistics.export_preparation",
                lambda: {
                    "summary": StatisticsService.get_summary(),
                    "customer_statistics": StatisticsService.get_customer_statistics(),
                    "service_statistics": StatisticsService.get_service_statistics(),
                },
                report_warnings,
            ),
            _profile_event_block("recycle_bin.summary", lambda: RecycleBinService.get_statistics(), report_warnings),
        ])

        total_duration_ms = (perf_counter() - total_started) * 1000.0
        total_query_count = sum(metric.query_count for metric in metrics)
        dataset = _dataset_summary()

        warnings = []
        for metric in metrics:
            if metric.status != "OK":
                warnings.append(f"{metric.name}: {metric.status}")
            warnings.extend(note for note in metric.notes if note.startswith("Possible") or note.startswith("Large"))

        warnings.extend(report_warnings)

        # Keep warnings stable and unique while preserving order.
        deduped_warnings = []
        seen_warnings = set()
        for warning in warnings:
            if warning and warning not in seen_warnings:
                deduped_warnings.append(warning)
                seen_warnings.add(warning)

        return PerformanceProfileReport(
            generated_at=generated_at,
            metrics=metrics,
            total_duration_ms=total_duration_ms,
            total_query_count=total_query_count,
            warnings=deduped_warnings,
            dataset=dataset,
        )
    finally:
        dashboard_cache.invalidate("dashboard_data")
        if saved_dashboard_data is not None:
            dashboard_cache.set("dashboard_data", saved_dashboard_data)
