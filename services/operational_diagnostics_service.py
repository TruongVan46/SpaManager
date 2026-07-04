from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import current_app
from sqlalchemy import text
from sqlalchemy.engine.url import make_url

from extensions import db
from models.appointment import Appointment
from models.activity_log import ActivityLog
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_detail import InvoiceDetail
from models.service import Service
from models.user import User
from services.backup_service import BackupService
from services.data_audit_service import run_data_consistency_audit
from services.data_repair_service import plan_data_repairs
from services.performance_profile_service import run_performance_profile
from utils.timezone_utils import local_now, to_local_datetime
import sys


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mask_database_url(database_url: str | None):
    if not database_url:
        return None
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return database_url


def _database_type(database_url: str | None):
    if not database_url:
        return "unknown"
    try:
        return make_url(database_url).get_backend_name()
    except Exception:
        if "sqlite" in database_url:
            return "sqlite"
        if "postgres" in database_url:
            return "postgresql"
        return "unknown"


def _format_bytes(value: int | None):
    if value is None:
        return None
    if value >= 1024 * 1024 * 1024:
        return f"{value / (1024 * 1024 * 1024):.1f} GB"
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value} B"


def _count_model(model, deleted=False):
    query = model.query
    if deleted:
        query = query.filter(model.deleted_at.isnot(None))
    return query.count()


def _parse_backup_created_at(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return to_local_datetime(value, assume_utc=True)
        except Exception:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
    return None


def _backup_sort_key(target_app, meta):
    created_at = _parse_backup_created_at(meta.get("created_at"))
    if created_at is not None:
        return created_at
    filename = meta.get("filename") or ""
    filepath = _safe_backup_file_path(target_app, filename)
    if filepath and Path(filepath).exists():
        return datetime.fromtimestamp(Path(filepath).stat().st_mtime)
    return datetime.min


def _backup_primary_dir(target_app):
    return target_app.config.get("BACKUP_FOLDER") or os.path.join(target_app.root_path, "backup")


def _backup_legacy_dir(target_app):
    primary_dir = os.path.abspath(_backup_primary_dir(target_app))
    legacy_dir = os.path.abspath(os.path.join(target_app.root_path, "backup"))
    if legacy_dir == primary_dir:
        return None
    return legacy_dir


def _backup_metadata_paths(target_app):
    paths = [os.path.join(_backup_primary_dir(target_app), "metadata.json")]
    legacy_dir = _backup_legacy_dir(target_app)
    if legacy_dir:
        paths.append(os.path.join(legacy_dir, "metadata.json"))
    return paths


def _safe_backup_file_path(target_app, filename):
    if not filename:
        return None
    candidate_name = os.path.basename(str(filename))
    for backup_dir in filter(None, [_backup_primary_dir(target_app), _backup_legacy_dir(target_app)]):
        resolved_dir = os.path.abspath(backup_dir)
        candidate = os.path.abspath(os.path.join(resolved_dir, candidate_name))
        if candidate.startswith(resolved_dir + os.sep) and Path(candidate).exists():
            return candidate
    primary_dir = os.path.abspath(_backup_primary_dir(target_app))
    candidate = os.path.abspath(os.path.join(primary_dir, candidate_name))
    if candidate.startswith(primary_dir + os.sep):
        return candidate
    return None


def _load_backup_metadata(target_app):
    merged = {}
    for path in _backup_metadata_paths(target_app):
        if not Path(path).exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as file_handle:
                loaded = json.load(file_handle)
            if isinstance(loaded, dict):
                merged.update(loaded)
        except Exception:
            continue
    return merged


@dataclass
class OperationalDiagnosticsReport:
    status: str
    generated_at: datetime
    app: dict[str, Any] = field(default_factory=dict)
    database: dict[str, Any] = field(default_factory=dict)
    backup: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)
    repair: dict[str, Any] = field(default_factory=dict)
    performance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, verbose: bool = False):
        payload = {
            "status": self.status,
            "generated_at": self.generated_at.isoformat(),
            "app": self.app,
            "database": self.database,
            "backup": self.backup,
            "audit": self.audit,
            "repair": self.repair,
            "performance": self.performance,
            "warnings": self.warnings,
        }
        if verbose:
            payload["verbose"] = True
        return payload

    def to_text(self, verbose: bool = False):
        lines = [
            "Operational diagnostics",
            f"Status: {self.status}",
            f"Generated at: {self.generated_at.strftime('%d/%m/%Y %H:%M:%S')}",
            "",
            "App",
            f"- Name: {self.app.get('name', 'SpaManager')}",
            f"- Version: {self.app.get('version', 'unknown')}",
            f"- Environment: {self.app.get('environment', 'unknown')}",
            f"- Python runtime: {self.app.get('python_runtime', 'unknown')}",
            f"- Database: {self.app.get('database_type', 'unknown')}",
        ]

        if self.app.get("database_url"):
            lines.append(f"- Database URL: {self.app.get('database_url')}")
        if self.app.get("persistent_root"):
            lines.append(f"- Persistent root: {self.app.get('persistent_root')}")
        if self.app.get("current_time"):
            lines.append(f"- Current time: {self.app.get('current_time')}")

        lines.extend(["", "Database"])
        for key in [
            "type",
            "connected",
            "path",
            "exists",
            "size",
            "customers",
            "services",
            "appointments",
            "invoices",
            "invoice_details",
            "users",
            "activity_logs",
            "soft_deleted_customers",
            "soft_deleted_services",
            "soft_deleted_appointments",
            "soft_deleted_invoices",
        ]:
            if key in self.database:
                label = key.replace("_", " ").title()
                lines.append(f"- {label}: {self.database[key]}")

        lines.extend(["", "Backup"])
        for key in [
            "status",
            "primary_dir",
            "exists",
            "count",
            "latest_filename",
            "latest_created_at",
            "latest_app_version",
            "latest_size",
            "latest_status",
        ]:
            if key in self.backup:
                label = key.replace("_", " ").title()
                lines.append(f"- {label}: {self.backup[key]}")

        lines.extend(["", "Data audit"])
        for key in ["status", "errors", "warnings", "top_issue_codes"]:
            if key in self.audit:
                label = key.replace("_", " ").title()
                lines.append(f"- {label}: {self.audit[key]}")
        if verbose and self.audit.get("issues"):
            lines.append("- Issues:")
            for issue in self.audit["issues"]:
                lines.append(f"  * [{issue['severity']}] {issue['code']} - {issue['message']}")

        lines.extend(["", "Repair dry-run"])
        for key in ["mode", "repairable_actions", "skipped_count", "top_action_codes", "top_skipped_codes"]:
            if key in self.repair:
                label = key.replace("_", " ").title()
                lines.append(f"- {label}: {self.repair[key]}")
        if verbose and self.repair.get("actions"):
            lines.append("- Actions:")
            for action in self.repair["actions"]:
                lines.append(f"  * {action['code']} {action['model']}#{action['record_id']} {action['field']}")

        lines.extend(["", "Performance"])
        for key in ["status", "total_duration_ms", "total_query_count", "slowest_blocks", "warnings"]:
            if key in self.performance:
                label = key.replace("_", " ").title()
                lines.append(f"- {label}: {self.performance[key]}")

        if self.warnings:
            lines.extend(["", "Warnings"])
            for warning in self.warnings:
                lines.append(f"- {warning}")

        return "\n".join(lines).rstrip()


def _dataset_counts():
    counts = {
        "customers": _count_model(Customer),
        "services": _count_model(Service),
        "appointments": _count_model(Appointment),
        "invoices": _count_model(Invoice),
        "invoice_details": _count_model(InvoiceDetail),
        "users": User.query.count(),
        "soft_deleted_customers": _count_model(Customer, deleted=True),
        "soft_deleted_services": _count_model(Service, deleted=True),
        "soft_deleted_appointments": _count_model(Appointment, deleted=True),
        "soft_deleted_invoices": _count_model(Invoice, deleted=True),
    }
    try:
        counts["activity_logs"] = ActivityLog.query.count()
    except Exception:
        counts["activity_logs"] = 0
    return counts


def _database_summary(target_app):
    database_url = target_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    database_type = _database_type(database_url)
    summary = {
        "connected": False,
        "type": database_type,
        "path": None,
        "exists": None,
        "size": None,
    }

    try:
        db.session.execute(text("SELECT 1"))
        summary["connected"] = True
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        return summary

    if database_type == "sqlite":
        path = BackupService.get_db_path(target_app)
        summary["path"] = path
        summary["exists"] = Path(path).exists()
        if summary["exists"]:
            summary["size"] = _format_bytes(Path(path).stat().st_size)

    try:
        summary.update(_dataset_counts())
    except Exception as exc:
        summary["counts_error"] = f"{type(exc).__name__}: {exc}"
    return summary


def _backup_summary(target_app):
    backup_dir = _backup_primary_dir(target_app)
    metadata = _load_backup_metadata(target_app)
    backup_items = []

    for backup_id, meta in metadata.items():
        if not isinstance(meta, dict):
            continue
        filename = meta.get("filename")
        if not filename:
            continue
        filepath = _safe_backup_file_path(target_app, filename)
        file_size = None
        if filepath and Path(filepath).exists():
            file_size = Path(filepath).stat().st_size
        backup_items.append({
            "id": backup_id,
            "filename": filename,
            "created_at": meta.get("created_at"),
            "app_version": meta.get("app_version"),
            "size": file_size,
            "status": meta.get("status", "Unknown"),
            "_sort_key": _backup_sort_key(target_app, meta),
        })

    backup_items.sort(key=lambda item: item["_sort_key"], reverse=True)
    latest = backup_items[0] if backup_items else None

    latest_status = latest["status"] if latest else None
    has_invalid_backup = any(item["status"] not in {"Valid", "Unknown"} for item in backup_items)

    summary = {
        "status": "OK" if backup_items and not has_invalid_backup else "WARN",
        "primary_dir": backup_dir,
        "exists": Path(backup_dir).exists(),
        "count": len(backup_items),
        "latest_filename": latest["filename"] if latest else None,
        "latest_created_at": latest["created_at"] if latest else None,
        "latest_app_version": latest["app_version"] if latest else None,
        "latest_size": _format_bytes(latest["size"]) if latest and latest["size"] is not None else None,
        "latest_status": latest_status,
        "items": backup_items,
    }

    if not backup_items:
        summary["warning"] = "No backup found."
    elif has_invalid_backup:
        summary["warning"] = "One or more backups reported a non-valid status."
    return summary


def _audit_summary(verbose: bool = False):
    report = run_data_consistency_audit()
    issue_counts = Counter(issue.code for issue in report.issues)
    summary = {
        "status": report.status,
        "errors": report.total_errors,
        "warnings": report.total_warnings,
        "top_issue_codes": [code for code, _count in issue_counts.most_common(5)],
    }
    if verbose:
        summary["issues"] = [
            {
                "severity": issue.severity,
                "code": issue.code,
                "model": issue.model,
                "record_id": issue.record_id,
                "field": issue.field,
                "message": issue.message,
            }
            for issue in report.issues
        ]
    return summary, report


def _repair_summary(audit_report, verbose: bool = False):
    repair_report = plan_data_repairs(audit_report, actor="Hệ thống")
    code_counts = Counter(action.code for action in repair_report.actions)
    skipped_counts = Counter(issue.code for issue in repair_report.skipped)
    summary = {
        "mode": repair_report.mode,
        "repairable_actions": repair_report.repairable_actions,
        "skipped_count": repair_report.skipped_count,
        "top_action_codes": [code for code, _count in code_counts.most_common(5)],
        "top_skipped_codes": [code for code, _count in skipped_counts.most_common(5)],
    }
    if verbose:
        summary["actions"] = [
            {
                "code": action.code,
                "model": action.model,
                "record_id": action.record_id,
                "field": action.field,
                "before": action.before,
                "after": action.after,
            }
            for action in repair_report.actions
        ]
    return summary, repair_report


def _performance_summary():
    report = run_performance_profile()
    slowest = sorted(report.metrics, key=lambda metric: metric.duration_ms, reverse=True)[:3]
    summary = {
        "status": report.status,
        "total_duration_ms": round(report.total_duration_ms, 2),
        "total_query_count": report.total_query_count,
        "slowest_blocks": [f"{metric.name} — {metric.duration_ms:.2f} ms" for metric in slowest],
        "warnings": report.warnings,
    }
    return summary, report


def run_operational_diagnostics(include_performance: bool = True, include_repair_plan: bool = True, verbose: bool = False, app=None):
    target_app = app or current_app._get_current_object()
    generated_at = local_now()
    warnings: list[str] = []

    app_summary = {
        "name": target_app.config.get("APP_NAME", "SpaManager"),
        "version": target_app.config.get("APP_VERSION", "unknown"),
        "environment": target_app.config.get("APP_ENV", "unknown"),
        "python_runtime": sys.version.split()[0],
        "database_url": _mask_database_url(target_app.config.get("SQLALCHEMY_DATABASE_URI", "")),
        "database_type": _database_type(target_app.config.get("SQLALCHEMY_DATABASE_URI", "")),
        "persistent_root": target_app.config.get("PERSISTENT_ROOT"),
        "current_time": generated_at.strftime('%Y-%m-%d %H:%M:%S'),
    }

    db_summary = _database_summary(target_app)
    if db_summary.get("error"):
        warnings.append(f"Database probe failed: {db_summary['error']}")

    backup_summary = _backup_summary(target_app)
    if backup_summary.get("warning"):
        warnings.append(f"Backup warning: {backup_summary['warning']}")

    audit_summary = {
        "status": "FAIL",
        "errors": 0,
        "warnings": 0,
        "top_issue_codes": [],
    }
    audit_report = None
    try:
        audit_summary, audit_report = _audit_summary(verbose=verbose)
    except Exception as exc:
        audit_summary = {
            "status": "FAIL",
            "errors": 1,
            "warnings": 0,
            "top_issue_codes": [],
        }
        warnings.append(f"Data audit failed: {type(exc).__name__}: {exc}")

    repair_summary = {
        "mode": "DRY-RUN",
        "repairable_actions": 0,
        "skipped_count": 0,
        "top_action_codes": [],
        "top_skipped_codes": [],
    }
    repair_report = None
    if include_repair_plan and audit_report is not None:
        try:
            repair_summary, repair_report = _repair_summary(audit_report, verbose=verbose)
        except Exception as exc:
            warnings.append(f"Repair dry-run failed: {type(exc).__name__}: {exc}")
    elif not include_repair_plan:
        repair_summary["mode"] = "SKIPPED"
        warnings.append("Repair dry-run skipped by option.")

    performance_summary = {
        "status": "SKIPPED" if not include_performance else "OK",
        "total_duration_ms": 0.0,
        "total_query_count": 0,
        "slowest_blocks": [],
        "warnings": [],
    }
    performance_report = None
    if include_performance:
        try:
            performance_summary, performance_report = _performance_summary()
        except Exception as exc:
            performance_summary = {
                "status": "WARN",
                "total_duration_ms": 0.0,
                "total_query_count": 0,
                "slowest_blocks": [],
                "warnings": [f"{type(exc).__name__}: {exc}"],
            }
            warnings.append(f"Performance profile failed: {type(exc).__name__}: {exc}")
    else:
        warnings.append("Performance profile skipped by option.")

    if db_summary.get("error"):
        overall_status = "FAIL"
    elif audit_summary.get("errors", 0) > 0:
        overall_status = "FAIL"
    else:
        warning_conditions = [
            audit_summary.get("warnings", 0) > 0,
            backup_summary.get("status") != "OK",
            performance_summary.get("status") in {"WARN", "SLOW"},
            bool(warnings),
        ]
        overall_status = "WARN" if any(warning_conditions) else "OK"

    if performance_summary.get("status") == "SLOW":
        warnings.append("Performance warning: report status SLOW.")

    if backup_summary.get("status") != "OK" and not backup_summary.get("warning"):
        warnings.append("Backup warning: latest backup metadata unavailable.")

    return OperationalDiagnosticsReport(
        status=overall_status,
        generated_at=generated_at,
        app=app_summary,
        database=db_summary,
        backup=backup_summary,
        audit=audit_summary,
        repair=repair_summary,
        performance=performance_summary,
        warnings=list(dict.fromkeys(warnings)),
    )
