# Google Auth Schema and Migration Plan

## Scope

- Task 6.2.2.
- Schema proposal and migration planning only.
- No migration executable created.
- No runtime auth implementation.
- No production migration.

## Current User model audit

Current fields observed in `models/user.py`:

- `role`
- `is_active`
- `email`
- `email_verified`
- `auth_provider`
- `oauth_id`
- `last_login`
- `created_at`
- `updated_at`

Fields still missing for a Google approval lifecycle:

- pending / approved / rejected / disabled status field
- `approved_by` / `approved_at` tracking
- rejected tracking if needed later
- explicit `last_login_at` field if we want a dedicated audit timestamp separate from `last_login`

## Reuse existing fields

Reuse the current fields where possible:

- `email`
- `email_verified`
- `auth_provider`
- `oauth_id`
- `role`
- `is_active`
- `last_login` or a future dedicated `last_login_at` if the implementation needs clearer naming

## Proposed minimal schema

Recommended minimal set for the first Google auth approval workflow:

- `approval_status`
- `approved_by_id`
- `approved_at`
- `last_login_at`

Optional later fields if the workflow needs them:

- `rejected_by_id`
- `rejected_at`
- `rejection_reason`
- `created_via_google`
- `google_avatar_url`

## Approval status rules

- `pending` + `is_active=False`: cannot access the app
- `active` + `is_active=True`: can access
- `rejected` + `is_active=False`: cannot access
- `disabled` + `is_active=False`: cannot access

## Google registration rule

- New Google user creates a pending account.
- Never auto-activate a new Google user.
- Pending user sees a pending page.
- Owner approval is required.

## Existing account linking rule

- If an existing user is already linked by Google identity (`auth_provider` + `oauth_id`), allow login only when active.
- If the same email exists but no safe Google link exists yet, do not silently hijack the password account.
- `email_verified` from Google is required.

## Alembic migration plan

- A future Alembic migration is required after the schema proposal is approved.
- Do not create any migration file in this task.
- Test the migration first on local Docker PostgreSQL.
- Do not run production migration without explicit approval.
- Keep workspace migration separate.
- Do not create `docs/workspace/WORKSPACE_MIGRATION_EXECUTION_APPROVAL.md`.
- A future migration name could be something like `0002_google_auth_user_approval_fields.py`, but that file must not be created here.

## Backfill plan

- Existing password users should remain active.
- Legacy users may keep `approval_status='active'` after migration.
- `approved_by_id` may be nullable for legacy rows.
- `approved_at` may be nullable for legacy rows.
- `oauth_id` remains nullable.
- `auth_provider` can stay `local` for existing password users.

## Index / constraint proposal

Only propose, do not change the database in this task:

- unique `oauth_id` when present
- index on `approval_status` for the owner pending list
- keep email uniqueness rules consistent with the safe linking policy

## Test plan for the future implementation

- migration applies on local PostgreSQL
- existing users remain login-capable
- new Google user is pending
- pending user is blocked
- owner approval activates the user
- rejected / disabled users are blocked
- duplicate email cannot hijack a local account
- `oauth_id` uniqueness is enforced
- `email_verified=false` is rejected

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
