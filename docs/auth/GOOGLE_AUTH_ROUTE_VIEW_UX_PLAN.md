# Google Auth Route/View and Pending Approval UX Plan

## Scope

- Task 6.2.3.
- Route/view/UX planning only.
- No Google OAuth implementation.
- No OAuth package install.
- No migration executable.
- No production migration.
- No Railway/DATABASE_URL changes.

## Current auth UI baseline

- Current login route: `routes/auth.py` exposes `GET/POST /login`.
- Current logout route: `routes/auth.py` exposes `POST /logout`.
- Current profile route: `routes/auth.py` exposes `GET/POST /profile`.
- Current change-password route: `routes/auth.py` exposes `POST /change-password`.
- Current dashboard route: `routes/dashboard.py` exposes the main authenticated dashboard.
- Current templates involved: `templates/auth/login.html`, `templates/auth/profile.html`, `templates/layout/base.html`, `templates/layout/auth_base.html`.
- Current role / active checks observed: `models/user.py` has `role` and `is_active`; `core/auth/permissions.py` distinguishes OWNER / ADMIN / STAFF; tests already enforce staff blocking and active-session behavior.
- Existing owner/admin user management UI: yes, `routes/user.py` and `templates/user/*` provide a user management area for OWNER / ADMIN.

## Proposed routes

This is only a proposal; no code is added here.

Public/auth routes:

- `GET /auth/google/start`
- `GET /auth/google/callback`
- `GET /auth/pending`
- `GET /auth/rejected` or a similar safe denial page, optional

Owner/admin routes:

- `GET /owner/pending-users` or the existing owner/admin route style
- `POST /owner/users/<id>/approve`
- `POST /owner/users/<id>/reject`
- `POST /owner/users/<id>/disable` optional
- `POST /owner/users/<id>/reactivate` optional

If the app later uses a different blueprint or route style, keep it consistent with the existing auth and user management modules.

## Proposed templates

This is only a proposal; no template is created in this task.

- Login page: add a “Continue with Google” button.
- Pending approval page.
- Rejected / disabled access page or safe message.
- Owner pending users list.
- Approve / reject confirmation UX.
- Flash messages.

## User flow

1. User opens the login page.
2. User chooses “Continue with Google”.
3. App starts OAuth with a `state` value.
4. Callback validates `state` and `email_verified`.
5. Existing active linked Google user: login succeeds.
6. New Google user: create a pending user and redirect to the pending page.
7. Existing pending user: redirect to the pending page.
8. Rejected / disabled user: deny access and show a safe message.
9. Owner opens the pending users list.
10. Owner approves the user.
11. Approved user can log in normally.

## Pending approval UX

- Pending user must not enter the dashboard.
- The pending page should say something simple, for example: “Tài khoản của bạn đang chờ chủ spa duyệt.”
- Do not reveal sensitive owner/admin details unless needed.
- Include logout and back-to-login actions.
- Do not auto-refresh or spam requests.
- Do not auto-activate.

## Owner approval UX

- Only OWNER sees the pending users page.
- Pending list should show at least:
  - name / email
  - provider
  - created_at
  - email_verified
  - approve / reject actions
- Approve action should use CSRF if the app uses forms and CSRF.
- Reject action should allow confirmation or an optional reason.
- After approve: user becomes active.
- After reject: user cannot log in.

## Access control plan

- After every login, check `is_active` and approval status if present.
- Pending / rejected / disabled users must not receive a full app session.
- Owner route must check OWNER role.
- Do not rely on client-side checks for authorization.
- Existing password accounts must not be hijacked by a Google email match.

## Redirect and flash plan

- New pending Google user -> `/auth/pending`
- Existing pending user -> `/auth/pending`
- Rejected / disabled -> safe denial page or login flash
- Active user -> dashboard
- OAuth failure -> login with flash
- State mismatch -> login with flash, no session

## Security notes

- OAuth `state` is required.
- `email_verified` is required.
- Redirect URI must match config.
- Do not log tokens.
- Do not expose the client secret.
- CSRF is required for owner approve/reject POST actions if the app uses CSRF.
- Rate-limit or basic abuse protection can be considered later.

## Testing plan for future implementation

- Login page shows Google button only when enabled.
- Google callback creates a pending user.
- Pending user is redirected to the pending page.
- Pending user cannot access the dashboard.
- Owner can see the pending user list.
- Staff/admin non-owner cannot approve if the rule is owner-only.
- Owner approve activates the user.
- Rejected / disabled user is blocked.
- OAuth state mismatch is rejected.
- `email_verified=false` is rejected.
- Same-email local account is not silently linked.
- No token or client secret is logged.

## Implementation sequence proposal

1. Add the schema migration for approval fields after approval.
2. Add config placeholders and docs.
3. Add Google OAuth package / config behind a feature flag.
4. Add routes for start/callback/pending.
5. Add the owner pending users page and actions.
6. Add tests.
7. Run local PostgreSQL smoke.
8. Set production env vars manually only after code is ready.

## Explicit non-goals

- No code implementation in 6.2.3.
- No migration executable in 6.2.3.
- No OAuth package in 6.2.3.
- No production migration.
- No Railway config change.
- No workspace migration approval.

## Safety confirmations

- No migration executable created.
- No approval marker created.
- `APP_VERSION` unchanged.
- Railway settings / `DATABASE_URL` unchanged.
- Production migration not run.
- Production `DATABASE_URL` not used.
- No Google auth implementation.
- No OAuth package added.
- No secret committed.
