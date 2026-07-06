# Google Auth Design and Security Plan

## Scope

- Task 6.2.1.
- Design/security plan only.
- No Google auth implementation in this task.
- No migration executable in this task.
- No production migration in this task.
- No Railway settings or `DATABASE_URL` changes.

## Current baseline

- Production DB: Railway PostgreSQL.
- Local dev DB: Docker PostgreSQL.
- SQLite: legacy/test fallback only.
- PostgreSQL-only readiness is complete through Task 6.1.7.
- Workspace production migration is still not deployed.
- No workspace migration approval marker exists.

## Current auth state

- `models/user.py` already has: `role`, `is_active`, `email`, `email_verified`, `auth_provider`, and `oauth_id`.
- `routes/auth.py` currently supports login, logout, change-password, and profile.
- There is no Google registration flow yet.
- There is no explicit `pending` user lifecycle in the user table yet.
- OWNER / ADMIN / STAFF roles already exist in the authorization layer.
- Workspace membership tables exist, but they are separate from Google auth lifecycle.

## Business rule

- Google registration must create or map a user as pending unless an existing active user is safely linked.
- New Google users must not auto-activate.
- Pending users cannot access the app.
- Only the owner can approve or activate access.
- Rejected or disabled users cannot log in.
- Owner approval workflow will be implemented in a later task.

## Proposed user lifecycle

1. User clicks “Continue with Google”.
2. App redirects to Google OAuth.
3. App validates the OAuth callback.
4. App checks `email_verified`.
5. App checks whether the Google identity or email maps to an existing user.
6. If an existing active user is safely linked, allow login.
7. If this is a new user, create a pending user.
8. If the user is already pending, show a pending approval page.
9. If the user is rejected or disabled, deny login.
10. Owner later approves the user.

## Security requirements

- Use the OAuth `state` parameter to prevent CSRF.
- Validate redirect URI.
- Require Google `email_verified`.
- Do not trust display name or avatar alone.
- Do not store Google access or refresh tokens unless there is a clear need.
- Store only the minimum identity fields needed for login, for example provider, Google subject ID, and email.
- Do not log OAuth tokens.
- Do not expose the client secret.
- Do not paste Google client secret into repo docs.
- Use environment variables for Google config.
- Pending users must not receive a full app session.
- Existing password users must not be silently hijacked by matching email without a safe linking rule.

## Data model impact proposal

This is only a proposal; no migration is created here.

If needed later, consider:

- `auth_provider` or `login_provider`
- `google_sub` or `provider_user_id`
- `email_verified`
- `status` with values like `pending`, `active`, `rejected`, `disabled`
- `approved_by`
- `approved_at`
- `last_login_at`
- `avatar_url` optional
- `created_via_google` optional

If the model already has an equivalent field, reuse it instead of adding a duplicate.

## Route/view proposal

This is only a proposal; no code is added here.

- `GET /auth/google/start`
- `GET /auth/google/callback`
- `GET /auth/pending`
- owner pending-users page
- owner approve/reject actions

If the app later uses a different blueprint or route style, keep the style consistent.

## Owner approval plan

- Pending user list is visible only to the owner.
- Owner can approve.
- Owner can reject or disable.
- Approval should record `approved_by` and `approved_at` if the schema supports it.
- Access control must check active status after login.
- Pending users should see a clear message, not the dashboard.

## Config plan

Use placeholders only:

- `GOOGLE_CLIENT_ID=<placeholder>`
- `GOOGLE_CLIENT_SECRET=<placeholder>`
- `GOOGLE_REDIRECT_URI=<placeholder>`
- `GOOGLE_AUTH_ENABLED=<optional>`
- `GOOGLE_ALLOWED_DOMAIN=<optional>`

## Testing plan

For the later implementation task, add tests for:

- New Google user becomes pending.
- Pending user cannot access the dashboard.
- Owner can approve user.
- Approved user can log in.
- Rejected or disabled user cannot log in.
- Missing `email_verified` is rejected.
- OAuth state mismatch is rejected.
- Existing password account cannot be hijacked by the same email.
- No token or client secret is logged.

## Rollout plan

- First implement behind a config flag if needed.
- Test locally on PostgreSQL first.
- Do not run a production migration without approval.
- Production environment variables must be set manually in Railway only after code is ready.
- Do not auto-activate users in production.

## Explicit non-goals

- No migration executable in 6.2.1.
- No Google OAuth package installation in 6.2.1.
- No production environment update in 6.2.1.
- No production migration in 6.2.1.
- No workspace production migration approval.

## Safety confirmations

- No migration executable created.
- No approval marker created.
- `APP_VERSION` unchanged.
- Railway settings and `DATABASE_URL` unchanged.
- Production migration not run.
- Production `DATABASE_URL` not used.
- No secret committed.
