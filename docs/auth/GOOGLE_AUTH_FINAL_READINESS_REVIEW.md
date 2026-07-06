# Google Auth Final Readiness Review

## Scope
- Task 6.2.14.
- Final local/readiness review before any production enablement decision.
- No production Google auth enablement in this task.
- No Railway env/settings changes.
- No production migration.
- No new migration executable.

## Current status
- Google OAuth code path exists behind feature flag.
- GOOGLE_AUTH_ENABLED defaults to false.
- New Google users are created as pending and inactive.
- Pending users cannot access dashboard.
- OWNER can approve/reject pending users.
- Approved linked Google users can login.
- Rejected/disabled users are blocked.
- Local/password same-email accounts are not auto-linked.
- Google tokens are not stored.

## Local DB
- Expected Alembic revision: 0002_google_auth_approval.
- Local validation DB only.
- Production DATABASE_URL was not used.

## Final smoke/check results
- **unittest**: PASS (169 tests)
- **compileall**: PASS
- **git diff --check**: PASS
- **local E2E smoke status**: PASS (verified via `test_google_auth_local_e2e_smoke_flow`)
- **migration diff status**: PASS (no new migration files created or modified)

## Production enablement checklist
Before enabling on Railway:
1. Confirm production DB revision includes Google approval schema.
2. Confirm production backup/restore readiness.
3. Configure Google Cloud OAuth consent screen.
4. Configure Google redirect URI:
   `https://<production-domain>/auth/google/callback`
5. Set Railway env manually:
   - `GOOGLE_AUTH_ENABLED=true`
   - `GOOGLE_CLIENT_ID` (Railway secret only)
   - `GOOGLE_CLIENT_SECRET` (Railway secret only)
   - `GOOGLE_REDIRECT_URI` (production callback URL)
   - `GOOGLE_ALLOWED_DOMAIN` (optional)
6. Confirm OWNER can access `/users/pending`.
7. Confirm first Google test user becomes pending.
8. Confirm OWNER approve is required before app access.
9. Confirm rollback:
   - `GOOGLE_AUTH_ENABLED=false`

## Explicit non-actions in this task
- Production Google auth was not enabled.
- Railway env/settings were not changed.
- Production DATABASE_URL was not used.
- Production migration was not run.
- No Google client secret/id was committed.
- No backup/runtime artifact was committed.

## Safety confirmations
- No new migration executable.
- No workspace migration.
- No approval marker.
- `APP_VERSION` unchanged.
- Railway settings/`DATABASE_URL` unchanged.
- No production migration.
- No secrets committed.
- Excel templates not changed.
