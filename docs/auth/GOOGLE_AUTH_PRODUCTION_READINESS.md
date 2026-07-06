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
   - `APPROVAL_OWNER_USERNAME` (system admin username for approvals)
   - `APPROVAL_OWNER_EMAIL` (system admin email)
   - `APPROVAL_OWNER_PASSWORD` (strong password, set in Railway only)
3. Confirm Google Cloud OAuth consent screen and redirect URI.
4. Confirm approval admin account (role APPROVAL_OWNER) can access `/approval/pending`.
5. Confirm backup/restore policy is understood.
6. Confirm no Google users auto-activate.
7. Confirm rollback plan:
   - set `GOOGLE_AUTH_ENABLED=false`

## Required callback URL
Use only placeholder format:
`https://<production-domain>/auth/google/callback`

## Runtime Dependencies
Google OAuth requires **both** of these packages to be installed:
- `Authlib>=1.3,<2` — OAuth2/OIDC client library
- `requests>=2.31,<3` — HTTP client required by authlib's Flask integration

> **Important**: Railway may install Authlib without `requests` if `requests` is not
> explicitly listed in `requirements.txt`. When `requests` is missing, the import
> `from authlib.integrations.flask_client import OAuth` fails with:
> `ModuleNotFoundError: No module named 'requests'`
> This causes `is_google_auth_available()` to return `False` even if all env vars are
> correctly set, and `/auth/google/start` silently falls back to `/login`.

### Diagnostic command (run in Railway Console)
```bash
python -c "from authlib.integrations.flask_client import OAuth; print(OAuth)"
```
If this fails, `requests` is missing. Redeploy after adding `requests>=2.31,<3` to requirements.txt.

## Safety
- Never commit Google client secret.
- Never paste production DATABASE_URL into docs/chat/logs.
- Do not enable Google auth without owner approval.
- Pending users require APPROVAL_OWNER approval.
