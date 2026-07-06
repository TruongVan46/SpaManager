# Current Workspace Context and Session Selection Plan

This document details the design and implementation of the active workspace context tracking in SpaManager.

## Core Design

### 1. Session Storage
We track the active workspace using the session key:
```python
WORKSPACE_SESSION_KEY = "current_workspace_id"
```
The workspace object and its ID are automatically exposed to all templates via Flask's `@app.context_processor` as `current_workspace` and `current_workspace_id`.

### 2. Auto-Selection Logic
Upon login success (via password or Google OAuth callback), `WorkspaceService.ensure_current_workspace_session(user)` evaluates:

- **Single Active Workspace:** If the user is a member of exactly one active workspace, that workspace is selected and its ID is saved to the session.
- **Multiple Active Workspaces:** If the user has multiple active memberships, the oldest membership is selected deterministically (ordered by `joined_at` ASC, `id` ASC). 
  *Note: A UI switcher is out-of-scope for the current phase and will be added in a future task.*
- **No Active Workspaces:** If the user has no memberships (e.g. legacy/existing users or unlinked accounts), the session remains empty. The application falls back to global view so it doesn't crash.
- **APPROVAL_OWNER:** Does not receive a workspace context (always redirected to `/approval/pending`).
- **Pending/Rejected/Disabled Users:** Forbidden from getting a workspace session.

### 3. Session Cleanup
During logout, `WorkspaceService.clear_current_workspace_session()` is invoked to remove `"current_workspace_id"` from the session.

---

## Technical Integration

### AuthService Hooks
- **on_login_success:** Calls `WorkspaceService.ensure_current_workspace_session(user)`.
- **on_logout:** Calls `WorkspaceService.clear_current_workspace_session()`.
- **logout:** Explicitly calls `session.pop("current_workspace_id", None)` to guarantee clean state.

---

## Next Steps
- **Task 6.5.5:** Implement data isolation scoping in CRUD actions based on `current_workspace_id`.
