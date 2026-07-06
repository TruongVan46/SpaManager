# Workspace Approval Provisioning Plan

This document outlines the provisioning logic for workspaces when a pending Google owner account is approved by an `APPROVAL_OWNER`.

## Behavior

### 1. Trigger
The provisioning is triggered automatically inside `UserService.approve_pending_user` when a user account with `auth_provider == 'google'` is successfully approved.

### 2. Workspace Creation
- **Name:** Generated in the format `Spa của <Full Name>` (using `full_name`, falling back to `username` or `email` if empty).
- **Slug:** Generated dynamically using lowercase alphanumeric characters and hyphens based on the user's username/email.
- **Uniqueness:** If the slug already exists, a suffix (e.g. `-2`, `-3`) is appended.
- **Status:** Initialized to `active`.
- **Created By:** The approved user is set as the creator (`created_by_id = user.id`).

### 3. Membership Creation
- A corresponding `WorkspaceMember` record is created linking the approved user to their new workspace.
- **Role:** Explicitly set to `owner`.
- **Status:** Set to `active`.
- **Invited By:** Linked to the `APPROVAL_OWNER` who approved the account.
- **Joined At:** Set to `utc_now()`.

### 4. Safety and Transaction Scoping
- The user role upgrade, workspace insertion, and member insertion occur in the **same database transaction** as the approval update.
- If any exception is raised during workspace/membership creation, the transaction is completely rolled back, preventing half-approved states.
- Excludes `APPROVAL_OWNER` from receiving workspaces.
- Idempotent: Subsequent calls to approve the same user will return the existing workspace and skip creation.
- Rejected or disabled users do not trigger provisioning.

## Next Steps
- **Task 6.5.4:** Implement current workspace context helper and session middleware.
- **Task 6.5.5:** Implement data isolation for all business modules.
- **Task 6.5.6:** Support staff and manager creation inside the user's workspace.
- **Task 6.5.7:** Write isolation tests.
