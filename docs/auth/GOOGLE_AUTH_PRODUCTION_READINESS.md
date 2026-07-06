# Google Auth Production Readiness

## Current status
- Code supports pending Google registration and approved Google login.
- Google auth remains disabled by default.
- Production Railway env has not been changed in this task.
- Production migration has not been run in this task.

## Before enabling in production
Checklist:
1. Confirm production DB is at required Alembic revision for Google approval schema.
2. Confirm Railway env vars are set manually:
   - `GOOGLE_AUTH_ENABLED=true`
   - `GOOGLE_CLIENT_ID` (set in Railway only)
   - `GOOGLE_CLIENT_SECRET` (set in Railway only)
   - `GOOGLE_REDIRECT_URI` (production callback URL, e.g. `https://<production-domain>/auth/google/callback`)
   - `GOOGLE_ALLOWED_DOMAIN` (optional)
3. Confirm Google Cloud OAuth consent screen and redirect URI.
4. Confirm owner account can access `/users/pending`.
5. Confirm backup/restore policy is understood.
6. Confirm no Google users auto-activate.
7. Confirm rollback plan:
   - set `GOOGLE_AUTH_ENABLED=false`

## Required callback URL
Use only placeholder format:
`https://<production-domain>/auth/google/callback`

## Safety
- Never commit Google client secret.
- Never paste production DATABASE_URL into docs/chat/logs.
- Do not enable Google auth without owner approval.
- Pending users require OWNER approval.
