# Workspace Data Isolation Plan

This document details the implementation design and mechanisms for isolating business data within a multi-tenant workspace architecture for SpaManager.

---

## 1. Scope

Data isolation applies to the following models and areas:
*   **Customers**: All customer profiles and contacts.
*   **Services**: All spa service items.
*   **Appointments**: Bookings and schedules.
*   **Invoices & InvoiceDetails**: Billings, sales, and payments.
*   **Dashboard & Statistics**: Daily metrics, revenue calculations, and charts.
*   **Settings page statistics**: Record counts shown in the administrator view.

---

## 2. Core Isolation Mechanics

### A. Automatic Workspace Assignment (Create)
When a new record (Customer, Service, Appointment, Invoice) is created, the system must automatically resolve the tenant workspace context and assign the correct `workspace_id`.
*   Done via: `WorkspaceService.assign_workspace(record)`.
*   During creation, if no workspace context is active, it raises a `403 Forbidden` error (except in testing bypass).

### B. Workspace-Scoped Queries (List/Detail/Update/Delete)
All query lookups (lists and single detail checks) are scoped using:
*   `WorkspaceService.scoped_query(Model)` instead of direct `Model.query`.
*   This automatically injects a `filter(Model.workspace_id == current_workspace_id)` clause.
*   Update and delete logic retrieve the target record using this scoped query first (e.g., `CustomerService.get_by_id`), ensuring that edits/deletions on cross-tenant records are impossible (fail as not found).

### C. Prevent Cross-Workspace Data Leakage & Linkage
*   **Appointments**: Creating or editing an appointment checks that both the associated `customer_id` and `service_id` belong to the active workspace. If they do not, a `ValidationException` is raised.
*   **Invoices**: Creating or editing an invoice checks that both the associated `customer_id` and all `service_id` values inside `items` belong to the active workspace. If not, a `ValidationException` is raised.

### D. Dashboard & Cache Isolation
*   All counts (customers, services, appointments today, invoices today) and revenue sums in `DashboardStatisticsService` are filtered by `workspace_id`.
*   The dashboard caching mechanism in Redis/Memory uses a key pattern formatted as `dashboard_data_<workspace_id>` to ensure that cached statistics do not leak across different workspaces.

---

## 3. Fail-Closed Principles (Default Deny)

*   **No Active Workspace Context**: If a user does not have a valid `current_workspace_id` in their session, the scoped query must **fail closed** by applying a filter of `workspace_id == -1`. 
*   **No Fallback**: The application does **not** fall back to `Model.query.all()` or display global data in production. All cross-tenant queries return empty results by default.

---

## 4. Test-Only Legacy Bypass

To ensure backward compatibility with the existing **190 basic unit tests** (which are not tenant-aware and do not initialize workspace contexts):
*   A test-only bypass is allowed **only** when `current_app.config.get("TESTING") is True` (Flask testing mode).
*   Even when `TESTING = True`, the bypass is only active if the test context does **not** set the explicit flag `session["_enable_workspace_isolation"] = True`.
*   If `_enable_workspace_isolation` is set to `True`, the test behaves exactly like a production environment (fail-closed, no bypass).
*   Any bypass helper (e.g., `_get_current_workspace_id_for_testing_bypass()`) is explicitly marked as internal and test-only.
*   **Production runtime ignores testing bypass entirely and defaults strictly to fail-closed.**

---

## 5. Non-Goals (Out of Scope for Task 6.5.5)

*   **No database migrations**: This task does not execute any database changes or generate new migrations (0003 is already active).
*   **No staff/manager creation**: The membership structure is assumed to exist. Adding users to workspaces is a future task.
*   **No workspace switcher UI**: Selecting or swapping workspaces dynamically via a UI drop-down is out of scope.

---

## 6. Next Steps

*   **Task 6.5.6**: Staff/manager account creation and invitations within the tenant workspace.
*   **Task 6.5.7**: Production readiness and E2E isolation validation tests.
