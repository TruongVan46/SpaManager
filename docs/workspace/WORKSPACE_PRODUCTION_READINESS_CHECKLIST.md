# Production Workspace Readiness Checklist

> **Version**: 6.5
> **Task**: 6.5.8
> **Status**: READY FOR PRODUCTION MANUAL SMOKE
> **Audit Date**: 2026-07-06

---

## 1. Current Architecture

The workspace-level tenant isolation is structured as a shared-schema, multi-tenant database:
- **Shared DB Instance**: A single Railway PostgreSQL database is shared among all tenants.
- **Tenant Scoping**: All business data entities (`Customer`, `Service`, `Appointment`, `Invoice`) are partitioned using a foreign key reference column `workspace_id`.
- **Workspace Scoped Queries**: Service layers apply `WorkspaceService.scoped_query` to query only current workspace data.
- **Workspace Membership**: Access permissions and workspace mapping are handled via the `WorkspaceMember` model.
- **Admin & Portals**:
  - `APPROVAL_OWNER` acts exclusively as the system administrator and is restricted to the `/approval` provisioning portal.
  - Normal users manage their accounts and business data within the main SpaManager dashboard.

---

## 2. Migration State

- **Current Alembic Head**: `0003_workspace_foundation` (Verified as the active head in local and development stages).
- **Railway Pre-deploy Automation**:
  - Pre-deploy phase automatically triggers:
    ```bash
    python -m flask --app app db upgrade
    ```
- **Execution Constraints**:
  - No manual execution of `flask db upgrade` or direct SQL manipulation should be run on the production database.
  - No new database migration scripts (e.g. `0004*.py`) are created for this checklist.
  - Never create `0002_workspace_foundation.py` or `WORKSPACE_MIGRATION_EXECUTION_APPROVAL.md` as they are legacy/docs only.

---

## 3. Required Railway Environment Variables Checklist

Ensure the following environment variables are properly populated in the Railway Project Settings (verify presence only, do NOT save/log secret values):

- `DATABASE_URL` (Connection string to the PostgreSQL database)
- `SECRET_KEY` (Used for session crypt and CSRF protection)
- `GOOGLE_AUTH_ENABLED` (Should be set to `true` to enable Google authentication)
- `GOOGLE_CLIENT_ID` (Google Cloud Client ID for OAuth login)
- `GOOGLE_CLIENT_SECRET` (Google Cloud Client Secret)
- `GOOGLE_REDIRECT_URI` (Must be: `https://spahub-truongvan.up.railway.app/auth/google/callback`)
- `GOOGLE_ALLOWED_DOMAIN` (Optional. Set to restrict logins to a specific GSuite/Google Workspace domain; leave blank to allow all gmail accounts)
- `APPROVAL_OWNER_USERNAME` (The master admin username for the approval portal)
- `APPROVAL_OWNER_EMAIL` (Email address of the master admin)
- `APPROVAL_OWNER_PASSWORD` (Secure password for the master admin)
- `PORT` (Injected automatically by Railway runtime)
- `APP_VERSION` (Used for version labeling in UI and backup metadata)

> [!WARNING]
> Never commit `.env` or write absolute credential values in any public documentation, logs, or reports.

---

## 4. Google Cloud OAuth Checklist

- **Callback/Redirect Endpoint**: Must match exactly in Google Cloud Console Credentials page:
  `https://spahub-truongvan.up.railway.app/auth/google/callback`
- **Domain Restrictions**: Ensure `GOOGLE_ALLOWED_DOMAIN` matches the target domain (or leave blank to allow any account).
- **Consent Screen Status**: Verify the Google OAuth Consent Screen is published (In Production) or includes all tester emails under the testing sandbox phase.

---

## 5. First Production Smoke Manual Checklist

Perform these manual verification steps immediately after deployment:

1. **OAuth Flow & Approval Portal**:
   - Visit the production domain: `https://spahub-truongvan.up.railway.app`.
   - Confirm that the "Tiếp tục với Google" login button appears.
   - Authenticate with a new Google Account.
   - Assert the user lands on the pending page (`/auth/pending`) and is blocked from accessing the main application dashboard.
2. **Provisioning Approval**:
   - Access `/approval` and log in using the `APPROVAL_OWNER` credentials.
   - Locate the pending Google user in the approval table.
   - Click "Approve" (Duyệt).
   - Log out of the approval portal.
3. **Workspace Initialization & Context**:
   - Log back in with the approved Google Account.
   - Confirm the user is automatically upgraded to `OWNER`.
   - Assert a new workspace is created for this owner.
   - Verify `current_workspace_id` is registered in their session, and they are redirected to the main dashboard.
4. **User Management Roles**:
   - Navigate to `/users`.
   - Create an `ADMIN` user and a `STAFF` user.
   - Verify their roles inside the workspace list.
   - Assert the UI does **not** allow creating or choosing the role `OWNER`.
   - Attempt to POST a user with `role=OWNER` using custom scripts -> confirm it is rejected with a 400 Bad Request/ValidationException.
5. **Business Data Scoping & Isolation**:
   - Create a test customer, service, appointment, and invoice.
   - Ensure the dashboard widgets increment (e.g. Total Customers = 1).
   - Log in using the newly created `STAFF` account.
   - Assert the `STAFF` user has the same workspace context and can view the business records created by the `OWNER`.
   - Confirm that the `STAFF` user is redirected or blocked (403) when attempting to access the User Management panel (`/users`).
6. **Cross-Workspace Data Leak Validation**:
   - Log in with a second, separate approved Google owner account (which generates Workspace B).
   - Verify that Workspace B has an empty dashboard, empty customer list, and empty service list.
   - Explicitly try to fetch Workspace A's records (e.g. `/customers/edit/<A_id>` or `/invoices/detail/<A_id>`) -> confirm it returns a 404 Not Found.
   - Assert that statistics, report downloads, and dashboard graphs do not leak data from Workspace A.

---

## 6. Fail-Closed Security Guarantees

- **No Workspace Context**: If a user manages to authenticate but has no active workspace membership (or `current_workspace_id` is not present in the session), they must see 0 customers, 0 services, 0 appointments, 0 invoices, and a blank dashboard (Fail-Closed).
- **Boundary Violation**: Attempts to read, edit, or delete items belonging to another workspace must result in 404 (NotFoundException) or a 400 validation block, ensuring no presence disclosure of other tenants.

---

## 7. User Management Policy Summary

- **OWNER**: Can only create `ADMIN` and `STAFF`.
- **ADMIN**: Can only create `STAFF`.
- **STAFF**: Blocked from user management entirely (receives 403 Forbidden).
- **APPROVAL_OWNER**: Blocked from main app user management, can only approve/reject pending owners.
- **OWNER role creation**: Strictly blocked from UI and service layer user creation. Can only be generated through Google approval provisioning.

---

## 8. Data Isolation Areas Covered

The implementation covers and secures the following zones:
- **Customers**: Fully scoped lists, detail views, creation, updates, and deletes.
- **Services**: Scoped queries and category/detail views.
- **Appointments**: Scoped scheduling, timezone checks, and updates.
- **Invoices**: Scoped invoicing, itemization, and printing.
- **Dashboard/Statistics**: Isolated summary cards, dynamic charts, and activities.
- **Reports**: Scoped revenue spreadsheets and status count tables.
- **Excel Import**: Scoped duplicate-conflict resolution and workspace mapping for imported records.
- **User Management**: Isolated user lists, profile updates, and active toggles.
- **Cache Invalidation**: Scoped wildcard eviction of workspace statistics.

---

## 9. Backup & Restore Note

- **Backup Center Paused**: The Backup Center features in the UI remain deactivated in this version.
- **Database Backups**: All backup and restoration tasks for the production PostgreSQL database must be performed at the infrastructure level (via Railway PostgreSQL backups or command line tools).
- **No UI Restoration**: UI-based restore and SQLite-only recovery tools are not allowed on the production environment.

---

## 10. Monitoring After Production Usage

- **Deployment Status**: Monitor Railway build and deployment logs to verify `flask db upgrade` executes cleanly without conflicts.
- **Login Logs**: Check security logs for OAuth callback errors, signature mismatches, or redirect anomalies.
- **Access Violation Alerts**: Watch for repeated 404 errors on scoped entities or unauthorized privilege escalation attempts.
- **Performance Logs**: Audit cache hits on workspace dashboard metrics to ensure cache validation keys are working properly.

---

## 11. Rollback & Contingency Notes

- **Pre-deployment Failure**: If the Alembic upgrade fails, revert the deployment instantly to the previous commit. Do not try to debug database schemas while live.
- **OAuth Callback Failures**: If OAuth callback fails, immediately check redirect URI spelling and Google credentials.
- **Data Leak Suspected**: If a multi-tenancy leak is suspected, immediately set the application to maintenance mode or suspend user logins rather than risking user data exposure.
- **No Direct SQL Execution**: Never run raw SQL updates or deletes on the production database to solve data issues without offline verification.

---

## 12. Readiness Result

**READY FOR PRODUCTION MANUAL SMOKE**

---

## 13. Next Recommended Step

- **Task 6.5.9**: Production manual smoke execution record (recording evidence of the first successful tenant isolation flow on the live production cluster).
