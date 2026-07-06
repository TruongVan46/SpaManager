# Google Auth Local E2E Smoke

## Scope
- Task 6.2.13.
- Local/mock-safe only.
- No production DATABASE_URL used.
- No real Google network call.
- No real Google client secret/id committed.
- No production Railway setting changed.

## Flow verified
- New Google identity creates pending inactive user.
- Pending user cannot access dashboard.
- OWNER can view pending user.
- OWNER can approve.
- Approved Google user can login through callback.
- last_login is updated.
- Rejected/disabled users are blocked.
- Local/password same-email account is not auto-linked.
- No tokens are stored.

## Local DB
- Expected Alembic revision: 0002_google_auth_approval.
- Production migration was not run.

## Validation
- **unittest count**: 169 tests PASS (including `test_google_auth_local_e2e_smoke_flow`)
- **compileall**: PASS
- **git diff --check**: PASS

## Safety confirmations
- Google auth remains feature-flagged.
- Production remains disabled unless Railway env is explicitly configured later.
- No secrets committed.
- No backup/runtime artifacts committed.
